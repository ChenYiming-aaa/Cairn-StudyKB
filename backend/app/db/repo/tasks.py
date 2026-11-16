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


def update_progress(
    conn: sqlite3.Connection, task_id: str, *, progress: int, stage: str | None = None
) -> int:
    """只对 queued/running 生效：迟到的回调不许把已 done/failed 的进度改回去。

    stage 传 None 时保留原值（COALESCE），这样只报进度不报阶段也不会把阶段清空。
    """
    cur = conn.execute(
        """UPDATE agent_task SET progress=?, stage=COALESCE(?, stage), updated_at=?
           WHERE id=? AND status IN ('queued','running')""",
        (progress, stage, now_iso(), task_id),
    )
    return cur.rowcount


def mark_stale_running_failed(conn: sqlite3.Connection) -> int:
    """启动时把上次进程残留的 queued/running 标为 failed，避免永久卡住。

    **同时把卡在 `organizing` 的内容放回 `pending`**（跨界面审计 1-1）：
    进程死掉时整理任务里的 `_mark_failed()` 不会执行，只标任务不回收内容，
    那条内容就永远显示「整理中」、`POST /{id}/organize` 一律 409 ITEM_BUSY，
    用户只剩「删了重传」一条路（还要重跑一遍读字）。

    这里用全量回收而不是按失败任务的 `input_json.item_id` 精确回收：这个函数
    只在启动时调一次，而任务队列是进程内的 ThreadPoolExecutor —— 新进程启动时
    不可能有整理在跑，任何 `organizing` 都是残留。精确回收会漏掉「置了状态、
    任务行还没写就崩了」那个窗口。
    """
    cur = conn.execute(
        """UPDATE agent_task
           SET status='failed', error_code='TASK_INTERRUPTED',
               error_msg='服务重启，任务中断', updated_at=?
           WHERE status IN ('queued','running')""",
        (now_iso(),),
    )
    conn.execute(
        """UPDATE knowledge_item SET status='pending', updated_at=?
           WHERE status='organizing'""",
        (now_iso(),),
    )
    return cur.rowcount
