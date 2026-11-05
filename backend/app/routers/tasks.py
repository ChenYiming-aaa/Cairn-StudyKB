"""任务查询端点（接口契约 §2：GET /api/tasks、GET /api/tasks/{id}）。"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.db.conn import get_conn
from app.db.repo import tasks as repo
from app.db.repo.items import loads
from app.errors import error_payload

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
