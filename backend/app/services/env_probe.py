"""环境自检（T2.5）：ffmpeg / whisper 模型 / embedding 模型 / sqlite-vec / LLM Key。

同一份逻辑同时供 `GET /api/env/check` 与 `scripts/env_check.py` 使用 ——
两处各写一遍必然漂移，而用户正是靠这个页面判断"为什么转录跑不起来"。

返回形状见 M2 §6.6：每项 `{ok, detail, hint?}`；失败项额外带 `code`，
其中缺 ffmpeg 必须是 `TRANSCRIBE_NO_FFMPEG`（M2 §5 DoD）。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from app.config import get_settings
from app.paths import is_frozen

log = logging.getLogger(__name__)


def _ffmpeg_hint() -> str:
    """提示要跟着"谁在跑"变：安装包用户没有 uv、也不需要理解 PATH。

    T5.7 的引导页把这段原样显示给用户看，写"uv add"或某个固定的 Anaconda 路径
    只会让人更困惑。
    """
    if is_frozen():
        return "安装包自带 ffmpeg（resources/ffmpeg），找不到说明安装不完整，请重新安装"
    return r"在 .env 里设 FFMPEG_DIR=<含 ffmpeg.exe 的目录>，或把该目录加进 PATH"


FFMPEG_HINT = _ffmpeg_hint()


def _version(exe: Path) -> str | None:
    """跑 `<exe> -version` 取版本号；跑不起来返回 None。"""
    try:
        out = subprocess.run(
            [str(exe), "-version"], capture_output=True, text=True,
            timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (out.stdout or out.stderr or "").splitlines()
    if not lines:
        return None
    parts = lines[0].split()
    # "ffmpeg version 4.3.1 Copyright (c) ..." / "ffprobe version 4.3.1 ..."
    return parts[2] if len(parts) >= 3 and parts[0] in ("ffmpeg", "ffprobe") else None


def check_ffmpeg() -> dict:
    cfg = get_settings()
    exe = cfg.ffmpeg_exe or (Path(p) if (p := shutil.which("ffmpeg")) else None)
    if exe is None or not exe.exists():
        return {"ok": False, "code": "TRANSCRIBE_NO_FFMPEG",
                "detail": "未找到 ffmpeg", "hint": FFMPEG_HINT}
    version = _version(exe)
    if version is None:
        return {"ok": False, "code": "TRANSCRIBE_NO_FFMPEG",
                "detail": f"{exe} 无法执行", "hint": FFMPEG_HINT}

    probe = cfg.ffprobe_exe or (Path(p) if (p := shutil.which("ffprobe")) else None)
    if probe is None or not probe.exists():
        return {"ok": False, "code": "TRANSCRIBE_NO_FFMPEG",
                "detail": f"ffmpeg {version} 可用，但缺少 ffprobe", "hint": FFMPEG_HINT}
    return {"ok": True, "detail": version}


def _models_dir(name: str) -> Path:
    return get_settings().data_dir / "models" / name


def check_whisper(model: str = "small") -> dict:
    """只看模型文件在不在，不加载模型（加载要几秒且吃显存）。"""
    root = _models_dir("whisper")
    downloaded = root.exists() and any(
        model in child.name.lower() for child in root.iterdir()
    )
    if downloaded:
        return {"ok": True, "detail": f"{model} 已下载"}
    return {"ok": False, "detail": f"模型 {model} 未下载",
            # 不是错误：第一次转录时自动下。提示里给真实路径，用户才知道占多少盘
            "hint": f"首次转录时自动下载（约 500MB）到 {root}"}


def check_embedding() -> dict:
    root = _models_dir("embedding")
    ready = root.exists() and any(root.iterdir())
    if ready:
        return {"ok": True, "detail": "bge-small-zh-v1.5 已下载"}
    return {"ok": False, "detail": "未加载",
            "hint": f"首次做向量检索时自动下载（bge-small-zh-v1.5，约 100MB）到 {root}"}


def check_sqlite_vec() -> dict:
    """sqlite-vec 是可选件（总纲 §3）：没装不影响任何 M2 功能。"""
    try:
        import sqlite_vec
    except ImportError:
        return {"ok": False, "detail": "未安装（可选）",
                "hint": "未装则向量检索退化为 numpy 精排，结果仍可用"}
    version = getattr(sqlite_vec, "__version__", "") or "已安装"
    return {"ok": True, "detail": version}


def check_llm() -> dict:
    cfg = get_settings()
    if cfg.has_llm_key:
        return {"ok": True, "detail": cfg.llm_model}
    return {"ok": False, "code": "LLM_NO_KEY", "detail": "未配置 LLM_API_KEY",
            # 引导页就在这个 hint 下面放输入框，所以指路要指到"页面上"，不是"去改文件"。
            # 具体存到哪由页面单独显示（`check_all()` 的 env_file），这里不重复路径。
            "hint": "在下方填入 API Key，保存后立即生效，不用重启"}


PROBE_TIMEOUT = 15.0


def _status_error(status: int) -> tuple[str, str]:
    """HTTP 状态码 → (错误码, 人话)。与 `llm.error_from` 保持同一套语义。"""
    if status in (401, 403):
        return "LLM_NO_KEY", "Key 无效或没有权限（401/403）"
    if status in (402, 429):
        return "LLM_QUOTA", "额度不足或触发限流（402/429）"
    if status == 404:
        return "LLM_MODELS_UNSUPPORTED", "该地址没有模型列表接口（404）"
    return "LLM_HTTP_ERROR", f"服务返回 HTTP {status}"


def _probe_fail(code: str, hint: str, started: float) -> dict:
    return {"ok": False, "models": [], "latency_ms": int((time.monotonic() - started) * 1000),
            "error_code": code, "hint": hint}


def probe_provider(base_url: str, api_key: str, model: str = "") -> dict:
    """探测一个 OpenAI 兼容服务：先列模型，列表拿不到再用 1 token 的 ping 判活。

    **不重试**（探测要快，失败就直说）；**绝不回显 Key**（红线 7）——
    返回里只有错误码与人话，`detail` 只允许出现状态码。
    返回 `{ok, models, latency_ms, error_code, hint}`，形状见接口契约。
    """
    base = (base_url or "").strip().rstrip("/")
    headers = {"Content-Type": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    started = time.monotonic()

    try:
        with httpx.Client(timeout=PROBE_TIMEOUT) as client:
            resp = client.get(base + "/models", headers=headers)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    models = sorted({
                        str(item.get("id")) for item in (data.get("data") or [])
                        if isinstance(item, dict) and item.get("id")
                    })
                except ValueError:
                    models = []
                return {"ok": True, "models": models,
                        "latency_ms": int((time.monotonic() - started) * 1000),
                        "error_code": None if models else "LLM_MODELS_UNSUPPORTED",
                        "hint": None if models
                                else "服务没有返回模型列表，可以手动输入模型名"}
            if resp.status_code not in (400, 404, 405, 501):
                code, hint = _status_error(resp.status_code)
                return _probe_fail(code, hint, started)

            # 服务没有 /models：退化成真的发一句话，能通就说明 Key 与地址可用
            if not model:
                return _probe_fail(
                    "LLM_MODELS_UNSUPPORTED",
                    "该服务不提供模型列表；请手动填入模型名并保存，再点探测",
                    started,
                )
            ping = client.post(
                base + "/chat/completions",
                headers=headers,
                json={"model": model, "max_tokens": 1,
                      "messages": [{"role": "user", "content": "ping"}]},
            )
            if ping.status_code in (200, 400):
                # 400 也算通了：说明地址与 Key 有效，只是这个模型名不对
                return {"ok": True, "models": [], "latency_ms": int(
                    (time.monotonic() - started) * 1000),
                    "error_code": "LLM_MODELS_UNSUPPORTED",
                    "hint": "地址与 Key 可用，但服务不提供模型列表；模型名请手动确认"}
            code, hint = _status_error(ping.status_code)
            return _probe_fail(code, hint, started)
    except httpx.TimeoutException:
        return _probe_fail("LLM_TIMEOUT", f"超过 {int(PROBE_TIMEOUT)} 秒没有响应", started)
    except Exception as exc:  # noqa: BLE001 - 只暴露异常类型，不带 URL 里的参数
        log.warning("provider 探测失败：%s", type(exc).__name__)
        return _probe_fail("LLM_HTTP_ERROR", "连不上这个地址，检查网络与 base_url", started)


def check_all() -> dict:
    # `env_file` 不是检查项，是给首次引导页显示"Key 会存到哪"的路径。
    # 放在最外层而不是塞进某一项里，因为它和任何一项的 ok/fail 都无关。
    return {
        "ffmpeg": check_ffmpeg(),
        "whisper": check_whisper(),
        "embedding": check_embedding(),
        "sqlite_vec": check_sqlite_vec(),
        "llm": check_llm(),
        "env_file": str(get_settings().env_file),
    }
