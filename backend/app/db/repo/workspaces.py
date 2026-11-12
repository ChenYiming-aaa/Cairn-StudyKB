"""workspace 的薄封装：用户自建的一层归类（ADR-032，不嵌套）。"""
from __future__ import annotations

import sqlite3

from app.db.repo.items import now_iso

_UPDATABLE = {"name", "color", "sort_order"}


def create(
    conn: sqlite3.Connection, *, name: str, color: str | None = None, sort_order: int = 0
) -> int:
    stamp = now_iso()
    cur = conn.execute(
        """INSERT INTO workspace (name, color, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (name, color, sort_order, stamp, stamp),
    )
    return int(cur.lastrowid)


def get(conn: sqlite3.Connection, workspace_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM workspace WHERE id=?", (workspace_id,)).fetchone()


def list_workspaces(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """带每条工作区的内容数；「未归类」不在这张表里（走 items.list_items 的 "none"）。"""
    return conn.execute(
        """SELECT w.*, COUNT(k.id) AS item_count
           FROM workspace w LEFT JOIN knowledge_item k ON k.workspace_id = w.id
           GROUP BY w.id ORDER BY w.sort_order, w.id"""
    ).fetchall()


def update(conn: sqlite3.Connection, workspace_id: int, fields: dict) -> sqlite3.Row | None:
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE and v is not None}
    if not fields:
        return get(conn, workspace_id)
    sets = [f"{k}=?" for k in fields]
    conn.execute(
        f"UPDATE workspace SET {', '.join(sets)}, updated_at=? WHERE id=?",
        [*fields.values(), now_iso(), workspace_id],
    )
    return get(conn, workspace_id)


def delete(conn: sqlite3.Connection, workspace_id: int) -> bool:
    """内容不跟着删：外键 ON DELETE SET NULL 让它们回落到「未归类」。"""
    return conn.execute(
        "DELETE FROM workspace WHERE id=?", (workspace_id,)
    ).rowcount > 0
