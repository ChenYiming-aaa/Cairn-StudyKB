"""item_page 的薄封装：逐页文字 + 页图，识别结果必须缓存（单页实测约 2.8 秒）。"""
from __future__ import annotations

import sqlite3


def upsert(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    file_id: int,
    page_no: int,
    text: str,
    source: str = "ocr",
    avg_conf: float | None = None,
    line_conf: str | None = None,
    image_path: str | None = None,
) -> None:
    """重识别某页只覆盖识别结果；`text_reviewed`（人工复核）不在这条 UPDATE 里，不能丢。

    `line_conf` 是**与 `text` 逐行对齐**的 JSON 数组（T9.10 原文页签标黄用），
    抽取来的页没有这个概念，传 None。
    """
    conn.execute(
        """INSERT INTO item_page
           (item_id, file_id, page_no, text, source, avg_conf, line_conf, image_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(file_id, page_no) DO UPDATE SET
             text=excluded.text, source=excluded.source,
             avg_conf=excluded.avg_conf, line_conf=excluded.line_conf,
             image_path=excluded.image_path""",
        (item_id, file_id, page_no, text, source, avg_conf, line_conf, image_path),
    )


def get(conn: sqlite3.Connection, file_id: int, page_no: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM item_page WHERE file_id=? AND page_no=?", (file_id, page_no)
    ).fetchone()


def list_by_file(conn: sqlite3.Connection, file_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM item_page WHERE file_id=? ORDER BY page_no", (file_id,)
    ).fetchall()


def set_reviewed(conn: sqlite3.Connection, file_id: int, page_no: int, reviewed: str) -> None:
    """只写复核结果；`item_page.text` 是原始识别文本，永不覆盖（需求文档 §8.5）。"""
    conn.execute(
        "UPDATE item_page SET text_reviewed=? WHERE file_id=? AND page_no=?",
        (reviewed, file_id, page_no),
    )


def delete_by_file(conn: sqlite3.Connection, file_id: int) -> int:
    return conn.execute("DELETE FROM item_page WHERE file_id=?", (file_id,)).rowcount
