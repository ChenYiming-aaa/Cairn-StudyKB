"""只读资源的定位：源码运行 与 PyInstaller 冻结运行共用一套口径。

为什么需要单独一个模块（T5.5）：
打包前所有路径都靠 `Path(__file__).resolve().parents[n]` 硬算，冻结后这个算式会指向
`_internal/` 里的假路径（`__file__` 是 `<_MEIPASS>/app/config.py`，文件并不存在），
于是 `prompts/` `templates/` 一律读不到 —— M5 §6.4 列的第一条打包失败原因。

两条硬约定：
1. **只读资源**（prompts / templates）走 `app_path()`，源码与冻结都对；
2. **可写数据**（data.db / logs / models / tmp）一律由 `Settings.data_dir` 决定，
   **绝不能**用这里的函数拼 —— 安装目录在 `Program Files` 下没有写权限（M5 §1 约束 4）。

PyInstaller 的 `--add-data "app/prompts;app/prompts"` 把资源铺在 `_MEIPASS/app/` 下，
与源码树 `backend/app/` 同形，所以两边都能用 `app_path("prompts")` 一条路。
"""
from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """只读资源的根。

    - 冻结（onedir / onefile）：`sys._MEIPASS`（onedir 下是 `<app>/_internal`）
    - 源码：`backend/`（本文件在 `backend/app/paths.py`）
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


def app_path(rel: str) -> Path:
    """`app/` 下的只读资源，如 `app_path("prompts")` → `backend/app/prompts`。"""
    return resource_root() / "app" / rel


def install_root() -> Path:
    """安装目录（exe 所在目录）。源码运行时是 `backend/`，仅供日志与报错文案用。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
