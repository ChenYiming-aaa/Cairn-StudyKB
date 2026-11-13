"""工作区 CRUD（T9.9）。用户自建的一层归类，**不嵌套**（ADR-032）。

四件事：
- 名字 ≤20 字（与标题同一口径），**同名允许** —— 用户叫两个「英语」不算错，
  强行去重会让人为了建第二个不得不改名（契约 §3.1 一行）。
- 列表带每条的 `item_count`，左栏数字直接用它，前端不自己数。
- 删工作区**不删内容**：外键 `ON DELETE SET NULL` 让内容回落到「未归类」。
- `none_count` = 没有工作区的内容数。左栏「未归类」那个固定项要显示数字，
  而它不在 `workspace` 表里（哨兵值 `"none"`，见 `repo/items.py`）。
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.db.conn import get_conn
from app.db.repo import workspaces as repo
from app.errors import error_payload

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

NAME_MAX = 20


class CreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    color: str | None = None
    sort_order: int = 0


class PatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    color: str | None = None
    sort_order: int | None = None


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=error_payload("WORKSPACE_NOT_FOUND", "工作区不存在，可能已经被删了"),
    )


def _count(conn: sqlite3.Connection, workspace_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM knowledge_item WHERE workspace_id=?", (workspace_id,)
    ).fetchone()[0]


def _shape(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """建/改的响应也带 `item_count`：前端拿它直接更新左栏，不必重拉整份列表。"""
    return {
        "id": row["id"], "name": row["name"], "color": row["color"],
        "sort_order": row["sort_order"], "item_count": _count(conn, int(row["id"])),
    }


@router.post("")
def create_workspace(body: CreateBody) -> JSONResponse:
    conn = get_conn()
    try:
        with conn:
            new_id = repo.create(
                conn, name=body.name.strip() or body.name,
                color=body.color, sort_order=body.sort_order,
            )
        row = repo.get(conn, new_id)
        return JSONResponse(status_code=201, content=_shape(conn, row))
    finally:
        conn.close()


@router.get("")
def list_workspaces() -> dict:
    conn = get_conn()
    try:
        rows = repo.list_workspaces(conn)
        none_count = conn.execute(
            "SELECT COUNT(*) FROM knowledge_item WHERE workspace_id IS NULL"
        ).fetchone()[0]
        items = [
            {"id": r["id"], "name": r["name"], "color": r["color"],
             "sort_order": r["sort_order"], "item_count": r["item_count"]}
            for r in rows
        ]
        return {"items": items, "total": len(items), "none_count": none_count}
    finally:
        conn.close()


@router.patch("/{workspace_id}")
def patch_workspace(workspace_id: int, body: PatchBody):
    conn = get_conn()
    try:
        with conn:
            if repo.get(conn, workspace_id) is None:
                return _not_found()
            row = repo.update(conn, workspace_id, body.model_dump(exclude_unset=True))
        return _shape(conn, row)
    finally:
        conn.close()


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: int):
    """内容跟着回到「未归类」，一条都不删（契约 §3.1 与数据契约 §3 的 SET NULL）。"""
    conn = get_conn()
    try:
        with conn:
            if not repo.delete(conn, workspace_id):
                return _not_found()
        return {"freed": False}
    finally:
        conn.close()
