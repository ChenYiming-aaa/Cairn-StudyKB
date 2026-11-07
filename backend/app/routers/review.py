"""复习队列端点（T4.6 / T4.7）。

- `GET  /api/review/due`            今日待复习（`due_at <= now`，UTC 存储、Python 侧比较）
- `POST /api/review/{question_id}/result`  单独上报一次复习结果并推进间隔

平时不需要手动调 `/result`：`POST /api/quiz/submit` 判完分就已经写/推进了 review_item。
这个端点存在的理由是「待人工判断」——简答批改失败时 `is_correct IS NULL`，后端**不排期**
（不猜对错），等用户自己看过之后在这里上报一次真实结果。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.db.conn import get_conn
from app.db.repo import questions as questions_repo
from app.db.repo import review as repo
from app.errors import ApiError

router = APIRouter(prefix="/api", tags=["review"])


class ResultBody(BaseModel):
    correct: bool


def _question_fields(question: dict) -> dict:
    """列表里只给作答/展示需要的字段，别把 fingerprint、payload 原文漏出去。"""
    return {
        key: question.get(key)
        for key in ("question_id", "type", "question", "options", "answer", "explanation",
                    "difficulty", "source_item_id", "source_title")
    }


@router.get("/review/due")
def due(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    conn = get_conn()
    try:
        items, total = repo.due(conn, limit=limit)
        return {
            "items": [{
                **_question_fields(item),
                "review_id": item.get("review_id"),
                "due_at": item.get("due_at"),
                "due_local": item.get("due_local"),
                "interval_days": item.get("interval_days"),
                "lapses": item.get("lapses"),
                "last_result": item.get("last_result"),
                "overdue_days": item.get("overdue_days"),
            } for item in items],
            "total": total,
            "tracked": repo.tracked_total(conn),
            "wrong": repo.wrong_total(conn),
            "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    finally:
        conn.close()


@router.post("/review/{question_id}/result")
def report(question_id: int, body: ResultBody) -> dict:
    conn = get_conn()
    try:
        if questions_repo.get_question(conn, question_id) is None:
            raise ApiError("QUESTION_NOT_FOUND", f"题目 {question_id} 不存在", status=404)
        with conn:
            scheduled = repo.apply(conn, question_id, body.correct)
        if scheduled is None:
            # 答对了、而且这题从没答错过：本来就不需要复习，不建队列行，也不是错误
            return {"question_id": question_id, "scheduled": False,
                    "due_at": None, "reason": "not_tracked"}
        return {"scheduled": True, **scheduled}
    finally:
        conn.close()
