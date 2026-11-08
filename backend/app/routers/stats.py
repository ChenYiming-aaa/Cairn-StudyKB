"""统计端点（T5.4）：仪表盘只用这两个。

- `GET /api/stats/today` 今日 6 个数字（口径见 `db/repo/stats.py` 与 M5 §6.6）
- `GET /api/stats/week`  本周 7 天条形图 + 周合计

两个都是纯读取，不起任务、不写库。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.db.conn import get_conn
from app.db.repo import stats as repo

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats/today")
def today() -> dict:
    conn = get_conn()
    try:
        return repo.today(conn)
    finally:
        conn.close()


@router.get("/stats/week")
def week() -> dict:
    conn = get_conn()
    try:
        return repo.week(conn)
    finally:
        conn.close()
