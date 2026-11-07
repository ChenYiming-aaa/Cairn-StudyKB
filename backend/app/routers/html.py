"""T3.9 学习页接口：生成 / 列表 / 预览 / 下载。

生成是**同步**的：一次渲染几十毫秒（纯模板 + 手写 SVG），没有必要走任务队列，
走了反而要前端轮询才能看到结果。真正耗时的是整理（调模型），那是 M1 的事。
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.db.conn import get_conn
from app.db.repo import artifacts as repo
from app.db.repo import items as item_repo
from app.errors import ApiError, error_payload
from app.services import renderer

router = APIRouter(prefix="/api/html", tags=["html"])

MAX_ITEMS = 20


class GenerateBody(BaseModel):
    item_ids: list[int] = Field(min_length=1, max_length=MAX_ITEMS)
    # 标题上限 40 字：比条目标题（20）宽松，它是整份专题的名字
    title: str | None = Field(default=None, max_length=40)


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404, content=error_payload("HTML_NOT_FOUND", "学习页不存在或已删除")
    )


@router.post("/generate")
def generate(body: GenerateBody):
    # 去重但保序：前端多选偶尔会重复提交同一个 id
    ids = list(dict.fromkeys(body.item_ids))
    conn = get_conn()
    try:
        rows = [item_repo.get_item(conn, item_id) for item_id in ids]
        missing = [i for i, row in zip(ids, rows) if row is None]
        if missing:
            raise ApiError(
                "ITEM_NOT_FOUND", "部分条目不存在，可能已被删除",
                detail=", ".join(str(i) for i in missing), status=404,
            )
        items = [item_repo.row_to_item(row) for row in rows]
        default_title = (
            items[0]["title"] if len(items) == 1 else f"{items[0]['title']} 等 {len(items)} 篇"
        )
        title = (body.title or "").strip() or default_title
        page = renderer.render_page(title, items)
        size = renderer.size_bytes(page)
        with conn:
            artifact_id = repo.create(
                conn, title=title, item_ids=ids, html_content=page
            )
        return JSONResponse(
            status_code=201,
            content={"id": artifact_id, "title": title, "size_bytes": size},
        )
    finally:
        conn.close()


@router.get("")
def list_pages(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    conn = get_conn()
    try:
        items, total = repo.list_artifacts(conn, limit=limit, offset=offset)
        return {"items": items, "total": total}
    finally:
        conn.close()


@router.get("/{artifact_id}")
def preview(artifact_id: int):
    """返回 HTML 文本给 iframe 预览。

    CSP 收紧到「只允许内联样式」：产物本来就是自包含的，任何外部请求都说明出了 bug，
    与其靠人工检查不如让浏览器直接拒掉。
    """
    conn = get_conn()
    try:
        row = repo.get(conn, artifact_id)
        if row is None:
            return _not_found()
        return HTMLResponse(
            content=row["html_content"],
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            },
        )
    finally:
        conn.close()


@router.get("/{artifact_id}/download")
def download(artifact_id: int):
    conn = get_conn()
    try:
        row = repo.get(conn, artifact_id)
        if row is None:
            return _not_found()
        title, content = row["title"], row["html_content"]
    finally:
        conn.close()
    # 中文文件名必须 URL 编码（M3 §6.8），另给一个纯 ASCII 的 fallback
    filename = quote(f"{title}.html")
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition":
                f"attachment; filename=\"cairn-page-{artifact_id}.html\"; filename*=UTF-8''{filename}",
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{artifact_id}")
def delete_page(artifact_id: int):
    conn = get_conn()
    try:
        with conn:
            deleted = repo.delete(conn, artifact_id)
        if not deleted:
            return _not_found()
        return {"id": artifact_id, "deleted": True}
    finally:
        conn.close()
