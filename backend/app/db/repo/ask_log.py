"""ask_log 的薄封装：问答历史（T3.12）。

刻意只存**单轮**问答：一行 = 一个问题 + 一次答案 + 当时的来源快照。
不存 session、不存上下文，追问就是新的一行 —— 与 `/api/ask` 的无状态语义一致。
"""
from __future__ import annotations

import sqlite3

from app.db.repo.items import dumps, loads, now_iso

LOG_COLUMNS = (
    "id", "question", "answer", "sources_json", "match_type", "fallback",
    "no_result", "error_code", "prompt_tokens", "completion_tokens",
    "duration_ms", "created_at",
)


def save(
    conn: sqlite3.Connection,
    *,
    question: str,
    answer: str,
    sources: list[dict] | None = None,
    match_type: str | None = None,
    fallback: str | None = None,
    no_result: bool = False,
    error_code: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    duration_ms: int | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO ask_log
           (question, answer, sources_json, match_type, fallback, no_result,
            error_code, prompt_tokens, completion_tokens, duration_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (question, answer or "", dumps(sources) if sources else None,
         match_type, fallback, 1 if no_result else 0, error_code,
         prompt_tokens, completion_tokens, duration_ms, now_iso()),
    )
    return int(cur.lastrowid)


def row_to_log(row: sqlite3.Row, *, with_sources: bool = True) -> dict:
    item = {key: row[key] for key in LOG_COLUMNS if key in row.keys()}
    item["no_result"] = bool(item.get("no_result"))
    if with_sources:
        item["sources"] = loads(item.pop("sources_json", None)) or []
    else:
        item.pop("sources_json", None)
    return item


def list_logs(conn: sqlite3.Connection, *, limit: int = 30, offset: int = 0) -> list[dict]:
    """时间倒序。列表不带快照正文（省流量），点开详情再取。"""
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    rows = conn.execute(
        "SELECT * FROM ask_log ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    out = []
    for row in rows:
        item = row_to_log(row, with_sources=False)
        # 列表里**不返回完整答案**，只给 80 字预览：抽屉只需要认出是哪一条，
        # 完整内容点开详情再取（也避免一次拉 50 条长答案）
        answer = item.pop("answer", "") or ""
        item["answer_preview"] = answer[:80] + ("…" if len(answer) > 80 else "")
        item["source_count"] = len(loads(row["sources_json"]) or [])
        out.append(item)
    return out


def get_log(conn: sqlite3.Connection, log_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM ask_log WHERE id=?", (log_id,)).fetchone()
    return row_to_log(row) if row else None


def delete_log(conn: sqlite3.Connection, log_id: int) -> bool:
    cur = conn.execute("DELETE FROM ask_log WHERE id=?", (log_id,))
    return cur.rowcount > 0


def count_logs(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM ask_log").fetchone()[0]


def clear_logs(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM ask_log")
    return cur.rowcount
