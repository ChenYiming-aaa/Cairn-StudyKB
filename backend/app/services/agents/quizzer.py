"""出题 Agent（T4.1）：材料 → 严格 JSON 题组，流式增量解析。

约束（M4 §1、§6.1–§6.3）：
- 出题**只依据给定材料**，prompt 里写死不许编造（`prompts/quiz.md`）
- 一次调用出全部题，靠 `scan_objects()` 增量抽 `{...}`，每完成一题就能 emit（T4.2）
- 单题解析/校验失败只跳过这一题，绝不让整条流崩（M4 §1 约束 2）
- 材料默认 6000 字预算，**按 chunk 等距抽样覆盖全文**（用户 2026-11-07 裁决），
  不是截前 6000 字——视频转录/长文的前 6000 字往往只是开场
- 指纹归一化只写一处（`questions.fingerprint`），出入库共用
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

from app.db.repo import questions as qrepo
from app.paths import app_path
from app.services import llm

PROMPT_DIR = app_path("prompts")

MAX_MATERIAL = 6000        # 出题材料预算（M4 §6.1）
MIN_MATERIAL = 120         # 低于这个长度基本出不了题，直接拒绝，不浪费一次 LLM 调用
# 20 题 × (题干+选项+解析) 约 4k+ token，默认 4096 会把末题截断成坏 JSON，
# 于是全部落进 skip 再触发补生成——反而更慢更贵。给足 8192。
MAX_TOKENS = 8192
TYPES = ("single", "multiple", "boolean", "short")
DIFFICULTIES = ("basic", "understand", "apply")
TYPE_LABELS = {"single": "单选", "multiple": "多选", "boolean": "判断", "short": "简答"}

log = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_LETTER = re.compile(r"^\s*([A-Za-z])")


class QuizError(Exception):
    """带 HTTP 状态码的业务异常，形状与 ApiError 一致，便于路由层直接转。"""

    def __init__(self, code: str, message: str, status: int = 400, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail


# ── 材料 ────────────────────────────────────────────────────

def sample_material(chunks: list[str], limit: int = MAX_MATERIAL) -> str:
    """按 chunk 等距抽样，拼出覆盖全文的 `limit` 字材料。

    chunk 之间有 80 字重叠（M1 §6.4），拼回来会重复少量句子，但比"只给开头"
    更可能出到中段/结尾的题，代价可以接受。
    """
    pieces = [c.strip() for c in chunks if c and c.strip()]
    if not pieces:
        return ""
    if sum(len(p) for p in pieces) <= limit:
        return "\n\n".join(pieces)

    total = sum(len(p) for p in pieces)
    take = min(len(pieces), max(1, int(len(pieces) * limit / total)))
    if take >= len(pieces):
        picked = list(range(len(pieces)))
    elif take == 1:
        picked = [0]
    else:
        # 首尾都取到：i*(n-1)/(take-1)，四舍五入后去重
        picked = sorted({round(i * (len(pieces) - 1) / (take - 1)) for i in range(take)})

    out: list[str] = []
    used = 0
    for index in picked:
        room = limit - used
        if room <= 0:
            break
        piece = pieces[index][:room]
        out.append(piece)
        used += len(piece)
    return "\n\n".join(out)


def material_for_item(conn, item_id: int, limit: int = MAX_MATERIAL) -> tuple[str, str]:
    """返回 (标题, 材料)。条目不存在抛 ITEM_NOT_FOUND，材料过短抛 QUIZ_MATERIAL_TOO_SHORT。"""
    row = conn.execute(
        "SELECT id, title, raw_content FROM knowledge_item WHERE id=?", (item_id,)
    ).fetchone()
    if row is None:
        raise QuizError("ITEM_NOT_FOUND", f"内容 {item_id} 不存在", status=404)

    rows = conn.execute(
        "SELECT content FROM chunk WHERE item_id=? AND source='raw' ORDER BY position",
        (item_id,),
    ).fetchall()
    chunks = [r["content"] for r in rows] or [row["raw_content"] or ""]
    material = sample_material(chunks, limit)
    if len(material) < MIN_MATERIAL:
        raise QuizError(
            "QUIZ_MATERIAL_TOO_SHORT",
            f"材料只有 {len(material)} 字，至少 {MIN_MATERIAL} 字才出得了题",
            detail="换一条内容更完整的，或先把笔记补长",
        )
    return row["title"], material


# ── 增量括号扫描（M4 §6.2）─────────────────────────────────

def scan_objects(buf: str) -> tuple[list[str], str]:
    """抽出 buf 中所有**已完整**的顶层 `{...}`，返回 (对象列表, 剩余 buf)。

    必须跟踪 `in_str`：题干里出现 `{}`（如写代码示例）时不跟踪就会错位。
    截断在末尾的对象留在剩余里，等下一个 delta 补齐。
    """
    found: list[str] = []
    start, depth, in_str, esc, consumed = -1, 0, False, False, 0
    for i, ch in enumerate(buf):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                found.append(buf[start:i + 1])
                start = -1
                consumed = i + 1
    return found, (buf[consumed:] if found else buf)


class Scanner:
    """喂 delta 进去，吐出已完整的对象字符串。"""

    def __init__(self) -> None:
        self.buf = ""

    def feed(self, piece: str) -> list[str]:
        self.buf += piece
        found, self.buf = scan_objects(self.buf)
        return found

    def leftover(self) -> str:
        return self.buf


# ── 校验与归一化 ────────────────────────────────────────────

def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _options(value: Any) -> list[str]:
    """选项一律存裸文本：模型爱写 "A. xxx"，字母由界面画，剥掉（2026-11-08 缺陷）。"""
    if not isinstance(value, list):
        return []
    return qrepo.clean_options([_text(o) for o in value])


def _letter(value: Any) -> str | None:
    """模型偶尔给 "B." / "b" / "B. 选项文本"，统一取首字母。"""
    match = _LETTER.match(_text(value))
    return match.group(1).upper() if match else None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in ("true", "对", "正确", "是", "1"):
        return True
    if text in ("false", "错", "错误", "否", "0"):
        return False
    return None


def _answer(qtype: str, value: Any, option_count: int) -> tuple[Any, str]:
    """返回 (归一化答案, 失败原因)。失败原因空串表示合法。"""
    if qtype == "boolean":
        parsed = _bool(value)
        return (parsed, "") if parsed is not None else (None, "bad_answer")

    if qtype == "single":
        if option_count < 2:
            return None, "bad_options"
        letter = _letter(value)
        if letter is None or letter > chr(ord("A") + option_count - 1):
            return None, "bad_answer"
        return letter, ""

    if qtype == "multiple":
        if option_count < 2:
            return None, "bad_options"
        raw = value if isinstance(value, list) else re.split(r"[,，、\s]+", _text(value))
        letters = sorted({x for x in (_letter(v) for v in raw) if x})
        if len(letters) < 2:
            return None, "bad_answer"
        if letters[-1] > chr(ord("A") + option_count - 1):
            return None, "bad_options"
        return letters, ""

    # short：参考答案要点文本
    reference = _text(value)
    return (reference, "") if len(reference) >= 2 else (None, "bad_answer")


def normalize(raw: dict, *, difficulty: str) -> tuple[dict | None, str]:
    """把模型给的对象压成入库形状。返回 (题目, 失败原因)，原因空串表示通过。"""
    qtype = _text(raw.get("type")).lower()
    if qtype not in TYPES:
        return None, "bad_type"

    question = _text(raw.get("question"))
    if len(question) < 4:
        return None, "empty_question"

    explanation = _text(raw.get("explanation"))
    if not explanation:
        # DoD 要求每题都有解析；编不出来就是没从材料找到依据，直接跳过
        return None, "missing_explanation"

    options = _options(raw.get("options")) if qtype in ("single", "multiple") else []
    answer, reason = _answer(qtype, raw.get("answer"), len(options))
    if reason:
        return None, reason

    level = _text(raw.get("difficulty")).lower()
    return {
        "type": qtype,
        "question": question,
        "options": options,
        "answer": answer,
        "explanation": explanation,
        "difficulty": level if level in DIFFICULTIES else difficulty,
    }, ""


# ── prompt 装配 ─────────────────────────────────────────────

def messages_for(
    *, title: str, material: str, types: list[str], difficulty: str,
    count: int, exclude: list[str],
) -> list[dict]:
    body = (PROMPT_DIR / "quiz.md").read_text(encoding="utf-8")
    note = "已按段落抽样，覆盖全文首尾" if len(material) >= MAX_MATERIAL else f"共 {len(material)} 字"
    body = body.replace("{{TITLE}}", title)
    body = body.replace("{{MATERIAL_NOTE}}", note)
    body = body.replace("{{MATERIAL}}", material)
    body = body.replace("{{TYPES}}", "、".join(type_desc(types)))
    body = body.replace("{{DIFFICULTY}}", difficulty)
    body = body.replace("{{COUNT}}", str(count))
    body = body.replace("{{EXCLUDE}}", ("\n" + "\n".join(f"- {q}" for q in exclude)) if exclude else "（无）")
    return [{"role": "user", "content": body}]


def type_desc(types: list[str]) -> list[str]:
    return [f"{t}（{TYPE_LABELS[t]}）" for t in types if t in TYPE_LABELS]


def stream(messages: list[dict]) -> Iterator[str]:
    """出题的流式调用入口：统一 agent 名与 max_tokens，路由层不再关心这些。"""
    return llm.chat_stream(messages, agent="quizzer", max_tokens=MAX_TOKENS)


def iter_raw_objects(text: str) -> Iterator[dict]:
    """非流式场景（补生成）用：从整段文本里取出所有可解析对象。"""
    objects, _ = scan_objects(text)
    for piece in objects:
        try:
            parsed = json.loads(piece)
        except ValueError:
            log.warning("出题结果里有一段无法解析的对象（%s 字），已跳过", len(piece))
            continue
        if isinstance(parsed, dict):
            yield parsed
