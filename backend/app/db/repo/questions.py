"""question / quiz_attempt 的薄封装：语义化方法，内部是可读 SQL。

T4.3 去重的全部逻辑都在这里：
- `fingerprint()` 是**唯一**的归一化入口，出题与入库共用（M4 §6.3、排障表「归一化只写一处」）
- 入库用 `INSERT ... ON CONFLICT(fingerprint) DO NOTHING`，撞了指纹就查回已有 id，
  同一个条目反复出题不会让 question 表膨胀
- `quiz_attempt.user_answer` 是 TEXT：字符串原样存，列表/布尔按 JSON 存，
  读的时候用 `loads_answer()` 还原（数据契约 §3）
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from app.db.repo.items import now_iso

_WS = re.compile(r"\s+")


def normalize_question(text: str) -> str:
    """去掉所有空白后再哈希：同一道题多一个空格不该算新题。"""
    return _WS.sub("", text or "")


def fingerprint(item_id: int | None, qtype: str, question: str) -> str:
    """M4 §6.3：sha256(item_id | type | 归一化题干)。"""
    raw = f"{item_id}|{qtype}|{normalize_question(question)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def dumps_answer(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def loads_answer(value: str | None):
    if value is None:
        return None
    text = value.strip()
    if text.startswith(("[", "{", "true", "false", "null")) or text.lstrip("-").isdigit():
        try:
            return json.loads(text)
        except ValueError:
            return value
    return value


def upsert_question(
    conn: sqlite3.Connection,
    *,
    item_id: int | None,
    qtype: str,
    difficulty: str,
    payload: dict,
    fp: str,
) -> tuple[int, bool]:
    """返回 (题目 id, 是否新建)。撞指纹时复用已有 id，不重复插入。"""
    cur = conn.execute(
        """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(fingerprint) DO NOTHING""",
        (item_id, qtype, difficulty, json.dumps(payload, ensure_ascii=False), fp, now_iso()),
    )
    if cur.rowcount:
        return int(cur.lastrowid), True
    row = conn.execute("SELECT id FROM question WHERE fingerprint=?", (fp,)).fetchone()
    return int(row["id"]), False


def row_to_question(row: sqlite3.Row) -> dict:
    question = dict(row)
    try:
        payload = json.loads(question.pop("payload") or "{}")
    except (ValueError, TypeError):
        payload = {}
    question["question"] = payload.get("question", "")
    question["options"] = payload.get("options") or []
    question["answer"] = payload.get("answer")
    question["explanation"] = payload.get("explanation", "")
    return question


def get_question(conn: sqlite3.Connection, question_id: int) -> dict | None:
    """带来源标题：判分与错题本都要显示「这道题出自哪篇」。"""
    row = conn.execute(
        """SELECT q.*, i.title AS source_title
           FROM question q LEFT JOIN knowledge_item i ON i.id = q.item_id
           WHERE q.id = ?""",
        (question_id,),
    ).fetchone()
    return row_to_question(row) if row is not None else None


def list_questions(
    conn: sqlite3.Connection, *, item_id: int | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    clause, args = ("WHERE item_id = ?", [item_id]) if item_id is not None else ("", [])
    total = conn.execute(f"SELECT COUNT(*) FROM question {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM question {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return [row_to_question(r) for r in rows], total


def count_questions(conn: sqlite3.Connection, item_id: int | None = None) -> int:
    if item_id is None:
        return conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM question WHERE item_id=?", (item_id,)
    ).fetchone()[0]


def save_attempt(
    conn: sqlite3.Connection,
    *,
    question_id: int,
    user_answer,
    is_correct: int | None,
    feedback: str | None = None,
    duration_ms: int | None = None,
) -> int:
    """is_correct 三态：1 / 0 / NULL（待人工判断）。NULL 绝不能落成 0。"""
    cur = conn.execute(
        """INSERT INTO quiz_attempt
           (question_id, user_answer, is_correct, feedback, duration_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (question_id, dumps_answer(user_answer), is_correct, feedback, duration_ms, now_iso()),
    )
    return int(cur.lastrowid)


def attempts_of(conn: sqlite3.Connection, question_id: int, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT id, user_answer, is_correct, feedback, duration_ms, created_at
           FROM quiz_attempt WHERE question_id=? ORDER BY id DESC LIMIT ?""",
        (question_id, limit),
    ).fetchall()
    out = []
    for row in rows:
        attempt = dict(row)
        attempt["user_answer"] = loads_answer(attempt["user_answer"])
        out.append(attempt)
    return out
