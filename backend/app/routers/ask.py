"""问答端点（T3.5）：`POST /api/ask`，SSE 流式。

三个坑（M3 §6.5）都在这里处理：
1. `async def` 生成器 + `StreamingResponse(media_type="text/event-stream")`
2. 显式加 `Cache-Control: no-cache` / `X-Accel-Buffering: no`；全局没挂 GZip，
   所以无需排除（挂了的话 SSE 会被攒成一次性返回）
3. 检索与 LLM 都是同步阻塞的，一律丢进线程池，否则卡死事件循环

**检索为空时绝不调用 LLM**（M3 §1 约束 4）：直接回固定话术，llm_call_log 不新增记录。
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


def _no_result() -> StreamingResponse:
    async def gen():
        yield _event({"type": "no_result", "message": NO_RESULT})
        yield _event({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


def _failure(exc: LLMError) -> dict:
    # detail 可能是 "HTTP 429" 这类，不含 Key（llm._safe_detail 已保证）
    return {"type": "error", "code": exc.code, "message": exc.message,
            "detail": getattr(exc, "detail", "")}


@router.post("/ask")
async def ask(body: AskBody) -> StreamingResponse:
    question = body.question.strip()
    if not question:
        return _no_result()

    # 阻塞的 SQLite + 可能的向量编码，必须离开事件循环
    result = await run_in_threadpool(retriever.hybrid, question, body.limit)
    items = result["items"]
    if not items:
        log.info("问答检索为空，直接短路（未调用 LLM）：%s", question[:30])
        return _no_result()

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

        while True:
            kind, payload = await queue.get()
            if kind == "end":
                yield _event({"type": "done", "usage": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                }})
                return
            if kind == "error":
                yield _event(_failure(payload))
                yield _event({"type": "done"})
                return
            yield _event({"type": "delta", "text": payload})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)
