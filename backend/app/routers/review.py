"""复习队列端点（T4.6 / T4.7）。

- `GET  /api/review/due`            今日待复习（`due_at <= now`，UTC 存储、Python 侧比较）
- `GET  /api/review/pending`        待人工判断（最近一次作答 `is_correct IS NULL`）
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
            # 待人工判断的题数：顺手带上，复习页不用再发一个请求才知道要不要显示入口
            "pending": repo.pending_total(conn),
            "tracked": repo.tracked_total(conn),
            "wrong": repo.wrong_total(conn),
            "now": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    finally:
        conn.close()


@router.get("/review/pending")
def pending(limit: int = Query(default=20, ge=1, le=100),
            offset: int = Query(default=0, ge=0)) -> dict:
    """待人工判断的题：批改失败时留在 `quiz_attempt` 里的 `is_correct IS NULL`。

    离开交卷结果页之后，这是唯一能再找到它们的地方（它们既不进复习队列也不进错题本）。
    """
    conn = get_conn()
    try:
        items, total = repo.pending(conn, limit=limit, offset=offset)
        return {
            "items": [{**_question_fields(item), "last_pending_at": item.get("last_pending_at")}
                      for item in items],
            "total": total,
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
            # 人工裁定也要落到作答记录里。**不能省**：`/review/pending` 认的是
            # 「最近一次作答是不是 NULL」，只写 review_item 的话那条 NULL 还在，
            # 判完照样被捞回来（2026-11-15 实测踩到，verify_m4 那条断言就是它抓出来的）。
            # 沿用上一次的作答内容，不编一个空答案。
            last = questions_repo.attempts_of(conn, question_id, limit=1)
            questions_repo.save_attempt(
                conn,
                question_id=question_id,
                user_answer=last[0]["user_answer"] if last else None,
                is_correct=1 if body.correct else 0,
                feedback="人工裁定",
            )
            scheduled = repo.apply(conn, question_id, body.correct)
        if scheduled is None:
            # 答对了、而且这题从没答错过：本来就不需要复习，不建队列行，也不是错误
            return {"question_id": question_id, "scheduled": False,
                    "due_at": None, "reason": "not_tracked"}
        return {"scheduled": True, **scheduled}
    finally:
        conn.close()
