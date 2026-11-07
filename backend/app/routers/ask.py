"""问答端点（T3.5）：`POST /api/ask`，SSE 流式；T3.12 起同时落库问答历史。

三个坑（M3 §6.5）都在这里处理：
1. `async def` 生成器 + `StreamingResponse(media_type="text/event-stream")`
2. 显式加 `Cache-Control: no-cache` / `X-Accel-Buffering: no`；全局没挂 GZip，
   所以无需排除（挂了的话 SSE 会被攒成一次性返回）
3. 检索与 LLM 都是同步阻塞的，一律丢进线程池，否则卡死事件循环

**检索为空时绝不调用 LLM**（M3 §1 约束 4）：直接回固定话术，llm_call_log 不新增记录。
**落库时机**：在 `done` 事件发出之前写 `ask_log`，所以前端收到 done 时，
历史里已经能看到这条记录。客户端中途断开时不会落库（没有 finally 里 await ——
async 生成器被 aclose 时再 await 会抛 `ignored GeneratorExit`）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db.conn import get_conn
from app.db.repo import ask_log as repo
from app.services import retriever
from app.services.agents import asker
from app.services.llm import LLMError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ask"])

NO_RESULT = "知识库中没有找到相关内容"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _persist(**fields) -> None:
    """同步写一条历史；失败只记日志，绝不影响问答本身。"""
    conn = get_conn()
    try:
        with conn:
            repo.save(conn, **fields)
    except Exception as exc:  # 历史存不下不该让用户看不到答案
        log.warning("问答历史落库失败（%s），本次不记录", type(exc).__name__)
    finally:
        conn.close()


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _no_result(question: str, result: dict, started: float) -> StreamingResponse:
    async def gen():
        # 检索为空也记一条：no_result=1，prompt_tokens 为空（确实没调模型）
        await run_in_threadpool(
            _persist, question=question, answer=NO_RESULT,
            match_type=result.get("match_type"), fallback=result.get("fallback"),
            no_result=True, duration_ms=_elapsed_ms(started),
        )
        yield _event({"type": "no_result", "message": NO_RESULT})
        yield _event({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


def _failure(exc: LLMError) -> dict:
    # detail 可能是 "HTTP 429" 这类，不含 Key（llm._safe_detail 已保证）
    return {"type": "error", "code": exc.code, "message": exc.message,
            "detail": getattr(exc, "detail", "")}


@router.post("/ask")
async def ask(body: AskBody) -> StreamingResponse:
    started = time.monotonic()
    question = body.question.strip()
    if not question:
        # 空问题不落库（没有信息量），但仍然回一个合法的 SSE 序列
        async def gen():
            yield _event({"type": "no_result", "message": NO_RESULT})
            yield _event({"type": "done"})

        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    # 阻塞的 SQLite + 可能的向量编码，必须离开事件循环
    result = await run_in_threadpool(retriever.hybrid, question, body.limit)
    items = result["items"]
    if not items:
        log.info("问答检索为空，直接短路（未调用 LLM）：%s", question[:30])
        return _no_result(question, result, started)

    sources_list = asker.sources(items)
    usage: dict = {}

    async def gen():
        yield _event({"type": "sources", "sources": sources_list,
                      "fallback": result["fallback"]})

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker() -> None:
            """同步生成器跑在子线程里，靠 call_soon_threadsafe 送进事件循环。"""
            try:
                for piece in asker.stream(question, sources_list, items, usage):
                    loop.call_soon_threadsafe(queue.put_nowait, ("delta", piece))
            except LLMError as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))
            except Exception as exc:  # 兜底：任何意外都要变成前端可见的错误事件
                log.error("问答流式输出异常：%s", type(exc).__name__)
                loop.call_soon_threadsafe(queue.put_nowait, (
                    "error", LLMError("LLM_HTTP_ERROR", "问答生成失败", type(exc).__name__)))
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

        threading.Thread(target=worker, name="cairn-ask", daemon=True).start()

        parts: list[str] = []
        while True:
            kind, payload = await queue.get()
            if kind == "end":
                await run_in_threadpool(
                    _persist, question=question, answer="".join(parts),
                    sources=sources_list, match_type=result.get("match_type"),
                    fallback=result.get("fallback"),
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    duration_ms=_elapsed_ms(started),
                )
                yield _event({"type": "done", "usage": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                }})
                return
            if kind == "error":
                # 出错也记：answer 只含已流出的部分，error_code 标明不可当完整答案回放
                await run_in_threadpool(
                    _persist, question=question, answer="".join(parts),
                    sources=sources_list, match_type=result.get("match_type"),
                    fallback=result.get("fallback"), error_code=payload.code,
                    duration_ms=_elapsed_ms(started),
                )
                yield _event(_failure(payload))
                yield _event({"type": "done"})
                return
            parts.append(payload)
            yield _event({"type": "delta", "text": payload})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/ask/history")
def history(limit: int = Query(30, ge=1, le=100),
            offset: int = Query(0, ge=0)) -> dict:
    """问答历史列表，时间倒序。列表不带片段正文，点开详情再取。"""
    conn = get_conn()
    try:
        return {
            "items": repo.list_logs(conn, limit=limit, offset=offset),
            "total": repo.count_logs(conn),
        }
    finally:
        conn.close()


@router.get("/ask/history/{log_id}")
def history_detail(log_id: int) -> dict:
    from fastapi import HTTPException

    conn = get_conn()
    try:
        row = repo.get_log(conn, log_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="问答记录不存在")
    return row


@router.delete("/ask/history/{log_id}")
def history_delete(log_id: int) -> dict:
    from fastapi import HTTPException

    conn = get_conn()
    try:
        with conn:
            ok = repo.delete_log(conn, log_id)
    finally:
        conn.close()
    if not ok:
        raise HTTPException(status_code=404, detail="问答记录不存在")
    return {"deleted": log_id}
