"""条目 CRUD + 切块（T1.7）。所有端点用同步 def（总纲 §7）。"""
from __future__ import annotations

import sqlite3
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.db.conn import get_conn
from app.db.repo import items as repo
from app.errors import error_payload

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class CreateBody(BaseModel):
    title: str | None = None
    raw_content: str = Field(min_length=1)
    source_type: Literal["text", "web", "video", "file"] = "text"


class PatchBody(BaseModel):
    title: str | None = None
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
    title = body.title or first_line[:120] or "未命名条目"
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    conn = get_conn()
    try:
        rows, total = repo.list_items(
            conn, source_type=source_type, category=category, status=status,
            q=q, page=page, page_size=page_size,
        )
        return {"items": [_list_shape(r) for r in rows], "total": total}
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
