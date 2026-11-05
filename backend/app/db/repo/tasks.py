"""agent_task 的薄封装：语义化方法，内部是可读 SQL。"""
from __future__ import annotations

import sqlite3

from app.db.repo.items import dumps, now_iso

TASK_COLUMNS = (
    "id", "type", "status", "progress", "stage", "input_json", "output_json",
    "error_code", "error_msg", "created_at", "updated_at",
)


def create_task(conn: sqlite3.Connection, *, type: str, input_json=None) -> str:
    import uuid

    task_id = str(uuid.uuid4())
    stamp = now_iso()
    conn.execute(
        """INSERT INTO agent_task
           (id, type, status, progress, input_json, created_at, updated_at)
           VALUES (?, ?, 'queued', 0, ?, ?, ?)""",
        (task_id, type, dumps(input_json) if input_json is not None else None, stamp, stamp),
    )
    return task_id


def get_task(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM agent_task WHERE id=?", (task_id,)).fetchone()


def count_tasks(conn: sqlite3.Connection, *, status: str | None = None) -> int:
    if status:
        return conn.execute(
            "SELECT COUNT(*) FROM agent_task WHERE status=?", (status,)
        ).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM agent_task").fetchone()[0]


def list_tasks(
    conn: sqlite3.Connection, *, limit: int = 50, status: str | None = None
) -> list[sqlite3.Row]:
    limit = max(1, min(int(limit), 200))
    if status:
        return conn.execute(
            "SELECT * FROM agent_task WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM agent_task ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


_UPDATABLE = {
    "status", "progress", "stage", "output_json", "error_code", "error_msg", "type", "input_json",
}


def update_task(conn: sqlite3.Connection, task_id: str, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not fields:
        return
    for key in ("output_json", "input_json"):
        if key in fields and fields[key] is not None and not isinstance(fields[key], str):
            fields[key] = dumps(fields[key])
    sets = [f"{k}=?" for k in fields]
    args = [*fields.values(), now_iso(), task_id]
    conn.execute(
        f"UPDATE agent_task SET {', '.join(sets)}, updated_at=? WHERE id=?", args
    )


def mark_stale_running_failed(conn: sqlite3.Connection) -> int:
    """启动时把上次进程残留的 queued/running 标为 failed，避免永久卡住。"""
    cur = conn.execute(
        """UPDATE agent_task
           SET status='failed', error_code='TASK_INTERRUPTED',
               error_msg='服务重启，任务中断', updated_at=?
           WHERE status IN ('queued','running')""",
        (now_iso(),),
    )
    return cur.rowcount
