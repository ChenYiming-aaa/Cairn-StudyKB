"""条目 CRUD + 切块（T1.7）+ 整理触发（T1.8）。所有端点用同步 def（总纲 §7）。"""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db.conn import get_conn
from app.db.repo import items as repo
from app.errors import ApiError, error_payload
from app.services import tasks as task_queue
from app.services.agents import organizer

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class CreateBody(BaseModel):
    title: str | None = None
    raw_content: str = Field(min_length=1)
    source_type: Literal["text", "web", "video", "file"] = "text"


class PatchBody(BaseModel):
    # 标题上限 20 字（2026-11-06 裁决）：AI 生成与手改同一口径，超长直接 422
    title: str | None = Field(default=None, min_length=1, max_length=20)
    category: str | None = None
    tags: list[str] | None = None
    structured_note: str | None = None


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content=error_payload("ITEM_NOT_FOUND", "条目不存在"))


def _list_shape(row: sqlite3.Row) -> dict:
    item = repo.row_to_item(row)
    return {
        "id": item["id"], "title": item["title"],
        "source_type": item["source_type"], "category": item["category"],
        "tags": item["tags"], "status": item["status"],
        "created_at": item["created_at"],
    }


def _detail_shape(row: sqlite3.Row, conn: sqlite3.Connection) -> dict:
    item = repo.row_to_item(row)
    item["chunks"] = repo.list_chunks(conn, item["id"])
    return item


@router.post("")
def create_item(body: CreateBody) -> JSONResponse:
    first_line = (body.raw_content.strip().splitlines() or ["未命名条目"])[0]
    # 占位标题只用于整理前列表可读；整理后会被 AI 生成的标题覆盖（≤20 字）
    title = (body.title or first_line[:40]).strip() or "未命名条目"
    conn = get_conn()
    try:
        with conn:
            row, duplicated = repo.create_item(
                conn, title=title, raw_content=body.raw_content,
                source_type=body.source_type,
            )
            if duplicated:
                chunk_count = repo.count_chunks(conn, row["id"])
            else:
                chunk_count = repo.rebuild_chunks(conn, row["id"], body.raw_content, "raw")
        return JSONResponse(status_code=201, content={
            "id": row["id"], "title": row["title"], "status": row["status"],
            "chunk_count": chunk_count, "duplicated": duplicated,
        })
    finally:
        conn.close()


@router.get("")
def list_items(
    source_type: str | None = None,
    category: str | None = None,
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    conn = get_conn()
    try:
        rows, total = repo.list_items(
            conn, source_type=source_type, category=category, status=status,
            q=q, tag=tag, page=page, page_size=page_size,
        )
        return {"items": [_list_shape(r) for r in rows], "total": total}
    finally:
        conn.close()


@router.get("/categories")
def list_categories() -> dict:
    """分类 / 标签两级计数 + 状态计数（左侧树与「整理全部」的气泡都用它）。

    必须注册在 `/{item_id}` 之前，否则 "categories" 会被当成 item_id 解析成 422。
    """
    conn = get_conn()
    try:
        return repo.category_tree(conn)
    finally:
        conn.close()


def _require_llm_key() -> None:
    """未配置 Key 时立刻失败，不留一个注定失败的任务在队列里（M1 §5 DoD）。"""
    if not get_settings().has_llm_key:
        raise ApiError("LLM_NO_KEY", "未配置 LLM API Key，请在 .env 中设置 LLM_API_KEY", status=400)


@router.post("/organize-pending")
def organize_pending(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """批量整理 status='pending' 的条目。逐条派发独立任务，返回 item→task 映射。"""
    _require_llm_key()
    conn = get_conn()
    try:
        item_ids = repo.list_ids_by_status(conn, "pending", limit)
        queued: list[dict] = []
        for item_id in item_ids:
            with conn:
                repo.set_status(conn, item_id, "organizing")
            queued.append({
                "item_id": item_id,
                "task_id": task_queue.submit("organize", organizer.run, {"item_id": item_id}),
            })
        return {"items": queued, "total": len(queued)}
    finally:
        conn.close()


@router.post("/{item_id}/organize")
def organize_item(item_id: int):
    """触发整理，返回 task_id（202）；同一时刻只允许一个整理任务在同一条目上跑。"""
    _require_llm_key()
    conn = get_conn()
    try:
        row = repo.get_item(conn, item_id)
        if row is None:
            return _not_found()
        if row["status"] == "organizing":
            return JSONResponse(
                status_code=409,
                content=error_payload("ITEM_BUSY", "该条目正在整理中，请等待完成"),
            )
        with conn:
            repo.set_status(conn, item_id, "organizing")
        task_id = task_queue.submit("organize", organizer.run, {"item_id": item_id})
        return JSONResponse(status_code=202, content={"task_id": task_id})
    finally:
        conn.close()


@router.get("/{item_id}")
def get_item(item_id: int):
    conn = get_conn()
    try:
        row = repo.get_item(conn, item_id)
        if row is None:
            return _not_found()
        return _detail_shape(row, conn)
    finally:
        conn.close()


@router.patch("/{item_id}")
def patch_item(item_id: int, body: PatchBody):
    conn = get_conn()
    try:
        with conn:
            if repo.get_item(conn, item_id) is None:
                return _not_found()
            fields = body.model_dump(exclude_unset=True)
            row = repo.update_item(conn, item_id, fields)
            if fields.get("structured_note") is not None:
                # 数据契约 §6 / M1 §6.9：删 source='note' 的 chunk 后用同一 chunker 重建
                repo.rebuild_chunks(conn, item_id, fields["structured_note"], "note")
            note_chunk_count = repo.count_chunks(conn, item_id, "note")
        return {
            "id": row["id"], "updated_at": row["updated_at"],
            "note_edited": row["note_edited"], "note_chunk_count": note_chunk_count,
        }
    finally:
        conn.close()


@router.delete("/{item_id}")
def delete_item(item_id: int):
    conn = get_conn()
    try:
        with conn:
            deleted = repo.delete_item(conn, item_id)
        if not deleted:
            return _not_found()
        return {"id": item_id, "deleted": True}
    finally:
        conn.close()
