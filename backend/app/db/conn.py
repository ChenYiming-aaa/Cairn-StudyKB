"""SQLite 连接策略：每请求新建连接，不用全局单例（线程池里会撞 check_same_thread）。"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import get_settings

# Windows + WAL 竞态修复：最后一个连接关闭时 SQLite 会 checkpoint 并删除 -wal/-shm，
# 另一线程此刻打开连接会被判定为只读（attempt to write a readonly database）。
# 持有一个空闲连接可阻止 WAL 文件被清理。它不执行任何业务 SQL，
# 业务连接仍是「每请求新建」（M1 §6.2），不存在跨线程共用连接的问题。
_keepalive: sqlite3.Connection | None = None
_keepalive_lock = threading.Lock()


def ensure_wal_keepalive(path: Path | str | None = None) -> None:
    target = Path(path) if path is not None else db_path()
    global _keepalive
    with _keepalive_lock:
        if _keepalive is not None:
            return
        conn = sqlite3.connect(str(target), timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        _keepalive = conn


def db_path() -> Path:
    return get_settings().db_path


def get_conn(path: Path | str | None = None) -> sqlite3.Connection:
    """建连接；path 用于 status.py 打开复制出来的 DB 文件。"""
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")  # 连接级，必须每个连接都开
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)
    ).fetchone()
    return row is not None
