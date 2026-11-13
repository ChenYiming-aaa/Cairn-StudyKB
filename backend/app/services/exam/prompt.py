"""模型补字段（T10.2 第二段）：**只补规则切不出的字段，不许改题号与题干**。

第一段（`parse.py` 的规则切分）已经拿到了绝大多数东西：题号、选项字母、答案（答案页
有速查表时几乎 100% 命中）。模型只处理剩下的残局：

- 有选项字母但选项文本缺失（卷面把选项压成一行、或识别把选项吃掉了）
- 没有答案且**原文里其实写了**（如题干内的「（ B ）」被断开）
- 题型判不准（判断题写成「正确 / 错误」的两行、填空两空）

**为什么不让模型直接输出整道题**：它会顺手把题号改掉、把「下列」写成「下面」、
把选项重新排序。这些都是看不出来的漂移，而题目一旦漂移，导进来的是「另一张卷子」。
所以模型的输出只允许落到 `answer` / `type` / `score` / `options`（仅当规则一个都没切出时），
`question` 与 `number` 由调用方原样保留（`merge()` 里没有任何一行会覆盖它们）。
"""
from __future__ import annotations

import logging
import re

from app.paths import app_path
from app.services import llm

log = logging.getLogger(__name__)

TYPES = ("single", "multiple", "boolean", "short")
LETTERS = "ABCDEFGH"
_LETTER_ONLY = re.compile(r"^[A-H]$")


def _template() -> str:
    return (app_path("prompts") / "exam_parse.md").read_text(encoding="utf-8")


def messages(*, number: str, block: str) -> list[dict]:
    body = (
        f"{_template()}\n\n"
        f"题号：{number}\n"
        "—— 原文开始 ——\n"
        f"{block}\n"
        "—— 原文结束 ——\n\n"
        "现在只输出那个 JSON 对象。"
    )
    return [{"role": "user", "content": body}]


def _letters(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        text = str(raw).strip().upper()[:1]
        if _LETTER_ONLY.match(text) and text not in out:
            out.append(text)
    return sorted(out)


def _score(value, fallback: float | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if 0 < number <= 200 else fallback


def merge(draft: dict, data: dict) -> tuple[dict, list[str]]:
    """把模型给的东西并进规则草稿，返回 (草稿, 被采纳的字段名)。

    采纳是有条件的，条件写在每一行里 —— 这些条件就是「不许漂移」的守卫：
    答案必须是既有选项里的字母；选项只在规则一个都没切出来时才收；
    题型必须是四种之一；`question` / `number` 无论模型说什么都不动。
    """
    taken: list[str] = []
    options = draft.get("options") or []

    model_options = [str(o).strip() for o in (data.get("options") or []) if str(o).strip()]
    if not options and len(model_options) >= 2:
        cleaned, _ = _strip_prefixes(model_options)
        options = cleaned
        draft["options"] = options
        draft["options_incomplete"] = False
        taken.append("options")

    qtype = str(data.get("type") or "").strip()
    if qtype in TYPES:
        draft["type"] = qtype
        taken.append("type")

    answer = data.get("answer")
    if draft.get("answer") is None and answer is not None:
        accepted = _accept_answer(draft["type"], answer, len(options))
        if accepted is not None:
            draft["answer"] = accepted
            taken.append("answer")

    score = _score(data.get("score"), None)
    if draft.get("score") is None and score is not None:
        draft["score"] = score
        taken.append("score")

    if "confidence" in data:
        try:
            draft["confidence"] = max(float(draft.get("confidence") or 0), min(1.0, float(data["confidence"])))
        except (TypeError, ValueError):
            pass
    return draft, taken


def _strip_prefixes(options: list[str]) -> tuple[list[str], bool]:
    """模型给的选项可能带 `A.` 前缀：剥掉，字母由界面按顺序画（同 M4 口径）。"""
    pattern = re.compile(r"^\s*(?:[(（]?\s*[A-H]\s*[)）.．、:：])\s*")
    bare = [pattern.sub("", o, count=1).strip() for o in options]
    return [o for o in bare if o], True


def _accept_answer(qtype: str, answer, option_count: int):
    if qtype in ("single", "boolean"):
        if isinstance(answer, bool):
            return answer
        letters = _letters(answer)
        if qtype == "single" and len(letters) == 1 and len(letters[0]) == 1:
            order = LETTERS[:max(option_count, 4)]
            return letters[0] if letters[0] in order else None
        return answer if isinstance(answer, bool) else None
    if qtype == "multiple":
        letters = _letters(answer)
        order = LETTERS[:max(option_count, 4)]
        return letters if letters and all(x in order for x in letters) else None
    text = str(answer).strip()
    return text or None


def refine(drafts: list[tuple[dict, str]]) -> int:
    """对「需要补」的草稿逐条调模型，返回被改过的条数。

    单条失败只记 warning 继续 —— 一道题补不出来不该让整份解析失败（规则部分已经是可用的）。
    没有 Key / 模型超时同样只是「没补上」，**不改变草稿已有的内容**。
    """
    changed = 0
    for draft, block in drafts:
        try:
            raw = llm.chat(messages(number=draft["number"], block=block),
                           agent="exam_parse", json_mode=True)
            draft, taken = merge(draft, llm.extract_json(raw))
        except llm.LLMError as exc:
            log.warning("第 %s 题补字段放弃（%s）", draft.get("number"), exc.code)
            continue
        except Exception as exc:            # noqa: BLE001 - 单题失败不能拖垮整份
            log.warning("第 %s 题补字段异常：%s", draft.get("number"), type(exc).__name__)
            continue
        if taken:
            changed += 1
    return changed
