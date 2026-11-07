"""html_artifact 的薄封装：学习页产物的存取（T3.9）。

列表刻意不返回 html_content —— 一份页面几十 KB，列表页只要元信息；
预览和下载各自按 id 取全文（契约 §api/html 的四个端点）。
"""
from __future__ import annotations

import json
import sqlite3

from app.db.repo.items import now_iso


def create(
    conn: sqlite3.Connection, *, title: str, item_ids: list[int], html_content: str
) -> int:
    cur = conn.execute(
        """INSERT INTO html_artifact (title, item_ids, html_content, created_at)
           VALUES (?, ?, ?, ?)""",
        (title, json.dumps(item_ids, ensure_ascii=False), html_content, now_iso()),
    )
    return int(cur.lastrowid)


def list_artifacts(
    conn: sqlite3.Connection, *, limit: int = 20, offset: int = 0
) -> tuple[list[dict], int]:
    total = conn.execute("SELECT COUNT(*) FROM html_artifact").fetchone()[0]
    rows = conn.execute(
        """SELECT id, title, item_ids, created_at, LENGTH(CAST(html_content AS BLOB)) AS size_bytes
           FROM html_artifact ORDER BY id DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    items = []
    for row in rows:
        try:
            ids = json.loads(row["item_ids"])
        except (ValueError, TypeError):
            ids = []
        items.append({
            "id": row["id"],
            "title": row["title"],
            "item_ids": ids,
            "item_count": len(ids),
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
        })
    return items, total


def get(conn: sqlite3.Connection, artifact_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM html_artifact WHERE id=?", (artifact_id,)).fetchone()


def delete(conn: sqlite3.Connection, artifact_id: int) -> bool:
    return conn.execute("DELETE FROM html_artifact WHERE id=?", (artifact_id,)).rowcount > 0
