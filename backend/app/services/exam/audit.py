"""题目初审（T10.9）：**判这道题能不能用，不替用户改卷子**。

识别 → 规则切分（`parse`）→ 复核（人）。原本中间还有一次「模型补字段」，
但它只在 `answer is None` 时触发，补的也只有答案。**没人看这题读出来像不像一道题**：
题干被截掉半句、两道题粘成一道、选项串进题干 —— 这些都能顺利导入，
用户到「按卷练习」才发现，而那时已经不知道错在哪一步。

所以加这一层，只做三件事：

1. **体检**：有没有答案、题干是不是一句完整的话、选项与题干对不对得上。
2. **报出来**：每条问题一句人话，挂回复核页对应的那道题，用户不用一题题自己读。
3. **给一条可采纳的改法**（只在模型有把握时）：**绝不自动应用**，人点「用这条」才改草稿。

## 与相邻两层的分工（别混）

| 层 | 改什么 | 怎么生效 |
|---|---|---|
| `clean` / `parse` | 规则能确定的一切（题号、选项字母、答案速查） | 直接产出草稿 |
| `proofread` 校对 | **页文本**里的错字，写 `text_reviewed` | 人逐条勾选，按行生效 |
| `audit` 初审 | **草稿字段**（题干） | 人点「用这条」，只动前端草稿 |

`text_reviewed` 是页文本的旁路，`parse.load_pages` 读它优先于 `text`，所以
「先校对、再解析」能把校对的成果带进题目；初审不写任何东西，`commit` 之前刷新一次即可。

## 三条不让步

- **答案一个字都不生成**。缺答案只报不补：猜一个答案比留空伤害大得多（需求 §13 风险 7），
  答案由复核页的人定。模型就算在 `note` 里提答案，也收不进来。
- **模型给的改法永不自动应用**。校对那层的「编辑距离 ≤ 30%」在这里不够用 ——
  题干被截断，正是要**多出半句**，比例必然不小。换成另外三道守卫：
  ① 数字串必须一模一样（识别错的是形近字，不是数字；数字一变答案就错）；
  ② 与原文的编辑距离 ≤ 55%（挡「换成另一句话」）；
  ③ 不能自带题号前缀（挡「把下一题并进来」）。
  任一条没过：**问题照报，改法丢掉**，并在 `dropped` 里写明原因。
- **不确定就别报**。报一堆「我觉得这题有点怪」比不报更糟，用户会学会无视它。
"""
from __future__ import annotations

import logging
import re

from app.paths import app_path
from app.services import llm
# 同一把尺子：改动的「差得远不远」两边必须用同一个算法，抄第二份迟早算出两个答案
from app.services.exam.proofread import _levenshtein

log = logging.getLogger(__name__)

BATCH_QUESTIONS = 6         # 一批几道题：再多模型开始串行（相邻题的题干会互相看混）
BATCH_CHARS = 1200          # 一批多少字：材料题自己占一批，别把别人挤掉
MAX_FIX_RATIO = 3.0         # 改法字数上限 = 原文 × 3 + 20
MIN_FIX_BUDGET = 20
MAX_EDIT_RATIO = 0.55       # 改法与原文的编辑距离上限（题干级，比校对的行级宽）
MAX_NOTE = 60               # 模型补的一句说明，太长说明它在写小作文
LETTERS = "ABCDEFGH"
TYPE_LABELS = {"single": "单选", "multiple": "多选", "boolean": "判断", "short": "简答"}

# code → (级别, 给人看的一句话)。**报文固定**，模型只补 note，不许自己写整段。
ISSUES: dict[str, tuple[str, str]] = {
    "NO_ANSWER": ("error", "这题没认到答案，导入后判不了分"),
    "NO_STEM": ("error", "题干是空的，这题用不了"),
    "SHORT_STEM": ("warn", "题干只有几个字，可能只认到半句"),
    "STEM_TAIL": ("warn", "题干断在半路，后半句可能没读到"),
    "OPTION_IN_STEM": ("warn", "选项混进题干了，对着页图看看"),
    "DUP_OPTION": ("warn", "有两个选项内容一样"),
    "STEM_DUP": ("warn", "题干里有一句重复了"),
    "FEW_OPTIONS": ("warn", "选项不到两个，导入后会存成简答"),
    "ANSWER_OUT_OF_RANGE": ("warn", "答案指向的选项不存在"),
    # 下面四个只由模型报（规则判不出来）
    "STEM_CUT": ("warn", "题干像是被截断了"),
    "STEM_MIXED": ("warn", "题干里混进了相邻题目的内容"),
    "OPTION_MIXED": ("warn", "选项混进了题干"),
    "UNREADABLE": ("warn", "这段读出来不像一句完整的话"),
}
RULE_CODES = ("NO_ANSWER", "NO_STEM", "SHORT_STEM", "STEM_TAIL", "OPTION_IN_STEM",
              "DUP_OPTION", "STEM_DUP", "FEW_OPTIONS", "ANSWER_OUT_OF_RANGE")
