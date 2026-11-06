"""采集入口（T2.3）：`POST /api/ingest/url`。

路由只做三件事：校验 URL、查已有、派任务。抓取不在请求线程里做（M2 §1.2）。
响应形状见接口契约 §3：202 `{task_id, existing_item_id}` / 已存在时 200 `{task_id: null, ...}`。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.db.conn import get_conn
from app.db.repo import items as repo
from app.errors import error_payload
from app.services import tasks as task_queue
from app.services import web_ingest
from app.services.fetch_errors import FetchError
from app.services.fetcher import normalize_url

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

TASK_TYPE = "fetch_url"          # agent_task.type 枚举之一（数据契约 §2）


class UrlBody(BaseModel):
    url: str = Field(min_length=1)
    # force=true：重新抓取并**只覆盖正文**（2026-11-06 裁决，见 repo.replace_raw_content）
    force: bool = False


def _bad_request(exc: FetchError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=error_payload(exc.code, exc.message, exc.detail),
    )


@router.post("/url")
def ingest_url(body: UrlBody):
    try:
        url = normalize_url(body.url)
    except FetchError as exc:
        return _bad_request(exc)

    conn = get_conn()
    try:
        existing = repo.find_by_url(conn, url)
    finally:
        conn.close()

    if existing is not None and not body.force:
        return JSONResponse(
            status_code=200,
            content={"task_id": None, "existing_item_id": existing["id"]},
        )

    task_id = task_queue.submit(
        TASK_TYPE, web_ingest.run, {"url": url, "force": body.force}, pass_task_id=True,
    )
    return JSONResponse(status_code=202, content={"task_id": task_id, "existing_item_id": None})
