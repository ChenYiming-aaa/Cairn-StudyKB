"""环境自检（T2.5）：ffmpeg / whisper 模型 / embedding 模型 / sqlite-vec / LLM Key。

同一份逻辑同时供 `GET /api/env/check` 与 `scripts/env_check.py` 使用 ——
两处各写一遍必然漂移，而用户正是靠这个页面判断"为什么转录跑不起来"。

返回形状见 M2 §6.6：每项 `{ok, detail, hint?}`；失败项额外带 `code`，
其中缺 ffmpeg 必须是 `TRANSCRIBE_NO_FFMPEG`（M2 §5 DoD）。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import get_settings

FFMPEG_HINT = r"在 .env 里设 FFMPEG_DIR=D:\Anaconda3\Library\bin（IDE/Electron 启动时 PATH 不含它）"


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
            "hint": "首次转录会自动下载（约 500MB，存 data/models/whisper）"}


def check_embedding() -> dict:
    root = _models_dir("embedding")
    ready = root.exists() and any(root.iterdir())
    if ready:
        return {"ok": True, "detail": "bge-small-zh-v1.5 已下载"}
    return {"ok": False, "detail": "未加载",
            "hint": "M3 首次使用自动下载（bge-small-zh-v1.5，约 100MB）"}


def check_sqlite_vec() -> dict:
    """sqlite-vec 是可选件（总纲 §3）：没装不影响任何 M2 功能。"""
    try:
        import sqlite_vec
    except ImportError:
        return {"ok": False, "detail": "未安装（可选）",
                "hint": "M3 需要时 uv add sqlite-vec；未装则向量检索退化为 numpy 精排"}
    version = getattr(sqlite_vec, "__version__", "") or "已安装"
    return {"ok": True, "detail": version}


def check_llm() -> dict:
    cfg = get_settings()
    if cfg.has_llm_key:
        return {"ok": True, "detail": cfg.llm_model}
    return {"ok": False, "code": "LLM_NO_KEY", "detail": "未配置 LLM_API_KEY",
            "hint": "在 .env 里设置 LLM_API_KEY（Key 只从 .env 读，不接受命令行）"}


def check_all() -> dict:
    return {
        "ffmpeg": check_ffmpeg(),
        "whisper": check_whisper(),
        "embedding": check_embedding(),
        "sqlite_vec": check_sqlite_vec(),
        "llm": check_llm(),
    }
