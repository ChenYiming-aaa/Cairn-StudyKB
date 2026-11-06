"""问答 Agent（T3.5）：检索到的片段 → 带编号引用的流式回答。

约束（M3 §1 约束 4、§3 验收 B）：
- **检索为空时本模块根本不会被调用**；路由层就短路，LLM 不得被触发（防编造）
- 引用编号 `[n]` 必须能对上 sources 里的 `n`，所以编号由这里统一分配，
  不交给模型自己数
- prompt 放 `prompts/ask.md`，代码只引用文件名（总纲 §7）
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator

from app.services import llm

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
MAX_CONTEXT_CHARS = 9000     # 8 段 ×900 字 ≈ 7200，留一点余量

_CITATION = re.compile(r"\[(\d+)\]")


def sources(items: list[dict]) -> list[dict]:
    """把检索结果压成前端用的来源卡片，顺便定死编号。

    `content` 也带上：点 `[n]` 要跳到原文的那一段，只给 snippet（带省略号）定位不到。
    """
    out = []
    for index, item in enumerate(items, start=1):
        out.append({
            "n": index,
            "item_id": item["item_id"],
            "item_title": item["item_title"],
            "chunk_id": item["chunk_id"],
            "source": item.get("source") or "raw",
            "snippet": item.get("snippet") or "",
            "content": item.get("content") or "",
        })
    return out


def context_block(sources_list: list[dict], items: list[dict]) -> str:
    """`[1] 《标题》` + 正文。超预算直接截断，宁可少给也不要爆上下文。"""
    parts, used = [], 0
    for source, item in zip(sources_list, items):
        head = f"[{source['n']}] 《{source['item_title']}》\n"
        body = (item.get("content") or "").strip()
        if used + len(head) + len(body) > MAX_CONTEXT_CHARS:
            body = body[: max(0, MAX_CONTEXT_CHARS - used - len(head))]
        if not body:
            continue
        parts.append(head + body)
        used += len(head) + len(body)
    return "\n\n".join(parts)


def build_messages(question: str, sources_list: list[dict], items: list[dict]) -> list[dict]:
    body = (PROMPT_DIR / "ask.md").read_text(encoding="utf-8")
    body = body.replace("{{CONTEXT}}", context_block(sources_list, items))
    body = body.replace("{{QUESTION}}", question)
    return [{"role": "user", "content": body}]


def stream(
    question: str, sources_list: list[dict], items: list[dict], usage: dict | None = None
) -> Iterator[str]:
    """流式产出答案片段。调用方负责把片段写进 SSE。"""
    messages = build_messages(question, sources_list, items)
    buffer: list[str] = []
    for piece in llm.chat_stream(messages, agent="asker", usage_out=usage):
        buffer.append(piece)
        yield piece
    answer = "".join(buffer)
    cited = {int(n) for n in _CITATION.findall(answer)}
    if not cited:
        # 不拦答案（已经流给用户了），但必须留痕：模型没按规则引用时，
        # 前端仍会展示 sources 卡片，用户不至于无从核对
        log.warning("问答未产生任何 [n] 引用（%s 字），已记录", len(answer))
