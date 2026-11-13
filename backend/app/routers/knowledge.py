"""条目 CRUD + 切块（T1.7）+ 整理触发（T1.8）。所有端点用同步 def（总纲 §7）。"""
from __future__ import annotations

import sqlite3
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db.conn import get_conn
from app.db.repo import files as file_repo
from app.db.repo import items as repo
from app.db.repo import pages as page_repo
from app.db.repo import workspaces as workspace_repo
from app.errors import ApiError, error_payload
from app.services import dispatch
from app.services import embedder
from app.services import files as file_store
from app.services import ingest_file, mindmap, ocr, pdf_pages
from app.services import extractors
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
    # 显式给 null = 移出工作区；不带这个键 = 不改（靠 exclude_unset 区分，见 patch_item）
    workspace_id: int | None = None


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


def _file_shape(conn: sqlite3.Connection, item_id: int) -> dict | None:
    """详情里的原件信息（T9.3）。一份内容可能有多份原件，这里只给主原件。

    绝对路径不出接口：`stored_path` 是数据目录相对路径，前端要字节流走
    `GET /api/knowledge/{id}/file`（T9.10），自己不拼路径。
    """
    rows = file_repo.list_by_item(conn, item_id)
    if not rows:
        return None
    row = next((r for r in rows if r["role"] == "main"), rows[0])
    return {
        "id": row["id"], "original_name": row["original_name"], "ext": row["ext"],
        "mime": row["mime"], "size": row["size"], "page_count": row["page_count"],
        "has_text_layer": row["has_text_layer"], "ocr_status": row["ocr_status"],
    }


def _detail_shape(row: sqlite3.Row, conn: sqlite3.Connection) -> dict:
    item = repo.row_to_item(row)
    item["chunks"] = repo.list_chunks(conn, item["id"])
    # kind / workspace_id 已在 row_to_item 的列里；原件要单独查一次
    item["file"] = _file_shape(conn, item["id"])
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
        payload = {
            "id": row["id"], "title": row["title"], "status": row["status"],
            "chunk_count": chunk_count, "duplicated": duplicated,
        }
    finally:
        conn.close()
    # 提交之后再派任务：补向量要读到已落库的 chunk（M3 §6.2）
    embedder.schedule(row["id"])
    return JSONResponse(status_code=201, content=payload)


