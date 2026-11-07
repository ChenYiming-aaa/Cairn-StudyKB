"""建库与版本迁移：PRAGMA user_version 递增，按版本号顺序执行。"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from app.config import get_settings
from app.db.conn import ensure_wal_keepalive, get_conn, table_exists

log = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
VEC_FILE = Path(__file__).with_name("schema_vec.sql")
MIGRATIONS_DIR = Path(__file__).with_name("migrations")
SCHEMA_VERSION = 2

# 老库升级：{起始版本: 脚本}。只允许"追加"性质的变化，
# 改既有列必须新开一版并写清回填方式（数据契约 §1）。
UPGRADES = {
    1: "v2_ask_log.sql",   # T3.12 问答历史
}


def _vec_extension_available(conn: sqlite3.Connection) -> bool:
    """M1 未安装 sqlite-vec，这里必然返回 False；M3 装上扩展后自动生效。"""
    try:
        import sqlite_vec  # type: ignore[import-not-found]

        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        return True
    except Exception as exc:  # 扩展缺失 / 平台不允许加载 / 名称不符
        log.info("sqlite-vec 不可用，跳过 chunk_vec：%s", type(exc).__name__)
        return False


def _migrate_base(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        log.info("数据库已是 v%s，跳过建表", version)
        return
    if version == 0:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()
        log.info("已按 schema.sql 建库，user_version=%s", SCHEMA_VERSION)
        return
    # 老库逐版升级。每个版本单独提交，升到一半失败时下次能接着升，
    # 不会出现"表建了一半但版本号已经跳过去"的错位。
    while version < SCHEMA_VERSION:
        script = UPGRADES.get(version)
        if script is None:
            raise RuntimeError(
                f"未知数据库版本 user_version={version}，拒绝自动迁移"
            )
        path = MIGRATIONS_DIR / script
        if not path.exists():
            raise RuntimeError(f"缺少迁移脚本 {script}，数据库停在 v{version}")
        conn.executescript(path.read_text(encoding="utf-8"))
        version += 1
        conn.execute(f"PRAGMA user_version={version}")
        conn.commit()
        log.info("数据库已升级到 v%s（%s）", version, script)


def _migrate_vec(conn: sqlite3.Connection) -> None:
    """可选表：仅在扩展可用且表不存在时执行，失败不影响主流程（ADR-010）。"""
    if table_exists(conn, "chunk_vec"):
        return
    if not _vec_extension_available(conn):
        return
    try:
        conn.executescript(VEC_FILE.read_text(encoding="utf-8"))
        conn.commit()
        log.info("已创建 chunk_vec（sqlite-vec 可用）")
    except Exception as exc:
        conn.rollback()
        log.warning("chunk_vec 创建失败，降级为无向量表：%s", type(exc).__name__)


def init_db(path: Path | str | None = None) -> Path:
    """建库入口。返回实际使用的 DB 路径。"""
    cfg = get_settings()
    target = Path(path) if path is not None else cfg.db_path
    target.parent.mkdir(parents=True, exist_ok=True)

    # WAL 只需建库时设一次；这里单独连接设置，避免放进 executescript
    bootstrap = sqlite3.connect(str(target), timeout=10)
    try:
        bootstrap.execute("PRAGMA journal_mode=WAL")
    finally:
        bootstrap.close()

    conn = get_conn(target)
    try:
        _migrate_base(conn)
        _migrate_vec(conn)
    finally:
        conn.close()
    ensure_wal_keepalive(target)
    return target
