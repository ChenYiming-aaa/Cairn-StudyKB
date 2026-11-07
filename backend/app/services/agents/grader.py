"""判分 Agent（T4.4）：客观题后端比对，简答走 LLM 批改。

约束（M4 §1 约束 3、§6.4）：
- 单选/多选/判断的判分**只在后端**做，前端只展示结果
- 多选按**集合**比较，`["C","A"]` 与 `["A","C"]` 都算对（排障表：用 `==` 比列表会全判错）
- 简答批改失败（超时 / 坏 JSON / 无 Key）→ `is_correct = None` + 「待人工判断」，
  **绝不默认判错**；`None` 落库就是 NULL，不能写成 0
- prompt 放 `prompts/grader.md`，代码只引用文件名（总纲 §7）
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from app.services import llm

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"

MIN_SCORE = 0.6
GRADER_TIMEOUT = 60          # 排障表：超时太短会全部「待人工判断」
GRADER_MATERIAL = 2500       # 批改只需要能核对要点，不必给全文
FAIL_FEEDBACK = "批改服务不可用，已标记待人工判断"
# 排障表要求超时与额度给不同提示：用户能做的事不一样（等一会儿重答 / 去充值）。
# 两种都保留「待人工判断」四个字——前端与 verify 都靠它判断这是 NULL 而不是判错。
FAIL_HINTS = {
    "LLM_TIMEOUT": f"批改超时（{GRADER_TIMEOUT}s 没返回），已标记待人工判断，可稍后重答",
    "LLM_QUOTA": "模型额度不足或触发限流，批改没跑成，已标记待人工判断",
}

log = logging.getLogger(__name__)

_WS = re.compile(r"\s+")
_LETTER = re.compile(r"^\s*([A-Za-z])")


def _text(value) -> str:
    return _WS.sub(" ", str(value or "")).strip()


def _bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in ("true", "对", "正确", "是", "1"):
        return True
    if text in ("false", "错", "错误", "否", "0"):
        return False
    return None


def _letters(value) -> set[str]:
    """用户答案可能是 ["A","C"]、也可能是 "A,C" / "AC"（前端控件不同）。"""
    if isinstance(value, list):
        items = [str(v) for v in value]
    else:
        text = _text(value)
        items = re.split(r"[,，、\s]+", text) if re.search(r"[,，、\s]", text) else list(text)
    out = set()
    for item in items:
        match = _LETTER.match(item)
        if match:
            out.add(match.group(1).upper())
    return out


def grade_objective(question: dict, user_answer) -> bool:
    """M4 §6.4：多选集合比较；单选大小写与空白归一；判断转布尔。"""
    expected = question.get("answer")
    if user_answer is None or user_answer == "" or user_answer == []:
        return False

    if question.get("type") == "multiple":
        want = set(expected) if isinstance(expected, list) else _letters(expected)
        return bool(want) and _letters(user_answer) == want

    if question.get("type") == "boolean":
        got, want = _bool(user_answer), _bool(expected)
        return got is not None and want is not None and got == want

    return _text(user_answer).upper() == _text(expected).upper()


def _messages(question: dict, user_answer: str, material: str) -> list[dict]:
    body = (PROMPT_DIR / "grader.md").read_text(encoding="utf-8")
    body = body.replace("{{MATERIAL}}", material or "（未提供材料，仅按参考答案判断）")
    body = body.replace("{{QUESTION}}", _text(question.get("question")))
    body = body.replace("{{REFERENCE}}", _text(question.get("answer")))
    body = body.replace("{{USER_ANSWER}}", user_answer)
    return [{"role": "user", "content": body}]


def grade_short(
    question: dict, user_answer, material: str = ""
) -> tuple[int | None, str]:
    """返回 (is_correct, feedback)。失败时第一项是 None（待人工判断），不是 0。"""
    answer = _text(user_answer)
    if not answer:
        return 0, "未作答。参考答案：" + _text(question.get("answer"))

    try:
        raw = llm.chat(
            _messages(question, answer, material),
            agent="grader", json_mode=True, timeout=GRADER_TIMEOUT,
        )
        data = llm.extract_json(raw)
        score = float(data.get("score"))
        feedback = _text(data.get("feedback"))
    except (llm.LLMError, TypeError, ValueError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        log.warning("简答批改失败（%s，题目 %s），标记待人工判断",
                    code, question.get("id"))
        return None, FAIL_HINTS.get(code, FAIL_FEEDBACK)

    if not feedback:
        # 没给出任何反馈等于没批改：宁可不判，也不给用户一个空结论
        log.warning("简答批改返回空 feedback（题目 %s），标记待人工判断", question.get("id"))
        return None, FAIL_FEEDBACK

    return (1 if score >= MIN_SCORE else 0), feedback


def grade(question: dict, user_answer, material: str = "") -> tuple[int | None, str | None]:
    """统一入口：客观题同步比对（feedback=None），简答走 LLM。"""
    if question.get("type") == "short":
        return grade_short(question, user_answer, material)
    return (1 if grade_objective(question, user_answer) else 0), None
