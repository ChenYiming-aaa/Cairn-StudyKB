"""统计端点（T5.4）：仪表盘与知识库顶部「今日」条只用这一个。

- `GET /api/stats/today` 今日若干数字（口径见 `db/repo/stats.py` 与 M5 §6.6）

纯读取，不起任务、不写库。

2026-11-17 番茄钟下线后 `GET /api/stats/week` 一并移除：它只服务仪表盘那张
「本周专注」条形图，没有别的消费者（周合计随计时器一起没有意义了）。
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
