"""出题与判分端点（T4.2 / T4.4）。

`POST /api/quiz/generate` 是 SSE：**一次 LLM 调用**，边收边用增量括号扫描抽题，
每完成一题立刻推给前端（M4 §6.2）。三种坑的处理与 `ask.py` 完全一致：
`async def` 生成器 + 显式 no-cache 头 + 同步阻塞工作丢子线程，靠
`call_soon_threadsafe` 把结果送回事件循环。

单题解析失败 → `skip` 事件继续跑，绝不让整条流崩（M4 §1 约束 2）。
数量不足 → 逐题补生成（M4 §7），最多补 `count` 次，补不出来就如实报 `count`。

`POST /api/quiz/submit` 批量判分：客观题在这里比对，简答走 grader；
简答失败落 NULL（待人工判断），**绝不默认判错**。写 `review_item` 是 T4.6，本轮刻意不做。
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Any

from app.db.conn import get_conn
from app.db.repo import questions as repo
from app.errors import ApiError
from app.services import llm
from app.services.agents import grader, quizzer

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["quiz"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
PAYLOAD_KEYS = ("question", "options", "answer", "explanation")


class GenerateBody(BaseModel):
    item_id: int
    types: list[str] = Field(default_factory=lambda: ["single"], max_length=4)
    difficulty: str = "understand"
    count: int = Field(default=5, ge=1, le=20)   # M4 §1 约束 5：一次最多 20 题


class AnswerIn(BaseModel):
    question_id: int
    user_answer: Any = None
    duration_ms: int | None = None


class SubmitBody(BaseModel):
    answers: list[AnswerIn] = Field(min_length=1, max_length=50)


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _prepare(item_id: int) -> tuple[str, str]:
    conn = get_conn()
    try:
        return quizzer.material_for_item(conn, item_id)
    finally:
        conn.close()


class _Run:
    """一次出题请求的可变状态。只有工作线程写，事件循环只读计数。"""

    def __init__(self, *, item_id: int, title: str, material: str,
                 types: list[str], difficulty: str, count: int):
        self.item_id = item_id
        self.title = title
        self.material = material
        self.types = types
        self.difficulty = difficulty
        self.count = count
        self.ok = 0
        self.skipped = 0
        self.index = 0
        self.stems: list[str] = []
        self.ids: set[int] = set()

    def consume(self, raw: str) -> tuple[dict | None, str]:
        """单个对象字符串 → 入库并返回前端题面；返回 None 表示这题无效。"""
        try:
            obj = json.loads(raw)
        except ValueError:
            return None, "json_parse_failed"
        if not isinstance(obj, dict):
            return None, "not_object"

        data, reason = quizzer.normalize(obj, difficulty=self.difficulty)
        if data is None:
            return None, reason

        fp = repo.fingerprint(self.item_id, data["type"], data["question"])
        payload = {key: data[key] for key in PAYLOAD_KEYS}
        conn = get_conn()
        try:
            with conn:
                qid, created = repo.upsert_question(
                    conn, item_id=self.item_id, qtype=data["type"],
                    difficulty=data["difficulty"], payload=payload, fp=fp,
                )
        except Exception as exc:  # 落库失败只跳这一题，其余照常
            log.error("题目入库失败（%s），跳过该题", type(exc).__name__)
            return None, "store_failed"
        finally:
            conn.close()

        if not created and qid in self.ids:
            # 补生成时模型容易重复出同一题；撞了指纹就不算新题，否则数量会虚高
            return None, "duplicate"

        self.ids.add(qid)
        self.stems.append(data["question"])
        return {
            "id": qid,
            "type": data["type"],
            "question": data["question"],
            "options": data["options"],
            "answer": data["answer"],
            "explanation": data["explanation"],
            "difficulty": data["difficulty"],
            "source_item_id": self.item_id,
            "source_title": self.title,
            "duplicate": not created,   # 撞已有指纹：复用了旧题，不是新生成的
        }, ""


def _emit(run: _Run, raw: str, queue: asyncio.Queue, loop) -> None:
    data, reason = run.consume(raw)
    if data is None:
        run.skipped += 1
        event = {"type": "skip", "index": run.index, "reason": reason}
    else:
        run.ok += 1
        event = {"type": "question", "index": run.index, "question": data}
    run.index += 1
    loop.call_soon_threadsafe(queue.put_nowait, ("event", event))


def _stream_pass(run: _Run, *, count: int, exclude: list[str],
                 queue: asyncio.Queue, loop) -> None:
    """一次 LLM 流式调用：抽一题推一题。`count=1` 用于补生成。"""
    messages = quizzer.messages_for(
        title=run.title, material=run.material, types=run.types,
        difficulty=run.difficulty, count=count, exclude=exclude,
    )
    before = run.ok
    scanner = quizzer.Scanner()
    for piece in quizzer.stream(messages):
        for raw in scanner.feed(piece):
            _emit(run, raw, queue, loop)
            if count == 1 and run.ok > before:
                return
    if run.ok > before:
        return
    if "{" in scanner.leftover():
        # 末尾被截断的对象：解析失败按 skip 报，不再尝试猜测修复（M4 §6.2）
        run.skipped += 1
        loop.call_soon_threadsafe(queue.put_nowait, (
            "event", {"type": "skip", "index": run.index, "reason": "json_parse_failed"}))
        run.index += 1


def _worker(run: _Run, queue: asyncio.Queue, loop) -> None:
    try:
        _stream_pass(run, count=run.count, exclude=[], queue=queue, loop=loop)
        attempts = 0
        while run.ok < run.count and attempts < run.count:
            attempts += 1
            before = run.ok
            _stream_pass(run, count=1, exclude=list(run.stems), queue=queue, loop=loop)
            if run.ok == before:
                break  # 补不出来就别再烧调用
        loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
    except llm.LLMError as exc:
        loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
        loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
    except Exception as exc:  # 兜底：任何意外都要变成前端可见的错误事件（红线 8）
        log.error("出题流式输出异常：%s", type(exc).__name__)
        loop.call_soon_threadsafe(queue.put_nowait, (
            "error", llm.LLMError("QUIZ_FAILED", "出题失败", type(exc).__name__)))
        loop.call_soon_threadsafe(queue.put_nowait, ("done", None))


@router.post("/quiz/generate")
async def generate(body: GenerateBody) -> StreamingResponse:
    types = [t for t in body.types if t in quizzer.TYPES]
    if not types:
        raise ApiError("QUIZ_BAD_TYPES", "题型不合法",
                       f"types 只能取 {'/'.join(quizzer.TYPES)}", status=422)
    if body.difficulty not in quizzer.DIFFICULTIES:
        raise ApiError("QUIZ_BAD_DIFFICULTY", "难度不合法",
                       f"difficulty 只能取 {'/'.join(quizzer.DIFFICULTIES)}", status=422)

    try:
        title, material = await run_in_threadpool(_prepare, body.item_id)
    except quizzer.QuizError as exc:
        raise ApiError(exc.code, exc.message, exc.detail, exc.status) from None

    run = _Run(item_id=body.item_id, title=title, material=material,
               types=types, difficulty=body.difficulty, count=body.count)

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        threading.Thread(target=_worker, args=(run, queue, loop),
                         name="cairn-quiz", daemon=True).start()
        while True:
            kind, payload = await queue.get()
            if kind == "event":
                yield _event(payload)
                continue
            if kind == "error":
                yield _event({"type": "error", "code": payload.code,
                              "message": payload.message,
                              "detail": getattr(payload, "detail", "")})
                continue
            # done：count = 实际入库题数，requested = 用户要的题数（M4 §7）
            yield _event({"type": "done", "count": run.ok,
                          "skipped": run.skipped, "requested": body.count})
            return

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


def _grading_material(conn, item_id: int | None, cache: dict) -> str:
    """简答批改只需要能核对要点的材料节选；同一题组内复用，不重复查库。"""
    if item_id is None:
        return ""
    if item_id not in cache:
        try:
            cache[item_id] = quizzer.material_for_item(
                conn, item_id, limit=grader.GRADER_MATERIAL)[1]
        except quizzer.QuizError:
            cache[item_id] = ""
    return cache[item_id]


@router.post("/quiz/submit")
def submit(body: SubmitBody) -> dict:
    results: list[dict] = []
    cache: dict = {}
    conn = get_conn()
    try:
        for answer in body.answers:
            question = repo.get_question(conn, answer.question_id)
            if question is None:
                raise ApiError("QUESTION_NOT_FOUND",
                               f"题目 {answer.question_id} 不存在", status=404)
            material = (_grading_material(conn, question.get("item_id"), cache)
                        if question.get("type") == "short" else "")
            is_correct, feedback = grader.grade(question, answer.user_answer, material)
            with conn:
                repo.save_attempt(
                    conn, question_id=answer.question_id,
                    user_answer=answer.user_answer, is_correct=is_correct,
                    feedback=feedback, duration_ms=answer.duration_ms,
                )
            results.append({
                "question_id": answer.question_id,
                "is_correct": None if is_correct is None else bool(is_correct),
                "correct_answer": question.get("answer"),
                "explanation": question.get("explanation") or "",
                "feedback": feedback,
            })
    finally:
        conn.close()

    correct = sum(1 for r in results if r["is_correct"] is True)
    total = len(results)
    return {
        "items": results,
        "correct_count": correct,
        "total": total,
        "accuracy": round(correct / total, 2) if total else 0.0,
    }
