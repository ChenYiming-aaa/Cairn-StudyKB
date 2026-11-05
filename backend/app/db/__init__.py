"""db 包：连接、迁移、repo 薄封装。"""
from app.db.conn import get_conn, table_exists
from app.db.migrate import init_db

__all__ = ["get_conn", "table_exists", "init_db"]
