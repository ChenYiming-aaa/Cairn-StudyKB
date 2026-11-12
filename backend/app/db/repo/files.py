"""item_file 的薄封装：落盘原件的元数据（ADR-031，只存相对路径）。"""
from __future__ import annotations

import sqlite3

_UPDATABLE = {"role", "original_name", "ext", "mime", "size", "sha256",
              "stored_path", "page_count", "has_text_layer", "ocr_status"}


def create(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    role: str = "main",
    original_name: str | None = None,
    ext: str | None = None,
    mime: str | None = None,
    size: int | None = None,
    sha256: str | None = None,
    stored_path: str | None = None,
    page_count: int = 0,
    has_text_layer: int = 0,
    ocr_status: str = "none",
) -> int:
    cur = conn.execute(
        """INSERT INTO item_file
           (item_id, role, original_name, ext, mime, size, sha256, stored_path,
            page_count, has_text_layer, ocr_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, role, original_name, ext, mime, size, sha256, stored_path,
         page_count, has_text_layer, ocr_status),
    )
    return int(cur.lastrowid)


def get(conn: sqlite3.Connection, file_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM item_file WHERE id=?", (file_id,)).fetchone()


def list_by_item(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM item_file WHERE item_id=? ORDER BY id", (item_id,)
    ).fetchall()


def find_by_hash(conn: sqlite3.Connection, digest: str) -> sqlite3.Row | None:
    """同文件不重复占盘：sha256 命中即复用已有原件。"""
    return conn.execute(
        "SELECT * FROM item_file WHERE sha256=? ORDER BY id LIMIT 1", (digest,)
    ).fetchone()


def update(conn: sqlite3.Connection, file_id: int, fields: dict) -> sqlite3.Row | None:
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE and v is not None}
    if not fields:
        return get(conn, file_id)
    sets = [f"{k}=?" for k in fields]
    conn.execute(
        f"UPDATE item_file SET {', '.join(sets)} WHERE id=?",
        [*fields.values(), file_id],
    )
    return get(conn, file_id)


def set_ocr_status(conn: sqlite3.Connection, file_id: int, status: str) -> None:
    """识别进度每页都会写，别为了拿返回值多查一次。"""
    conn.execute("UPDATE item_file SET ocr_status=? WHERE id=?", (status, file_id))


def reset_running(conn: sqlite3.Connection) -> int:
    """启动时把残留的 `running` 拨回 `pending`。

    识别是后台线程，进程被 kill（或断点续跑前崩溃）时没有机会写回状态，
    库里就会永远停在 `running`，界面一直转圈、重识别还被判「正在跑」。
    后端是单进程，启动时看到 `running` 一定是上次没跑完 —— 这里必须清掉（T9.6）。
    """
    return conn.execute(
        "UPDATE item_file SET ocr_status='pending' WHERE ocr_status='running'"
    ).rowcount


def link_item(conn: sqlite3.Connection, item_id: int, file_id: int) -> None:
    """把原件挂回内容（`knowledge_item.file_id` 是反向指针）。

    建内容时还不知道 file_id（`item_file.item_id` 是 NOT NULL，只能先有内容再有原件行），
    所以这一列只能事后补。写在 files 这一侧而不是 items：原件与内容的挂接属于原件的事。
    """
    conn.execute("UPDATE knowledge_item SET file_id=? WHERE id=?", (file_id, item_id))


def delete(conn: sqlite3.Connection, file_id: int) -> bool:
    return conn.execute("DELETE FROM item_file WHERE id=?", (file_id,)).rowcount > 0
