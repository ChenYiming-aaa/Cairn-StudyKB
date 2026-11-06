"""采集入口（T2.3 网页 / T2.7 视频）。

路由只做三件事：校验 URL、查已有、派任务。抓取与转录都不在请求线程里做（M2 §1.2）。
响应形状见接口契约 §3：202 `{task_id, existing_item_id}` / 已存在时 200 `{task_id: null, ...}`。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.db.conn import get_conn
from app.db.repo import items as repo
from app.errors import error_payload
from app.services import dispatch
from app.services.fetch_errors import FetchError
from app.services.fetcher import normalize_url
from app.services.transcriber import DEFAULT_LANGUAGE, DEFAULT_MODEL, MODEL_CHOICES

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class UrlBody(BaseModel):
    url: str = Field(min_length=1)
    # force=true：重新抓取并**只覆盖正文**（2026-11-06 裁决，见 repo.replace_raw_content）
    force: bool = False


class VideoBody(BaseModel):
    """三项都可省：model 默认 small、language 默认 zh（契约 §3 只列了形状）。"""

    url: str = Field(min_length=1)
    model: str = DEFAULT_MODEL
    language: str = DEFAULT_LANGUAGE
    force: bool = False


def _bad_request(exc: FetchError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=error_payload(exc.code, exc.message, exc.detail),
    )


def _existing_or_null(url: str, force: bool) -> JSONResponse | None:
    """同 URL 已入库且不是 force → 直接告诉前端已有条目，不派任务、不消耗一次下载。"""
    conn = get_conn()
    try:
        existing = repo.find_by_url(conn, url)
    finally:
        conn.close()
    if existing is not None and not force:
        return JSONResponse(
            status_code=200,
            content={"task_id": None, "existing_item_id": existing["id"]},
        )
    return None


@router.post("/url")
def ingest_url(body: UrlBody):
    try:
        url = normalize_url(body.url)
    except FetchError as exc:
        return _bad_request(exc)

    if (hit := _existing_or_null(url, body.force)) is not None:
        return hit

    task_id = dispatch.submit(
        dispatch.TASK_FETCH_URL, {"url": url, "force": body.force}
    )
    return JSONResponse(status_code=202, content={"task_id": task_id, "existing_item_id": None})


@router.post("/video")
def ingest_video(body: VideoBody):
    try:
        url = normalize_url(body.url)
    except FetchError as exc:
        return _bad_request(exc)

    model = body.model if body.model in MODEL_CHOICES else DEFAULT_MODEL
    if (hit := _existing_or_null(url, body.force)) is not None:
        return hit

    task_id = dispatch.submit(
        dispatch.TASK_TRANSCRIBE_VIDEO,
        {"url": url, "model": model, "language": body.language or DEFAULT_LANGUAGE,
         "force": body.force},
    )
    return JSONResponse(status_code=202, content={"task_id": task_id, "existing_item_id": None})
