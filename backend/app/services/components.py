"""可选重组件（向量 / 语音 / 浏览器）的**清单、可用性判定、状态**（T8.0）。

协议收发在 `component_proc.py`；本文件只管"有没有、怎么跑、占多少盘"。

**为什么要有这一层**（ADR-027）：v0.1.0 安装包 426 MB，其中 torch / faster-whisper /
playwright 三坨占了约 560 MB 解包体积，而这三样只在特定场景用得上。M8 把它们从主包里
挪出去，改成独立 onedir + 自己的 exe，主程序只通过管道与之对话。

**为什么不是"把 wheel 装到用户目录再塞 sys.path"**：主程序是 PyInstaller 冻结的，
解释器在 `_internal/` 里，装进去的扩展必须与之 ABI 完全一致；torch 的 DLL 加载路径
还极挑，失败率不可控。三条路只有"每个组件自带解释器"是可靠的。

**可用性三态**（`resolve()`）：组件进程 > 本进程内库 > 没有。
冻结包里那三个库被 `excludes` 剔掉，`find_spec` 自然返回 None，于是自动落到组件 ——
同一份代码两种形态，**不需要 `if is_frozen` 分支**，这是这套判定最值钱的地方。
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.paths import app_path, is_frozen
from app.services import component_proc
from app.services.component_proc import ComponentError

log = logging.getLogger(__name__)

IDS = ("embed", "asr", "browser")
LABELS = {"embed": "向量检索", "asr": "视频转录", "browser": "网页渲染"}

ENTRY_EXE = "cairn-{id}.exe"        # 组件包里的入口 exe（T8.2 的 build_components.py 产出）
# 源码态能被 import 的等价实现；冻结包里这些模块在 excludes 里，find_spec 返回 None
LOCAL_MODULE = {"embed": "sentence_transformers", "asr": "faster_whisper", "browser": "playwright"}

HELLO_TTL = 30.0                    # 握手结果缓存：可用性判定每请求都跑，不能每次起进程

_hello_at: dict[str, float] = {}
_local_cache: dict[str, bool] = {}


# ── 清单 ────────────────────────────────────────────────
def manifest() -> dict:
    """`app/components.json`：随主包发布的组件清单。

    读不到不该让整个应用起不来（清单坏了最多是下载中心空着），所以吞异常。
    """
    try:
        return json.loads(app_path("components.json").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("组件清单读取失败（%s），下载中心不可用", type(exc).__name__)
        return {"manifest_version": 1, "components": []}


def entries() -> dict[str, dict]:
    return {c.get("id"): c for c in manifest().get("components", []) if c.get("id")}


def root() -> Path:
    """契约位置：`<数据目录>/components/`（数据契约 §10）。"""
    return get_settings().data_dir / "components"


def component_dir(cid: str) -> Path:
    return root() / cid


def disk_bytes(cid: str) -> int:
    total = 0
    base = component_dir(cid)
    if not base.exists():
        return 0
    for path in base.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def installed_version(cid: str) -> str:
    try:
        meta = json.loads((component_dir(cid) / "manifest.json").read_text(encoding="utf-8"))
        return str(meta.get("version") or "")
    except Exception:  # noqa: BLE001 - 没装 / 文件坏了，一律当"没有版本"
        return ""


# ── 入口定位 ────────────────────────────────────────────
def _local_ok(cid: str) -> bool:
    if cid in _local_cache:
        return _local_cache[cid]
    ok = False
    try:
        ok = importlib.util.find_spec(LOCAL_MODULE[cid]) is not None
    except Exception:  # noqa: BLE001 - 父包缺失时 find_spec 会抛而不是返回 None
        ok = False
    _local_cache[cid] = ok
    return ok


def _dev_entry(cid: str) -> list[str] | None:
    """源码态的组件入口：不用先打包就能验协议。冻结包里没有这条路径。"""
    if is_frozen():
        return None
    path = Path(__file__).resolve().parents[2] / "components" / cid / "entry.py"
    return [sys.executable, str(path), "--serve"] if path.exists() else None


def _argv(cid: str) -> list[str] | None:
    exe = component_dir(cid) / ENTRY_EXE.format(id=cid)
    if exe.exists():
        return [str(exe), "--serve"]
    return _dev_entry(cid)


# ── 可用性 ──────────────────────────────────────────────
def resolve(cid: str) -> str | None:
    """这个组件现在能用什么方式跑：`"component"` / `"local"` / `None`。

    顺序是刻意的：**装了组件就优先用组件**（它可能比本机装的新），
    组件握手失败再退回本进程内库，两者都没有才算缺。
    """
    if cid not in IDS:
        return None
    forced = os.environ.get("CAIRN_COMPONENT_MODE", "auto").strip().lower()
    if forced == "none":
        # 只为验收：模拟"这台机器什么都没装"。冻结包的真实形态由 excludes 制造，
        # 源码态却总有 torch，没有这个开关就没法在开发机上跑"无组件回归"。
        return None
    if forced == "local":
        return "local" if _local_ok(cid) else None
    if forced == "process":
        return "component" if _argv(cid) else None

    if component_dir(cid).exists() and _hello_ok(cid):
        return "component"
    if _local_ok(cid):
        return "local"
    return None


def _hello_ok(cid: str) -> bool:
    stamp = _hello_at.get(cid)
    if stamp and time.monotonic() - stamp < HELLO_TTL:
        return not component_proc.is_broken(cid)
    try:
        call(cid, "hello", {}, timeout=component_proc.HELLO_TIMEOUT, no_retry=True)
        _hello_at[cid] = time.monotonic()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("组件 %s 握手失败（%s）", cid, type(exc).__name__)
        return False


# ── 调用 ────────────────────────────────────────────────
def call(cid: str, op: str, payload: dict | None = None, on_progress=None,
         timeout: float = 120.0, no_retry: bool = False, idle: bool = False) -> dict:
    argv = _argv(cid)
    if argv is None:
        raise ComponentError("COMPONENT_MISSING", f"{LABELS.get(cid, cid)}组件还没装", cid)
    return component_proc.call(cid, argv, op, payload or {}, on_progress, timeout,
                               no_retry, idle)


# ── 生命周期 / 状态 ─────────────────────────────────────
def stop(cid: str) -> None:
    component_proc.stop(cid)


def stop_all() -> None:
    """主进程退出前调用（M8 D3）。留着孤儿进程会锁住组件目录，卸载时删不掉。"""
    component_proc.stop_all()
    _hello_at.clear()


def uninstall(cid: str) -> int:
    """停进程 → 删目录 → 返回释放的字节数。**只动 components/<id>/，不碰 data.db。**"""
    stop(cid)
    freed = disk_bytes(cid)
    base = component_dir(cid)
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    _hello_at.pop(cid, None)
    component_proc.clear_broken(cid)
    log.info("已卸载组件 %s，释放 %.1f MB", cid, freed / 1e6)
    return freed


def status(cid: str) -> dict:
    """给下载中心用（接口契约 §components 的形状，T8.4 消费）。"""
    entry = entries().get(cid, {})
    base = component_dir(cid)
    state = "missing"
    if base.exists():
        state = "broken" if component_proc.is_broken(cid) else "installed"
    return {
        "id": cid,
        "name": entry.get("name") or LABELS.get(cid, cid),
        "why": entry.get("why", ""),
        "size": int(entry.get("size") or 0),
        "version": installed_version(cid),
        "min_app_version": entry.get("min_app_version") or manifest().get("min_app_version", ""),
        "state": state,
        "mode": resolve(cid),          # component / local / null：本机现在实际怎么跑
        "bytes": disk_bytes(cid) if base.exists() else 0,
    }


def status_all() -> list[dict]:
    return [status(cid) for cid in IDS]


def reset_cache() -> None:
    """只给脚本用：忘掉握手、故障与本地探测结果。"""
    _hello_at.clear()
    _local_cache.clear()
    for cid in IDS:
        component_proc.clear_broken(cid)
