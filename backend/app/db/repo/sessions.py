"""study_session 的薄封装（T5.1 / T5.2）：只用时间戳推算，不做任何累加。

**表结构一行没改**（数据契约 §3 已定），所以「暂停累计」用现有两列表达：

    duration_seconds = 已结算时长（不含正在走的那一段）
    start_time       = 当前段的起点；status='paused' 时它就是暂停时刻

于是：

    elapsed = duration_seconds + (now - start_time)   # 仅 status='running'
    elapsed = duration_seconds                        # paused / done / abandoned

这样每一次状态变化（pause / resume / finish / abandon / heartbeat）都是同一件事：
**把当前段卷进 duration_seconds，再把 start_time 挪到当下**。M5 §6.1 的
`pausedAccum` + `pausedAt` 就是这两列，前端与后端用同一套公式，不会各算一个数。

`heartbeat` 是这套口径的副产品：它不改 status，只做一次卷账 + 重置锚点，
所以进程被强杀时最多丢一个心跳间隔（15 秒）的时长（M5 §6.2）。

`start_time` 用**带本地时区偏移**的 ISO（与 `items.now_iso()` 一致），
差值一律在 Python 侧算，不写成 SQL 时间函数——数据契约 §3 的教训：
本地时间与 UTC 混着进 SQL 比字典序必错。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from app.db.repo.items import now_iso

ACTIVE = ("running", "paused")
TERMINAL = ("done", "abandoned")
STALE_HOURS = 4              # M5 §6.2：启动时把放太久的 active session 收掉

_SELECT = """
SELECT s.*, i.title AS target_title
FROM study_session s
LEFT JOIN knowledge_item i ON i.id = s.target_id AND s.target_type = 'item'
"""


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now().astimezone()


def parse(value: str) -> datetime:
    """`fromisoformat` 同时吃 `+08:00` 与 `+00:00`；无时区的老数据按本地时区解释。"""
    moment = datetime.fromisoformat(value)
    return moment.astimezone() if moment.tzinfo is None else moment


def iso(moment: datetime) -> str:
    return moment.astimezone().isoformat(timespec="seconds")


def elapsed_seconds(row, now: datetime | None = None) -> int:
    """有效时长（秒），暂停期间不计。**唯一**的时长算法，接口与统计都走它。"""
    total = int(row["duration_seconds"] or 0)
    if row["status"] != "running":
        return total
    anchor = parse(row["start_time"])
    total += max(0, int((_now(now) - anchor).total_seconds()))
    return total


def row_to_session(row, now: datetime | None = None) -> dict:
    return {
        "id": row["id"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "target_title": row["target_title"] if "target_title" in row.keys() else None,
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "duration_seconds": int(row["duration_seconds"] or 0),
        "elapsed_seconds": elapsed_seconds(row, now),
        "planned_seconds": int(row["planned_seconds"] or 0),
        "status": row["status"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def get(conn: sqlite3.Connection, session_id: int) -> dict | None:
    row = conn.execute(_SELECT + " WHERE s.id=?", (session_id,)).fetchone()
    return row_to_session(row) if row is not None else None


def get_row(conn: sqlite3.Connection, session_id: int):
    return conn.execute(_SELECT + " WHERE s.id=?", (session_id,)).fetchone()


def active(conn: sqlite3.Connection) -> dict | None:
    """进行中 = running 或 paused（**暂停也算占用**，否则可以同时开两个计时）。"""
    row = conn.execute(
        _SELECT + " WHERE s.status IN ('running','paused') ORDER BY s.id DESC LIMIT 1"
    ).fetchone()
    return row_to_session(row) if row is not None else None


def start(
    conn: sqlite3.Connection, *, target_type: str, target_id: int | None,
    planned_seconds: int, now: datetime | None = None,
) -> dict:
    """新建一个 running session。调用方负责先查 `active()` 并拒绝并发。"""
    moment = _now(now)
    cur = conn.execute(
        """INSERT INTO study_session
               (target_type, target_id, start_time, duration_seconds,
                planned_seconds, status, created_at)
           VALUES (?, ?, ?, 0, ?, 'running', ?)""",
        (target_type, target_id, iso(moment), int(planned_seconds), now_iso()),
    )
    return get(conn, int(cur.lastrowid))


def _roll(conn: sqlite3.Connection, session_id: int, moment: datetime, **extra) -> None:
    """把当前段卷进 duration_seconds，并把锚点挪到 moment；extra 里可带 status/end_time/note。"""
    row = get_row(conn, session_id)
    total = elapsed_seconds(row, moment)
    fields = {"duration_seconds": total, "start_time": iso(moment), **extra}
    assigns = ", ".join(f"{key}=?" for key in fields)
    conn.execute(
        f"UPDATE study_session SET {assigns} WHERE id=?",
        (*fields.values(), session_id),
    )


def pause(conn: sqlite3.Connection, session_id: int, now: datetime | None = None) -> dict:
    _roll(conn, session_id, _now(now), status="paused")
    return get(conn, session_id)


def resume(conn: sqlite3.Connection, session_id: int, now: datetime | None = None) -> dict:
    """恢复：只把锚点挪到当下，duration_seconds 不动（暂停期间本来就不算）。"""
    conn.execute(
        "UPDATE study_session SET status='running', start_time=? WHERE id=?",
        (iso(_now(now)), session_id),
    )
    return get(conn, session_id)


def heartbeat(conn: sqlite3.Connection, session_id: int, now: datetime | None = None) -> dict:
    """卷一次账并重置锚点，**不改 status**（paused/终态时原样返回，不报错）。

    不报错是故意的：闭窗时 `sendBeacon` 与「暂停」几乎同时到达，
    迟到的心跳不该让前端弹一个 409。
    """
    row = get_row(conn, session_id)
    if row is not None and row["status"] == "running":
        _roll(conn, session_id, _now(now))
    return get(conn, session_id)


def finish(
    conn: sqlite3.Connection, session_id: int, *, note: str | None = None,
    now: datetime | None = None,
) -> dict:
    moment = _now(now)
    _roll(conn, session_id, moment, status="done", end_time=iso(moment),
          **({"note": note} if note is not None else {}))
    return get(conn, session_id)


def abandon(conn: sqlite3.Connection, session_id: int, now: datetime | None = None) -> dict:
    moment = _now(now)
    _roll(conn, session_id, moment, status="abandoned", end_time=iso(moment))
    return get(conn, session_id)


def history(
    conn: sqlite3.Connection, *, target_type: str | None = None,
    target_id: int | None = None, limit: int = 20, offset: int = 0,
) -> tuple[list[dict], int]:
    """学习记录：按条目/时间倒序，只给 done / abandoned（进行中的另有 current 端点）。"""
    where = ["s.status IN ('done','abandoned')"]
    params: list = []
    if target_type:
        where.append("s.target_type=?")
        params.append(target_type)
    if target_id is not None:
        where.append("s.target_id=?")
        params.append(target_id)
    clause = " WHERE " + " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM study_session s{clause}", params
    ).fetchone()[0]
    rows = conn.execute(
        _SELECT + clause + " ORDER BY s.id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [row_to_session(row) for row in rows], int(total)


def abandon_stale(conn: sqlite3.Connection, now: datetime | None = None) -> int:
    """启动清理：active 且**会话开始**早于 4 小时 → abandoned，时长按计划时长封顶。

    判据用 `created_at` 而不是 `start_time`：心跳会把锚点一直往前挪，
    用锚点判断等于「只要前端还开着就永远不算超时」，正好放过要防的那一种。

    为什么封顶：忘关一晚的 session 会算出 10 小时专注，直接污染周统计；
    而正常「提前完成/超时完成」走 finish，记真实时长，不封顶。
    """
    moment = _now(now)
    cutoff = moment - timedelta(hours=STALE_HOURS)
    rows = conn.execute(
        _SELECT + " WHERE s.status IN ('running','paused')"
    ).fetchall()
    closed = 0
    for row in rows:
        if parse(row["created_at"]) > cutoff:
            continue
        capped = min(elapsed_seconds(row, moment), int(row["planned_seconds"] or 0))
        conn.execute(
            """UPDATE study_session
                  SET status='abandoned', duration_seconds=?, end_time=?
                WHERE id=?""",
            (capped, iso(moment), row["id"]),
        )
        closed += 1
    return closed