MODEL_CODES = ("STEM_CUT", "STEM_MIXED", "OPTION_MIXED", "UNREADABLE")

# 模型判出来之后，规则那条就收起来 —— 同一件事说两遍，用户会以为有两个问题。
# 只列真正同义的：`STEM_MIXED`（两题粘连）与规则的任何一条都不是一回事，不收。
SUPERSEDES = {
    "STEM_CUT": ("STEM_TAIL",),        # 「题干断了」规则与模型说的是同一个现象
    "OPTION_MIXED": ("OPTION_IN_STEM",),
}

# 题干结尾落在这些字上，几乎不可能是一句完整的话。
# 只留「无论如何都收不了尾」的功能字；这几类刻意不在内（都是完整的结尾）：
#   「是」——「…的值是」「…正确的是」是最常见的题干写法，误报最多的就是它；
#   「和 / 与 / 或」——「输出 1 到 10 的和」是完整的名词短语（这条被真实用例打红过）；
#   「在 / 为 / 上 / 下」——「存在」「称为」「如下」都收得住。
_TAIL_CUT = ("的", "中", "把", "被", "对", "使", "让", "即", "则", "从", "向")
_TERMINAL = "？?。.！!；;：:…"
# `A.` `B、` 出现在题干里：选项被吞进来了（前面得有分隔，免得吃掉英文里的缩写）
_OPTION_IN_TEXT = re.compile(r"(?:^|[\s；;，,])[A-D]\s*[.、．)）]\s*\S")


def _issue(code: str, *, source: str = "rule") -> dict:
    level, message = ISSUES[code]
    return {"code": code, "level": level, "message": message, "source": source}


def _blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return not value
    return not str(value).strip()


def _letters_of(answer) -> list[str]:
    """答案里出现的选项字母。多选存的是 list，单选存的是 str。"""
    if isinstance(answer, list):
        raw = "".join(str(v) for v in answer)
    else:
        raw = str(answer or "")
    return sorted({ch for ch in raw.upper() if ch in LETTERS})


def _squash(text: str) -> str:
    return "".join(str(text).split())


def faults(draft: dict) -> list[dict]:
    """纯规则体检。**零成本、确定、先跑**：这些错了不用模型看也能确定。

    只报能确证的问题。「题干读不通」这种要靠模型，不在这里瞎猜 ——
    规则层每误报一条，用户对整排提示的信任就少一分。
    """
    out: list[dict] = []
    qtype = str(draft.get("type") or "")
    stem = str(draft.get("question") or "").strip()
    options = [str(o).strip() for o in (draft.get("options") or []) if str(o).strip()]
    answer = draft.get("answer")

    if _blank(answer):
        out.append(_issue("NO_ANSWER"))
        # 没答案的题不必再报「选项不全」：先让人把答案补上，其余问题会跟着重算
    elif qtype in ("single", "multiple") and len(options) >= 2:
        beyond = [ch for ch in _letters_of(answer) if LETTERS.index(ch) >= len(options)]
        if beyond:
            out.append(_issue("ANSWER_OUT_OF_RANGE"))

    if qtype in ("single", "multiple") and len(options) < 2:
        out.append(_issue("FEW_OPTIONS"))

    if not stem:
        out.append(_issue("NO_STEM"))
    elif len(_squash(stem)) < 4:
        out.append(_issue("SHORT_STEM"))
    elif stem[-1] not in _TERMINAL and stem[-1] in _TAIL_CUT:
        out.append(_issue("STEM_TAIL"))

    if stem and _OPTION_IN_TEXT.search(stem):
        out.append(_issue("OPTION_IN_STEM"))

    seen: set[str] = set()
    for option in options:
        key = re.sub(r"\s", "", option).lower()
        if key in seen:
            out.append(_issue("DUP_OPTION"))
            break
        seen.add(key)

    # 题干里同一句出现两遍：识别把一段读了两遍。6 字以下不算 ——「的值是。」这种短句
    # 在材料题里重复出现是正常的，误报一次就够用户烦的
    sentences = [_squash(s) for s in re.split(r"[。？！?]", stem) if len(_squash(s)) >= 6]
    if len(sentences) >= 2 and len(set(sentences)) < len(sentences):
        out.append(_issue("STEM_DUP"))
    return out


