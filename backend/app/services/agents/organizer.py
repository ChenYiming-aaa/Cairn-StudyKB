"""整理 Agent（T1.8）：raw_content → 分类 / 标签 / 摘要 / 关键点 / 结构化笔记。

设计要点（M1 §6.5、§6.6，数据契约 §6）：
- prompt 全部放 `prompts/organize.md`，代码只引用文件名（总纲 §7）
- 输出严格 JSON；解析失败重试一次，质量不合格（summary 空 / key_points < 2）也重试一次
- 原文超过 50,000 字符时采样前 40,000 + 末 10,000，并置 truncated=1
- 写入 structured_note 后必须按数据契约 §6 重建 source='note' 的 chunk
- 失败一律抛异常交给任务队列落 agent_task（红线 8），不静默
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.db.conn import get_conn
from app.db.repo import items as repo
from app.services import llm
from app.services.llm import LLMError

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

SAMPLE_LIMIT = 50_000
HEAD_CHARS = 40_000
TAIL_CHARS = 10_000
OMIT_MARKER = "\n\n[内容过长，已省略中间部分]\n\n"
MAX_TAGS = 6
MAX_KEY_POINTS = 8

RETRY_HINT = (
    "上一次的输出不合格：summary 为空，或 key_points 少于 3 条，或 structured_note 为空。"
    "请严格按 schema 重新只输出一个 JSON 对象，不要任何解释文字。"
)


class OrganizeError(Exception):
    """带错误码的业务异常，形状与 LLMError 一致，便于任务队列统一记录。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def sample_text(text: str) -> tuple[str, bool]:
    """M1 §6.6：超过 50,000 字符采样，返回 (采样后文本, 是否截断)。"""
    if len(text) <= SAMPLE_LIMIT:
        return text, False
    return text[:HEAD_CHARS] + OMIT_MARKER + text[-TAIL_CHARS:], True


def _read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _build_messages(title: str, content: str, truncated: bool) -> list[dict]:
    body = _read_prompt("organize.md").replace("{{TITLE}}", title).replace("{{CONTENT}}", content)
    if truncated:
        body += "\n\n（注意：正文过长，中间部分已省略。不要据此推测或补写被省略的内容。）"
    return [{"role": "user", "content": body}]


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _normalize(data: dict) -> dict:
    """容错：模型偶尔把 tags 写成字符串、把 key_points 写成带序号的段落。"""
    tags: list[str] = []
    for raw in _as_list(data.get("tags")):
        text = str(raw).strip().lstrip("#").strip()
        if text and text not in tags:
            tags.append(text)

    points = [str(p).strip() for p in _as_list(data.get("key_points")) if str(p).strip()]

    return {
        "category": str(data.get("category") or "").strip() or "未分类",
        "tags": tags[:MAX_TAGS],
        "summary": str(data.get("summary") or "").strip(),
        "key_points": points[:MAX_KEY_POINTS],
        "structured_note": str(data.get("structured_note") or "").strip(),
    }


def _quality_ok(result: dict) -> bool:
    """M1 §6.5：key_points < 2 或 summary 为空视为不合格。"""
    return bool(result["summary"]) and len(result["key_points"]) >= 2


def run(task_input: dict | None = None) -> dict:
    """任务队列入口。成功返回 {item_id, truncated, note_chunk_count}。"""
    item_id = int((task_input or {}).get("item_id") or 0)
    conn = get_conn()
    try:
        row = repo.get_item(conn, item_id)
        if row is None:
            raise OrganizeError("ITEM_NOT_FOUND", f"条目 {item_id} 不存在")
        title = row["title"]
        content, truncated = sample_text(row["raw_content"] or "")
    finally:
        conn.close()

    if not content.strip():
        _mark_failed(item_id, "原文为空，无法整理")
        raise OrganizeError("ORGANIZE_EMPTY_CONTENT", "原文为空，无法整理")

    try:
        result = _organize_with_retry(_build_messages(title, content, truncated))
    except LLMError as exc:
        # 根因在 LLM 侧（无 Key / 超时 / JSON 解析失败），原样上抛给任务队列
        _mark_failed(item_id, exc.message)
        raise
    except Exception as exc:
        _mark_failed(item_id, str(exc)[:200])
        raise OrganizeError("ORGANIZE_FAILED", str(exc)[:200]) from None

    conn = get_conn()
    try:
        with conn:
            repo.save_organize_result(
                conn, item_id, category=result["category"], tags=result["tags"],
                summary=result["summary"], key_points=result["key_points"],
                structured_note=result["structured_note"], truncated=truncated,
            )
            # 数据契约 §6：新 structured_note 必须重建 note chunk
            note_chunks = repo.rebuild_chunks(conn, item_id, result["structured_note"], "note")
    finally:
        conn.close()

    log.info("条目 %s 整理完成（truncated=%s, note_chunk=%s）", item_id, truncated, note_chunks)
    return {"item_id": item_id, "truncated": truncated, "note_chunk_count": note_chunks}


def _organize_with_retry(messages: list[dict]) -> dict:
    """解析失败重试一次；质量不合格也重试一次。最多两次调用。"""
    last_error: LLMError | None = None
    for attempt in range(2):
        try:
            raw = llm.chat(messages, agent="organizer", json_mode=True)
            result = _normalize(llm.extract_json(raw))
        except LLMError as exc:
            last_error = exc
            if exc.code in ("LLM_BAD_JSON", "LLM_BAD_RESPONSE") and attempt == 0:
                log.warning("整理结果解析失败（%s），重试一次", exc.code)
                messages = messages + [{"role": "user", "content": RETRY_HINT}]
                continue
            raise
        if _quality_ok(result):
            return result
        if attempt == 0:
            log.warning("整理结果质量不合格（summary=%s, key_points=%s），重试一次",
                        bool(result["summary"]), len(result["key_points"]))
            messages = messages + [{"role": "user", "content": RETRY_HINT}]
            continue
        # 第二次仍不合格：不编造、不丢弃已有内容，接受结果但留痕
        log.warning("整理结果连续两次不合格，接受现有内容")
        return result
    raise last_error or OrganizeError("ORGANIZE_FAILED", "整理失败")


def _mark_failed(item_id: int, reason: str) -> None:
    """失败时把条目状态落为 failed，前端能看到（红线 8）。"""
    conn = get_conn()
    try:
        with conn:
            repo.set_status(conn, item_id, "failed")
    except Exception as exc:  # 落状态本身失败也不能掩盖原始错误
        log.error("条目 %s 状态落 failed 失败：%s", item_id, type(exc).__name__)
    finally:
        conn.close()
    log.error("条目 %s 整理失败：%s", item_id, reason)
