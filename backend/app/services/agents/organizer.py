"""整理 Agent（T1.8 → T9.11 按 kind 分派）：raw_content → 分类 / 标签 / 摘要 / 关键点 / 结构化笔记。

设计要点（M1 §6.5、§6.6，数据契约 §6）：
- prompt 全部放 `prompts/`，代码只引用文件名（总纲 §7）
- 输出严格 JSON；解析失败重试一次，质量不合格（summary 空 / key_points 不足）也重试一次
- 原文超过 50,000 字符时采样前 40,000 + 末 10,000，并置 truncated=1
- 写入 structured_note 后必须按数据契约 §6 重建 source='note' 的 chunk
- 失败一律抛异常交给任务队列落 agent_task（红线 8），不静默

**T9.11 按 `kind` 分派**（别对试卷和图片写「要点 + 笔记」，那是纯浪费且污染学习页）：

| kind | prompt | 产出 | structured_note |
|---|---|---|---|
| `material` | `organize.md` | 标题/摘要/要点/笔记/分类 | 写 |
| `exam` | `organize_exam.md` | 卷面概览：科目、题型分布、题数、涉及知识点 | **不写（置 NULL）** |
| `image` | `organize_image.md` | 一句话说明 + 图上看得出的要点 | **不写（置 NULL）** |

为什么 exam/image 要**清空**而不是「保留旧值」：一条内容如果从 material 被确认成 exam，
它原来的笔记就是「给试卷写的要点」，留着会继续出现在学习页与导图里 —— 正是这张卡要治的污染。
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from app.db.conn import get_conn
from app.db.repo import items as repo
from app.services import llm, prompts
from app.services.llm import LLMError
from app.services.schemas import OrganizeResult

log = logging.getLogger(__name__)

SAMPLE_LIMIT = 50_000
HEAD_CHARS = 40_000
TAIL_CHARS = 10_000
OMIT_MARKER = "\n\n[内容过长，已省略中间部分]\n\n"

RETRY_HINT = (
    "上一次的输出不合格：summary 为空，或 key_points 少于 3 条，或 structured_note 为空。"
    "请严格按 schema 重新只输出一个 JSON 对象，不要任何解释文字。"
)

# 每种 kind 的自我纠正提示必须跟着换，否则会出现「用试卷的 prompt 要求补笔记」
EXAM_RETRY_HINT = (
    "上一次的输出不合格：summary 为空，或卷面概览少于 2 条。"
    "请严格按 schema 重新只输出一个 JSON 对象，不要任何解释文字，也不要输出 structured_note。"
)
IMAGE_RETRY_HINT = (
    "上一次的输出不合格：summary 为空。"
    "请严格按 schema 重新只输出一个 JSON 对象，不要任何解释文字，也不要输出 structured_note。"
)

# kind → (prompt 文件, 重试提示)
KINDS = {
    "material": ("organize.md", RETRY_HINT),
    "exam": ("organize_exam.md", EXAM_RETRY_HINT),
    "image": ("organize_image.md", IMAGE_RETRY_HINT),
}


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


def _build_messages(title: str, content: str, truncated: bool,
                    kind: str = "material") -> list[dict]:
    prompt_file = KINDS.get(kind, KINDS["material"])[0]
    body = prompts.render(prompt_file, title=title, content=content)
    if truncated:
        body += "\n\n（注意：正文过长，中间部分已省略。不要据此推测或补写被省略的内容。）"
    return [{"role": "user", "content": body}]


def _normalize(data: dict, fallback_title: str, kind: str = "material") -> OrganizeResult:
    """模型的 JSON → `OrganizeResult`。形状与容错都在 `services/schemas.py`，这里不再各写一套。

    唯一留在调用点的判断是「兜底之后仍然不合法」：那说明容错本身有 bug（字段改名、
    兜底值变空），落成 `LLM_BAD_RESPONSE` 走 `_organize_with_retry` 的重试分支 ——
    与坏 JSON 同一条路，重试一次还不行就整条失败，不新增错误码也不新增文案。
    """
    try:
        return OrganizeResult.from_raw(data, fallback_title, kind)
    except ValidationError as exc:
        log.error("整理结果形状不合法（kind=%s）：%s", kind, exc.error_count())
        raise LLMError("LLM_BAD_RESPONSE", "LLM 响应结构异常", "schema") from None


def _quality_ok(result: OrganizeResult, kind: str = "material") -> bool:
    """M1 §6.5：key_points < 2 或 summary 为空视为不合格。

    `image` 只要求 summary：一张只有两行字的照片本来就没有两个要点，
    按 material 的标准重试只会让模型编出两条凑数。
    """
    if not result.summary:
        return False
    if kind == "image":
        return True
    return len(result.key_points) >= 2


def _yield_to_user(item_id: int, overwrite_note: bool) -> bool:
    """排队期间用户手改过笔记 → 放行这次整理（返回 True）。

    `dispatch.organize_if_pending` 在**派任务时**已经挡过一次 `note_edited`，
    但任务可能排队等模型、等别的任务跑好几分钟，用户完全可能在这段时间里打开这条
    改掉笔记。写入时不复查，就会出现「我刚改完，一刷新全没了」——
    而这正是自动化最招人恨的形态。复查放在调模型之前，省掉一次白花钱的调用。

    状态落回 `pending` 而不是 `ready`：这次确实没整理，界面上「待整理」才是实话。
    用户点「重新整理」（界面会先弹确认框）时任务带 `overwrite_note=True`，不再走这里。
    """
    if overwrite_note:
        return False
    conn = get_conn()
    try:
        row = repo.get_item(conn, item_id)
        if row is None or not row["note_edited"]:
            return False
        with conn:
            repo.set_status(conn, item_id, "pending")
    finally:
        conn.close()
    log.warning("条目 %s 在整理排队期间笔记被手改，本次整理让开", item_id)
    return True


def run(task_input: dict | None = None) -> dict:
    """任务队列入口。成功返回 {item_id, truncated, note_chunk_count}。

    `overwrite_note=True` 只由「用户点过确认框的重新整理」传进来：它允许把
    `note_edited` 清成 0（手改的那份笔记已被这次整理取代）。自动与批量整理一律不传，
    否则用户手改过的笔记会在下一次采集时被静默覆盖。
    """
    payload = task_input or {}
    item_id = int(payload.get("item_id") or 0)
    overwrite_note = bool(payload.get("overwrite_note"))
    conn = get_conn()
    try:
        row = repo.get_item(conn, item_id)
        if row is None:
            raise OrganizeError("ITEM_NOT_FOUND", f"内容 {item_id} 不存在")
        title = row["title"]
        kind = str(row["kind"] or "material")
        content, truncated = sample_text(row["raw_content"] or "")
    finally:
        conn.close()

    if not content.strip():
        _mark_failed(item_id, "原文为空，无法整理")
        raise OrganizeError("ORGANIZE_EMPTY_CONTENT", "原文为空，无法整理")

    # 用户已经接管这条内容 → 连模型都不必调
    if _yield_to_user(item_id, overwrite_note):
        return {"item_id": item_id, "skipped": "note_edited"}

    try:
        result = _organize_with_retry(
            _build_messages(title, content, truncated, kind), title, kind
        )
    except LLMError as exc:
        # 根因在 LLM 侧（无 Key / 超时 / JSON 解析失败），原样上抛给任务队列
        _mark_failed(item_id, exc.message)
        raise
    except Exception as exc:
        _mark_failed(item_id, str(exc)[:200])
        raise OrganizeError("ORGANIZE_FAILED", str(exc)[:200]) from None

    # 模型调用那几十秒里用户也可能手改，写库前再复查一次
    if _yield_to_user(item_id, overwrite_note):
        return {"item_id": item_id, "skipped": "note_edited"}

    conn = get_conn()
    try:
        with conn:
            repo.save_organize_result(
                conn, item_id, title=result.title,
                category=result.category, tags=result.tags,
                summary=result.summary, key_points=result.key_points,
                # 非 material 是 ""：**明确清空**（不是「别动」），见 save_organize_result 三态
                structured_note=result.structured_note, truncated=truncated,
                reset_note_edited=overwrite_note,
            )
            # 数据契约 §6：新 structured_note 必须重建 note chunk（空串 = 删掉旧 note chunk）
            note_chunks = repo.rebuild_chunks(conn, item_id, result.structured_note, "note")
    finally:
        conn.close()

    log.info("条目 %s 整理完成（kind=%s, title=%s, truncated=%s, note_chunk=%s）",
             item_id, kind, result.title, truncated, note_chunks)
    return {"item_id": item_id, "title": result.title,
            "truncated": truncated, "note_chunk_count": note_chunks}


def _organize_with_retry(messages: list[dict], fallback_title: str,
                         kind: str = "material") -> OrganizeResult:
    """解析失败重试一次；质量不合格也重试一次。最多两次调用。"""
    hint = KINDS.get(kind, KINDS["material"])[1]
    last_error: LLMError | None = None
    for attempt in range(2):
        try:
            result = _normalize(llm.json_call(messages, agent="organizer"),
                                fallback_title, kind)
        except LLMError as exc:
            last_error = exc
            if exc.code in ("LLM_BAD_JSON", "LLM_BAD_RESPONSE") and attempt == 0:
                log.warning("整理结果解析失败（%s），重试一次", exc.code)
                messages = messages + [{"role": "user", "content": hint}]
                continue
            raise
        if _quality_ok(result, kind):
            return result
        if attempt == 0:
            log.warning("整理结果质量不合格（kind=%s, summary=%s, key_points=%s），重试一次",
                        kind, bool(result.summary), len(result.key_points))
            messages = messages + [{"role": "user", "content": hint}]
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