def _size(draft: dict) -> int:
    return (len(str(draft.get("question") or ""))
            + sum(len(str(o)) for o in (draft.get("options") or [])) + 24)


def batches(drafts: list[dict]) -> list[list[tuple[int, dict]]]:
    """切批。下标跟着草稿数组走 —— 题号可能重复（识别把两题读成同一个号），不能拿题号当键。"""
    out: list[list[tuple[int, dict]]] = []
    current: list[tuple[int, dict]] = []
    size = 0
    for index, draft in enumerate(drafts or []):
        need = _size(draft)
        if current and (len(current) >= BATCH_QUESTIONS or size + need > BATCH_CHARS):
            out.append(current)
            current, size = [], 0
        current.append((index, draft))
        size += need
    if current:
        out.append(current)
    return out


def _render(batch: list[tuple[int, dict]]) -> str:
    parts: list[str] = []
    for index, draft in batch:
        options = list(draft.get("options") or [])
        lines = [f"[题 {index + 1}]",
                 f"题型：{TYPE_LABELS.get(str(draft.get('type')), '未定')}",
                 f"题干：{draft.get('question') or '（空）'}"]
        if options:
            lines.append("选项：" + "  ".join(
                f"{LETTERS[i]}. {o}" for i, o in enumerate(options) if i < len(LETTERS)))
        answer = draft.get("answer")
        if _blank(answer):
            lines.append("答案：（没认到）")
        elif isinstance(answer, list):
            lines.append("答案：" + "".join(str(v) for v in answer))
        else:
            lines.append(f"答案：{answer}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _template() -> str:
    return (app_path("prompts") / "exam_audit.md").read_text(encoding="utf-8")


def messages(batch: list[tuple[int, dict]]) -> list[dict]:
    body = (
        f"{_template()}\n\n"
        "—— 题目开始 ——\n"
        f"{_render(batch)}\n"
        "—— 题目结束 ——\n\n"
        "现在只输出那个 JSON 对象。"
    )
    return [{"role": "user", "content": body}]


def _check_fix(fix: str, origin: str) -> tuple[str | None, str]:
    """模型给的题干改法能不能用。返回 `(能用的改法, 不能用时的原因)`。

    三道守卫各自挡一类事故，缺一不可：

    1. **数字串必须一模一样** —— 识别错的是形近字（己/已、0/O），不该动数字。
       数字一变（`3**2//2` → `3**3//2`），答案立刻不对，而用户看不出来。
    2. **编辑距离 ≤ 55%** —— 挡「顺手换一句话」：同长度的另一句话也能过数字关。
    3. **不许带题号前缀** —— 挡「把下一题并进来」：那会让第 5 题吞掉第 6 题。
    """
    if not _squash(origin):
        return None, "题干是空的，没有可比的基准"
    if re.match(r"^\s*\d{1,3}\s*[.、．]", fix):
        return None, "改法里带了题号"
    if re.findall(r"\d+", fix) != re.findall(r"\d+", origin):
        return None, "改法动了数字"
    if len(fix) > len(origin) * MAX_FIX_RATIO + MIN_FIX_BUDGET:
        return None, "改法比原文长出太多"
    if _squash(fix) == _squash(origin):
        return None, "改了等于没改"
    limit = max(12, int(len(_squash(origin)) * MAX_EDIT_RATIO))
    if _levenshtein(_squash(origin), _squash(fix)) > limit:
        return None, "改法与原文差得太远"
    return fix, ""


def verify(raw, batch: list[tuple[int, dict]]) -> tuple[list[dict], list[dict]]:
    """校验模型报的问题，返回 `(收下的, 丢掉的)`。

    丢掉的两种粒度要分开记（`scope`）：`issue` 是整条不成立（题号越界、类型不认识），
    `fix` 是问题成立但改法不能用 —— 后一种**问题照报**，只是不给「用这条」按钮。
    """
    by_index = {index: draft for index, draft in batch}
    accepted: list[dict] = []
    dropped: list[dict] = []
    seen: set[tuple[int, str]] = set()

    for item in raw or []:
        if not isinstance(item, dict):
            dropped.append({"index": None, "scope": "issue", "why": "格式不对"})
            continue
        try:
            number = int(item.get("index"))
        except (TypeError, ValueError):
            dropped.append({"index": None, "scope": "issue", "why": "没有题号"})
            continue
        index = number - 1
        if index not in by_index:
            dropped.append({"index": number, "scope": "issue", "why": "题号不在这一批里"})
            continue
        code = str(item.get("code") or "").strip().upper()
        if code not in MODEL_CODES:
            dropped.append({"index": number, "scope": "issue", "why": f"不认识的问题类型 {code or '（空）'}"})
            continue
        if (index, code) in seen:
            # 同一题同一种问题报两条：界面上会出现两条一模一样的提示
            dropped.append({"index": number, "scope": "issue", "why": "同一题同一种问题给了两条"})
            continue
        seen.add((index, code))

        issue = _issue(code, source="model")
        issue["index"] = index
        note = str(item.get("note") or "").strip()
        if note and len(note) <= MAX_NOTE and "答案" not in note:
            issue["message"] = f"{issue['message']}（{note}）"
        issue["fix"] = None

        fix = item.get("fix")
        if isinstance(fix, str) and fix.strip():
            usable, why = _check_fix(fix.strip(), str(by_index[index].get("question") or ""))
            if usable:
                issue["fix"] = usable
            else:
                # 问题成立、改法不成立：问题留着，改法丢掉并说明原因
                dropped.append({"index": number, "scope": "fix", "why": why})
        accepted.append(issue)

    accepted.sort(key=lambda it: (it["index"], 0 if it["level"] == "error" else 1, it["code"]))
    return accepted, dropped


def audit(drafts: list[dict], *, use_llm: bool = True) -> dict:
    """整份初审。**纯计算不落库**：草稿本来就在前端，这里只是给它补一层判断。

    模型那一层的失败是**降级而不是报错**：没有 Key、超时、返回不合法，
    规则体检的结果照常返回。理由与 `parse` 一致 —— 少一层判断总比整份导不进来好。
    """
    drafts = list(drafts or [])
    rule_hits: list[dict] = []
    for index, draft in enumerate(drafts):
        for fault in faults(draft):
            rule_hits.append({"index": index, **fault, "fix": None})

    groups = batches(drafts) if use_llm else []
    model, failed, dropped = ("off" if not use_llm else "used"), 0, []
    model_hits: list[dict] = []
    for group in groups:
        try:
            raw = llm.chat(messages(group), agent="exam_audit", json_mode=True)
            data = llm.extract_json(raw)
        except llm.LLMError as exc:
            log.warning("初审第 %s 题起的一批放弃（%s）", group[0][0] + 1, exc.code)
            failed += 1
            continue
        except Exception as exc:            # noqa: BLE001 - 一批失败不能拖垮整份
            log.warning("初审第 %s 题起的一批异常：%s", group[0][0] + 1, type(exc).__name__)
            failed += 1
            continue
        got, lost = verify(data.get("issues"), group)
        model_hits.extend(got)
        dropped.extend(lost)

    if groups and failed == len(groups):
        model = "failed"            # 一批都没成：界面要说「这次没看成」，不能装作看过了
    elif failed:
        model = "partial"

    # 同一件事别说两遍：模型报了的，规则那条收起来
    shadowed = {(it["index"], code)
                for it in model_hits for code in SUPERSEDES.get(it["code"], ())}
    issues = [it for it in rule_hits if (it["index"], it["code"]) not in shadowed] + model_hits

    issues.sort(key=lambda it: (it["index"], 0 if it["level"] == "error" else 1, it["code"]))
    flagged = len({it["index"] for it in issues})
    missing = sum(1 for it in issues if it["code"] == "NO_ANSWER")
    log.info("初审完成：%s 题，%s 题有问题，模型 %s（%s/%s 批失败）",
             len(drafts), flagged, model, failed, len(groups))
    return {
        "issues": issues,
        "stats": {
            "questions": len(drafts),
            "flagged": flagged,
            "missing_answer": missing,
            "model": model,
            "blocks": len(groups),
            "failed": failed,
            "dropped": len(dropped),
            "suggestions": sum(1 for it in issues if it.get("fix")),
        },
        "dropped": dropped,
    }
