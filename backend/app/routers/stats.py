"""统计端点（T5.4）：仪表盘与知识库顶部「今日」条只用这一个。

- `GET /api/stats/today` 今日若干数字（口径见 `db/repo/stats.py` 与 M5 §6.6）
- `GET /api/stats/heatmap` 逐日学习强度（贡献热力图；一格 = 作答次数 + 整理篇数）
- `GET /api/stats/mastery/{item_id}` 一条内容的掌握度（按题算，不按次数算）
- ~~`GET /api/stats/week`~~ 已于 2026-11-17 随番茄钟下线

纯读取，不起任务、不写库。三个端点共用 `repo/stats.py` 里同一份口径，
前端不做二次统计 —— 否则页面与 SQL 迟早对不上。
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.db.conn import get_conn
from app.db.repo import stats as repo
from app.errors import error_payload

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/today")
def today() -> dict:
    conn = get_conn()
    try:
        return repo.today(conn)
    finally:
        conn.close()


@router.get("/stats/heatmap")
def heatmap(
    days: int = Query(
        default=repo.HEATMAP_DAYS, ge=repo.HEATMAP_MIN_DAYS, le=repo.HEATMAP_MAX_DAYS
    ),
) -> dict:
    """连续日期的逐日强度，含 0 格；前端只排版，不补日期也不改口径。"""
    conn = get_conn()
    try:
        return repo.heatmap(conn, days=days)
    finally:
        conn.close()


@router.get("/stats/mastery/{item_id}")
def mastery(item_id: int):
    conn = get_conn()
    try:
        data = repo.mastery(conn, item_id)
        if data is None:
            return JSONResponse(
                status_code=404, content=error_payload("ITEM_NOT_FOUND", "条目不存在")
            )
        return data
    finally:
        conn.close()
