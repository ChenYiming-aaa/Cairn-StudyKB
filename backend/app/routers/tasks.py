"""任务查询与重试端点（接口契约 §2：GET /api/tasks、GET /api/tasks/{id}、POST /api/tasks/{id}/retry）。"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.db.conn import get_conn
from app.db.repo import tasks as repo
from app.db.repo.items import loads
from app.errors import error_payload
from app.services import dispatch

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _shape(row: sqlite3.Row) -> dict:
    task = dict(row)
    task["output_json"] = loads(task.get("output_json"))
    task["input_json"] = loads(task.get("input_json"))
    return task


@router.get("")
def list_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
) -> dict:
    conn = get_conn()
    try:
        rows = repo.list_tasks(conn, limit=limit, status=status)
        return {"items": [_shape(r) for r in rows],
                "total": repo.count_tasks(conn, status=status)}
    finally:
        conn.close()


@router.get("/{task_id}")
def get_task(task_id: str):
    conn = get_conn()
    try:
        row = repo.get_task(conn, task_id)
        if row is None:
            return JSONResponse(
                status_code=404, content=error_payload("TASK_NOT_FOUND", "任务不存在")
            )
        return _shape(row)
    finally:
        conn.close()


@router.post("/{task_id}/retry")
def retry_task(task_id: str):
    """重新派发一个 failed 任务（接口契约 §2）。

    新建一条任务而不是复用原 id：`agent_task` 是一次执行一条记录，
    覆盖原行会丢掉失败现场（error_code / 已经跑过的进度），排障就没依据了。
    """
    try:
        new_id = dispatch.retry(task_id)
    except dispatch.NotRetryable as exc:
        return JSONResponse(
            status_code=409,
            content=error_payload("TASK_NOT_RETRYABLE",
                                  f"任务当前状态为 {exc.status}，只有失败的任务可以重试"),
        )
    except KeyError:
        return JSONResponse(
            status_code=400,
            content=error_payload("TASK_TYPE_UNSUPPORTED", "该类型的任务不支持重试"),
        )
    if new_id is None:
        return JSONResponse(
            status_code=404, content=error_payload("TASK_NOT_FOUND", "任务不存在")
        )
    return JSONResponse(status_code=202, content={"task_id": new_id})