@router.get("")
def list_items(
    source_type: str | None = None,
    category: str | None = None,
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    workspace_id: int | Literal["none"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """`workspace_id="none"` = 只看未归类（契约 §3.1：哨兵值不用 0）。

    `int | Literal["none"]` 让 FastAPI 直接 422 掉 `workspace_id=abc`，
    不需要在函数体里再写一次类型判断。
    """
    conn = get_conn()
    try:
        rows, total = repo.list_items(
            conn, source_type=source_type, category=category, status=status,
            q=q, tag=tag, workspace_id=workspace_id, page=page, page_size=page_size,
        )
        return {"items": [_list_shape(r) for r in rows], "total": total}
    finally:
        conn.close()


@router.get("/categories")
def list_categories(category: str | None = None, tag: str | None = None) -> dict:
    """分类 / 标签两级计数 + 状态计数（左侧树与「整理全部」的气泡都用它）。

    `category` / `tag` 只收窄 `counts`，分类树本身仍是全库（树是导航，不该自我截断）。
    左栏选中筛选后，状态行与「开始整理 N 条」都跟着变成当前范围的数量。

    必须注册在 `/{item_id}` 之前，否则 "categories" 会被当成 item_id 解析成 422。
    """
    conn = get_conn()
    try:
        return repo.category_tree(conn, category=category, tag=tag)
    finally:
        conn.close()


def _require_llm_key() -> None:
    """未配置 Key 时立刻失败，不留一个注定失败的任务在队列里（M1 §5 DoD）。"""
    if not get_settings().has_llm_key:
        raise ApiError("LLM_NO_KEY", "还没配模型 Key。在「设置 → 模型」里填一下就能用。", status=400)


@router.post("/organize-pending")
def organize_pending(
    limit: int = Query(default=20, ge=1, le=100),
    category: str | None = None,
    tag: str | None = None,
) -> dict:
    """批量整理 status='pending' 的条目。逐条派发独立任务，返回 item→task 映射。

    `category` / `tag` 与列表筛选同一口径：左栏筛着某分类时，「开始整理 N 条」
    整理的就是这 N 条，不是全库的待整理。
    """
    _require_llm_key()
    conn = get_conn()
    try:
        item_ids = repo.list_ids_by_status(conn, "pending", limit, category=category, tag=tag)
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


@router.get("/{item_id}/mindmap")
def get_mindmap(
    item_id: int,
    theme: str = "paper",
    mode: Literal["light", "dark"] = "light",
):
    """T3.7：现场从 structured_note 生成 SVG（ADR-019 不落库、不缓存）。

    `theme` 传主题 id（paper / notes / chestnut / docs / study / teal），配色按该主题派生；
    也兼容老契约 `theme=light|dark`（直接当明暗处理）。`mode` 只在传主题 id 时生效。

    `no-store` 是刻意的：笔记一改导图必须立刻变，浏览器缓存会直接违背这条 DoD。
    """
    conn = get_conn()
    try:
        row = repo.get_item(conn, item_id)
        if row is None:
            return _not_found()
        svg = mindmap.render_item_svg(
            row["title"], row["structured_note"], repo.loads(row["key_points"]) or [], theme, mode
        )
        return Response(
            content=svg,
            media_type="image/svg+xml; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
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
            # workspace_id 显式给 null 是合法的「移出工作区」，只校验非空值是否存在
            target = fields.get("workspace_id")
            if target is not None and workspace_repo.get(conn, target) is None:
                raise ApiError("WORKSPACE_NOT_FOUND", "工作区不存在，可能已经被删了", status=404)
            row = repo.update_item(conn, item_id, fields)
            if fields.get("structured_note") is not None:
                # 数据契约 §6 / M1 §6.9：删 source='note' 的 chunk 后用同一 chunker 重建
                repo.rebuild_chunks(conn, item_id, fields["structured_note"], "note")
            note_chunk_count = repo.count_chunks(conn, item_id, "note")
        result = {
            "id": row["id"], "updated_at": row["updated_at"],
            "note_edited": row["note_edited"], "note_chunk_count": note_chunk_count,
            "workspace_id": row["workspace_id"],
        }
    finally:
        conn.close()
    if body.structured_note is not None:
        # 笔记改写会重建 note chunk，向量必须跟着补，否则问答引用的还是旧文本
        embedder.schedule(item_id)
    return result


@router.delete("/{item_id}")
def delete_item(item_id: int):
    conn = get_conn()
    try:
        # 页图按 file_id 建目录，删内容前先把 file_id 拿到（级联删完就查不到了）
        file_ids = [int(r["id"]) for r in file_repo.list_by_item(conn, item_id)]
        with conn:
            deleted = repo.delete_item(conn, item_id)
        if not deleted:
            return _not_found()
    finally:
        conn.close()
    # 删内容连带删原件：item_file 行由外键 CASCADE，盘上的目录得自己清（T9.3 / T9.6）
    file_store.purge_item(item_id)
    for file_id in file_ids:
        pdf_pages.purge_file(file_id)
    return {"id": item_id, "deleted": True}


# ── 识别链路（T9.6）──────────────────────────────────────
def _main_file(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    rows = file_repo.list_by_item(conn, item_id)
    if not rows:
        return None
    return next((r for r in rows if r["role"] == "main"), rows[0])


def _file_not_found(message: str) -> JSONResponse:
    return JSONResponse(status_code=404, content=error_payload("FILE_NOT_FOUND", message))


def _ocr_progress(conn: sqlite3.Connection, file: sqlite3.Row) -> dict:
    """进度全部从库里推：`item_page` 有行就是这一页处理完了（空页也算）。

    没有单独一张"识别任务"表 —— 状态只有 `item_file.ocr_status` 加页数，
    这样进程被杀也不会丢进度，重启后天然是「已完成 12/30」。
    """
    rows = page_repo.list_by_file(conn, int(file["id"]))
    total = int(file["page_count"] or 0)
    have = {int(r["page_no"]) for r in rows}
    return {
        "status": file["ocr_status"] or "none",
        "done_pages": len(rows),
        "total_pages": total,
        # 没落库的页就是没识别成功的页（整页失败不写行，见 services/ingest_file.py）
        "failed_pages": [n for n in range(1, total + 1) if n not in have],
    }


@router.get("/{item_id}/ocr")
def get_ocr_progress(item_id: int):
    conn = get_conn()
    try:
        if repo.get_item(conn, item_id) is None:
            return _not_found()
        file = _main_file(conn, item_id)
        if file is None:
            return _not_found()
        return _ocr_progress(conn, file)
    finally:
        conn.close()


class OcrBody(BaseModel):
    # 给了 pages 就只重跑这几页（失败重试 / 认错了再跑一次）；不给就是整份
    pages: list[int] | None = None


@router.post("/{item_id}/ocr")
def start_ocr(item_id: int, body: OcrBody | None = None):
    """202 + task_id。读字是后台任务：上传/重读都不许同步等（契约 §3.1）。

    这个端点的语义是**「把这份原件重新读一遍」**，两条路都接受：
    PDF/图片重新识别（可点名页号），docx/pptx/xlsx/txt 重新抽取（整份，没有页号概念）。
    只回 409 不给路的话，"抽取失败"就没有任何重试入口 —— 用户只能删了重传。
    """
    conn = get_conn()
    try:
        if repo.get_item(conn, item_id) is None:
            return _not_found()
        file = _main_file(conn, item_id)
        if file is None:
            return _file_not_found("这条内容没有原件，没什么可读的")
        ext = str(file["ext"] or "").lower()
        is_ocr = ext in ingest_file.OCR_EXT
        if not is_ocr and extractors.for_ext(ext) is None:
            return JSONResponse(
                status_code=409,
                content=error_payload("OCR_NOT_APPLICABLE",
                                      "这个格式没有可用的读取方式"),
            )
        if is_ocr and ocr.available() == "none":
            return JSONResponse(status_code=409, content=error_payload(**ocr.missing_hint()))
        if (file["ocr_status"] or "") == "running":
            return JSONResponse(
                status_code=409,
                content=error_payload("OCR_RUNNING", "这份文件正在读，等它跑完再试"),
            )

        pages = [n for n in (body.pages or []) if n >= 1] if is_ocr else []
        total = int(file["page_count"] or 0)
        if pages and total and max(pages) > total:
            raise ApiError("OCR_PAGE_OUT_OF_RANGE",
                           f"这份文件只有 {total} 页", status=422)

        # 先落 running 再派任务：中间的毫秒级窗口里第二个请求不该又派一份
        with conn:
            file_repo.set_ocr_status(conn, int(file["id"]), "running")
        task_type = dispatch.TASK_OCR_PAGES if is_ocr else dispatch.TASK_EXTRACT_TEXT
        payload = {"file_id": int(file["id"])}
        if is_ocr:
            payload["pages"] = pages or None
        task_id = dispatch.submit(task_type, payload)
        return JSONResponse(status_code=202, content={"task_id": task_id})
    finally:
        conn.close()


def _page_image_url(item_id: int, page_no: int) -> str:
    return f"/api/knowledge/{item_id}/file?page={page_no}"


@router.get("/{item_id}/pages/{n}")
def get_page(item_id: int, n: int):
    """第 n 页的文字与页图**必须同一次返回**（"认错也看得出来"的保障，数据契约 §6）。"""
    if n < 1:
        raise ApiError("PAGE_NOT_FOUND", "页码从 1 开始", status=404)
    conn = get_conn()
    try:
        if repo.get_item(conn, item_id) is None:
            return _not_found()
        file = _main_file(conn, item_id)
        if file is None:
            return _file_not_found("这条内容没有原件")
        row = page_repo.get(conn, int(file["id"]), n)
        if row is None:
            return JSONResponse(
                status_code=404,
                content=error_payload("PAGE_NOT_FOUND", f"第 {n} 页还没识别出来"),
            )
        return {
            "page_no": n,
            "text": row["text"] or "",
            "source": row["source"],
            "avg_conf": row["avg_conf"],
            # 抽取来的页（docx/pptx/xlsx/txt）没有页图：给 null，别给一个必然 404 的地址
            "image_url": _page_image_url(item_id, n) if row["image_path"] else None,
        }
    finally:
        conn.close()


@router.get("/{item_id}/file")
def get_file(item_id: int, page: int | None = Query(default=None, ge=1)):
    """原件字节流（`inline`）；带 `page` 时返回该页页图。

    页图与原件共用一个端点：前端要的是"能显示的图片地址"，多一个端点只是让
    `pages/{n}` 的 `image_url` 指向一个已登记的路径（T9.6）。
    """
    conn = get_conn()
    try:
        if repo.get_item(conn, item_id) is None:
            return _not_found()
        file = _main_file(conn, item_id)
        if file is None:
            return _file_not_found("这条内容没有原件")
        file_id = int(file["id"])

        if page is None:
            path = file_store.abs_path(str(file["stored_path"] or ""))
            if not path.is_file():
                return _file_not_found("原件在盘上找不到了，重新上传一次")
            name = quote(str(file["original_name"] or path.name))
            return FileResponse(
                path, media_type=file["mime"] or "application/octet-stream",
                headers={"Content-Disposition": f"inline; filename*=UTF-8''{name}"},
            )

        row = page_repo.get(conn, file_id, page)
        if row is None or not row["image_path"]:
            return JSONResponse(
                status_code=404,
                content=error_payload("PAGE_NOT_FOUND", f"第 {page} 页还没有页图"),
            )
        image = pdf_pages.abs_path(str(row["image_path"]))
        if not image.is_file():
            return JSONResponse(
                status_code=404,
                content=error_payload("PAGE_NOT_FOUND", f"第 {page} 页的页图不在了，重新识别一次"),
            )
        return FileResponse(image, media_type="image/jpeg")
    finally:
        conn.close()
