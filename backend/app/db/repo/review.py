"""review_item 的薄封装（T4.6）：间隔规则 + 待复习队列 + 错题本。

间隔规则刻意简单（M4 §6.5 / 数据契约 §4，不做 SM-2 / FSRS）：

    答错：interval = 1，lapses += 1
    答对且 interval < 7：interval = min(interval * 2, 7)   即 1→2→4→7
    答对且 interval >= 7：interval = 15

`due_at` **存 UTC**（用户 2026-11-07 裁决），比较只在 Python 侧做：
本地时间带 `+08:00`、UTC 带 `+00:00`，混着进 SQL 比字典序必错（数据契约 §3）。
所以待复习查询是「取全表 → 逐行转 aware datetime → 过滤」，不写成 `WHERE due_at <= ?`。
个人库的 review_item 只有几百行，这个代价换取的是不会静默漏题。

`apply()` 的 correct 允许 None：简答批改失败时 `is_correct IS NULL`，
**待人工判断的题不排期**，既不推进也不拉回，等人工裁定。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from app.db.repo.items import now_iso
from app.db.repo.questions import row_to_question

UTC = timezone.utc
MAX_INTERVAL = 15
CAP_INTERVAL = 7           # interval < 7 时翻倍，到 7 之后直接跳 15


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(UTC)


def to_aware(value: str) -> datetime:
    """`fromisoformat` 能同时吃 `+08:00` 与 `+00:00`；无时区的老数据按 UTC 解释。"""
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def to_utc_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def next_interval(interval: int, correct: bool) -> int:
    if not correct:
        return 1
    if interval < CAP_INTERVAL:
        return min(max(interval, 1) * 2, CAP_INTERVAL)
    return MAX_INTERVAL


def get(conn: sqlite3.Connection, question_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM review_item WHERE question_id=?", (question_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def apply(
    conn: sqlite3.Connection, question_id: int, correct: bool | None, *,
    now: datetime | None = None,
) -> dict | None:
    """按一次作答结果写/推进复习项，返回新的排期；None 表示这次不需要排期。

    - `correct is None`：批改失败/待人工判断 → 不排期（绝不因为没批出来就把题塞进队列）
    - `correct is True` 且队列里没有这题：从没答错过，答对了没必要复习 → 不新建
    - `correct is False`：新建或重置为明天
    """
    if correct is None:
        return None

    current = get(conn, question_id)
    if current is None and correct:
        return None

    interval = 1 if current is None else next_interval(int(current["interval_days"]), correct)
    lapses = (int(current["lapses"]) if current else 0) + (0 if correct else 1)
    due_at = to_utc_iso(_now(now) + timedelta(days=interval))
    result = 1 if correct else 0

    conn.execute(
        """INSERT INTO review_item
               (question_id, due_at, interval_days, lapses, last_result, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(question_id) DO UPDATE SET
               due_at        = excluded.due_at,
               interval_days = excluded.interval_days,
               lapses        = excluded.lapses,
               last_result   = excluded.last_result,
               updated_at    = excluded.updated_at""",
        (question_id, due_at, interval, lapses, result, now_iso()),
    )
    return {
        "question_id": question_id,
        "due_at": due_at,
        "interval_days": interval,
        "lapses": lapses,
        "last_result": result,
    }


_DUE_SQL = """
SELECT r.id AS review_id, r.due_at, r.interval_days, r.lapses, r.last_result,
       q.*, i.title AS source_title
FROM review_item r
JOIN question q ON q.id = r.question_id
LEFT JOIN knowledge_item i ON i.id = q.item_id
"""


def _row_to_due(row: sqlite3.Row, moment: datetime) -> dict:
    question = row_to_question(row)
    question["question_id"] = question.pop("id")
    question["source_item_id"] = question.pop("item_id")
    question["review_id"] = question.pop("review_id")
    due = to_aware(question["due_at"])
    question["overdue_days"] = max(0, (moment - due).days)
    question["due_local"] = due.astimezone().isoformat(timespec="seconds")
    return question


def due(
    conn: sqlite3.Connection, *, now: datetime | None = None, limit: int = 20
) -> tuple[list[dict], int]:
    """返回 (到期的题, 到期总数)。到期 = `due_at <= now`，按到期时间从旧到新。"""
    moment = _now(now)
    rows = conn.execute(_DUE_SQL + " ORDER BY r.due_at").fetchall()
    ready = [row for row in rows if to_aware(row["due_at"]) <= moment]
    return [_row_to_due(row, moment) for row in ready[:limit]], len(ready)


_WRONG_SQL = """
SELECT q.*, i.title AS source_title,
       r.due_at, r.interval_days, r.lapses,
       (SELECT COUNT(*) FROM quiz_attempt a
          WHERE a.question_id = q.id AND a.is_correct = 0) AS wrong_count,
       (SELECT MAX(a.created_at) FROM quiz_attempt a
          WHERE a.question_id = q.id AND a.is_correct = 0) AS last_wrong_at
FROM question q
LEFT JOIN knowledge_item i ON i.id = q.item_id
LEFT JOIN review_item r ON r.question_id = q.id
WHERE (SELECT a.is_correct FROM quiz_attempt a
         WHERE a.question_id = q.id ORDER BY a.id DESC LIMIT 1) = 0
"""


def wrong(
    conn: sqlite3.Connection, *, limit: int = 20, offset: int = 0
) -> tuple[list[dict], int]:
    """错题本 = **最近一次作答明确答错**的题。

    复习答对之后 `last_result` 变 1、这个查询就不再返回它——错题本描述的是
    「现在还没弄懂的东西」，不是「历史上错过的东西」；历史仍可在 `quiz_attempt` 里查。
    待人工判断（`is_correct IS NULL`）既不算错也不算对，不进错题本。
    """
    total = conn.execute(f"SELECT COUNT(*) FROM ({_WRONG_SQL})").fetchone()[0]
    rows = conn.execute(
        _WRONG_SQL + " ORDER BY last_wrong_at DESC, q.id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    items = []
    for row in rows:
        question = row_to_question(row)
        question["question_id"] = question.pop("id")
        question["source_item_id"] = question.pop("item_id")
        items.append(question)
    return items, int(total)


def wrong_total(conn: sqlite3.Connection) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM ({_WRONG_SQL})").fetchone()[0])


def tracked_total(conn: sqlite3.Connection) -> int:
    """复习队列里的题数（不等于到期数：明天才到期的不算 due）。"""
    return int(conn.execute("SELECT COUNT(*) FROM review_item").fetchone()[0])
