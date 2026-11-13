"""试卷解析（T10.2）：逐页文字 → 题目草稿。**纯计算：不建内容、不写库**。

两段式（需求 §9 / 执行计划 T10.2）：

1. **规则切分**（这里）：按题号锚点切块 → 块内抽选项 → 答案去答案页取。
   题号、选项字母、答案速查表这些「原文写得很规整」的东西一律规则做，**不交给模型**。
2. **模型补字段**（`prompt.py`）：只处理规则切不出的残局（没答案、选项被吃掉）。

三条判断写在实现里，后手别改回去：

- **答案只从答案区取，不从题干猜**。抽不到就留 `answer: null` 并在复核页标红 ——
  猜一个答案比留空伤害大得多（需求 §13 风险 7）。答案速查表的格式是 `1.B　2.D`，
  而「逐题解析」的格式是 `1.（B）解析…`，两种都要认，且以后者为准（它更具体）。
- **题型由选项数与答案形态推，不由章节标题猜**。「一、单项选择题」这种标题在真实
  卷子里经常一份文件里出现两次、或者干脆写成「选择题」；4 个选项 + 单字母答案才是事实。
- **草稿不落库**：`parse` 只读 `item_page`，任何字段都不写。上传 100 份试卷不会在
  知识库里堆出 100 个半成品（需求 §6 末尾那条）。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.db.conn import get_conn
from app.db.repo import files as file_repo
from app.db.repo import pages as page_repo
from app.errors import ApiError
from app.services.exam import clean, prompt

log = logging.getLogger(__name__)

# 答案区的入口。必须是**整行就是个标题**：卷子里「下列哪项是正确答案」这种题干
# 一旦被当成入口，后半张卷子会被整体划进答案区，题目就全没了。
ANSWER_ANCHOR = re.compile(
    r"^(?:[一二三四五六七八九十]{1,3}\s*[、.．]\s*)?"
    r"(?:客观题|主观题|客观卷)?(?:参考)?答案"
    r"(?:与解析|及解析|速查|汇总|与评分标准)?"
    r"(?:速查)?$"
)
# 答案速查：`1.B` `(1) B` `1、B`；多选写作 `1.AB`
KEY_PAIR = re.compile(r"(\d{1,3})\s*[.．、:：]\s*[(（]?\s*([A-H]{1,8})\s*[)）]?")
# 逐题解析：`1.（B）先算…`
EXPLAIN = re.compile(r"^(\d{1,3})\s*[.．、]\s*[(（]\s*([A-H]{1,8})\s*[)）]\s*(.+)$")
# 主观题答案：`1. 答案正文`（后续无题号的行算续行，代码答案常占好几行）
PLAIN_ITEM = re.compile(r"^(\d{1,3})\s*[.．、]\s*(.+)$")
SCORE_PER = re.compile(r"每小题\s*([\d.]+)\s*分")
JUDGE_TRUE = {"√", "对", "正确", "是", "T", "TRUE", "Y"}
JUDGE_FALSE = {"×", "错", "错误", "否", "F", "FALSE", "N"}

QUESTION_KINDS = ("arabic", "paren", "explicit")


@dataclass
class Block:
    """一道题在原文里的原始块。规则切分只产出它，题型/答案在 `to_draft` 里定。"""

    number: str
    raw_no: str
    page_no: int
    section: str
    score: float | None
    stem: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    material: str | None = None

    def text(self) -> str:
        return "\n".join([*self.stem, *self.options])


def load_pages(file_id: int) -> tuple[int, list[dict]]:
    """读这份文件已落库的逐页文字。没读完就 409 而不是解析出 0 题。"""
    conn = get_conn()
    try:
        file = file_repo.get(conn, file_id)
        if file is None:
            raise ApiError("FILE_NOT_FOUND", "这份原件不在库里了，重新上传一次", status=404)
        status = str(file["ocr_status"] or "")
        rows = page_repo.list_by_file(conn, file_id)
        if not rows:
            raise ApiError("FILE_NOT_READY", "这份文件还在读字，读完再导入试卷", status=409)
        if status in ("pending", "running"):
            raise ApiError("FILE_NOT_READY", "这份文件还在读字，读完再导入试卷", status=409)
        return int(file["item_id"]), [
            {"page_no": int(r["page_no"]), "text": r["text"] or "", "image": r["image_path"]}
            for r in rows
        ]
    finally:
        conn.close()


def split_answer_zone(pages: list[dict]) -> tuple[list[dict], list[list[str]]]:
    """把页流切成「题目区（按页）」与「答案区（按页的行）」。

    答案区从第一个命中的锚点行开始，**一直到文件末尾** —— 答案通常在最后几页。
    答案区**不做合并、不做标点归一**（代码答案被合并就毁了），但**要清页眉页脚**：
    主观题答案常跨页，页眉被当成答案的一行混进代码里，用户看到的是一段认错的代码。
    """
    question_pages: list[dict] = []
    answer_pages: list[list[str]] = []
    in_answers = False
    for page in pages:
        lines = clean.split_pages(page["text"])
        kept: list[str] = []
        zone: list[str] = []
        for line in lines:
            if not in_answers and ANSWER_ANCHOR.match(clean._squeeze(line)):
                in_answers = True
            if in_answers:
                zone.append(line)
            else:
                kept.append(line)
        if kept:
            question_pages.append({"page_no": page["page_no"], "lines": kept})
        if zone:
            answer_pages.append(zone)
    return question_pages, clean.drop_headers(answer_pages)


def read_answers(lines: list[str]) -> tuple[dict, dict, dict]:
    """答案区 → (答案, 解析, 主观题答案)。三张表都以题号（字符串）为键。"""
    answers: dict[str, str] = {}
    explanations: dict[str, str] = {}
    subjective: dict[str, str] = {}
    last: str | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        hit = EXPLAIN.match(line)
        if hit:
            answers[hit.group(1)] = hit.group(2)          # 逐题解析比速查表更可信
            explanations[hit.group(1)] = hit.group(3).strip()
            last = None
            continue
        pairs = KEY_PAIR.findall(line)
        if pairs and (len(pairs) > 1 or len(line) < 40):
            for number, letters in pairs:
                answers.setdefault(number, letters)
            last = None
            continue
        plain = PLAIN_ITEM.match(line)
        if plain:
            subjective[plain.group(1)] = plain.group(2).strip()
            last = plain.group(1)
            continue
        if last:
            subjective[last] = f"{subjective[last]}\n{line}"   # 代码答案的续行
    return answers, explanations, subjective


def split_blocks(pages: list[dict]) -> list[Block]:
    """题目区 → 按题号切块。大题标题（`一、`）只当章节与分值来源，不算一道题。

    **题号必须连续**才算新题（`value == 上一题 + 1`，换了章节则允许重新从 1 开始）。
    这条不是洁癖：卷面折行经常把「画笔宽 2、颜色为蓝色」这种内容甩到行首，
    只认「行首是数字」会平白多出一道 2 号题，还会把原题的尾巴切走一半。
    折行**只会往回或与当前题同号**（`2、` 出现在第 25 题正文里），所以「比当前题号还小」
    才判折行；一个**向前跳号**（21 之后直接 23，因为 22 那行没认出来）仍然是新题 ——
    那是识别漏行，不该把后面两道题并进前一道。
    """
    blocks: list[Block] = []
    section = ""
    prev_section = ""
    prev_num: int | None = None
    score: float | None = None
    material: list[str] = []
    cur: Block | None = None

    for page in pages:
        for line in page["lines"]:
            num = clean.normalize_number(line)
            if num and num["kind"] == "cjk":
                section = line.strip()
                hit = SCORE_PER.search(section)
                score = float(hit.group(1)) if hit else None
                cur, material, prev_num = None, [], None
                prev_section = section
                continue
            if num and num["kind"] in QUESTION_KINDS:
                value = int(num["num"])
                jumped = prev_num is not None and value != prev_num + 1
                if cur is not None and section == prev_section and jumped and value <= prev_num:
                    cur.stem.append(line)       # 折行：原样接回，保住行首那几个字
                    continue
                cur = Block(number=num["num"], raw_no=num["raw"], page_no=page["page_no"],
                            section=section, score=score, stem=[num["rest"]],
                            material=clean.join_lines(material) or None)
                blocks.append(cur)
                material, prev_num = [], value
                continue
            if cur is None:
                if section:                     # 章节下的材料；卷头的注意事项（无章节）丢掉
                    material.append(line)
                continue
            if clean.is_option_line(line):
                cur.options.append(line)
            elif cur.options:                   # 选项被折行：接回最后一个选项
                cur.options[-1] = f"{cur.options[-1]} {line.strip()}"
            else:
                cur.stem.append(line)
    return blocks


def _type_of(options: list[str], answer) -> str:
    if isinstance(answer, list):
        return "multiple"
    if isinstance(answer, str) and len(answer.strip()) > 1 and answer.strip().isalpha():
        return "multiple"
    if len(options) < 2:
        return "short"
    if isinstance(answer, str) and len(options) == 2 and answer.strip().upper() in (
        JUDGE_TRUE | JUDGE_FALSE | {"正确", "错误"}
    ):
        return "boolean"
    return "single"


def _answer_of(qtype: str, raw: str | None):
    """答案归一：单选留一个字母、多选给数组、判断给布尔、其余留文本。"""
    if raw is None:
        return None
    text = raw.strip()
    if qtype == "boolean":
        upper = text.upper()
        if upper in JUDGE_TRUE:
            return True
        if upper in JUDGE_FALSE:
            return False
        return None
    if qtype == "multiple":
        return sorted({ch for ch in text.upper() if ch in prompt.LETTERS})
    if qtype == "single":
        letters = [ch for ch in text.upper() if ch in prompt.LETTERS]
        return letters[0] if len(letters) == 1 else (letters[0] if letters else None)
    return text or None


def to_draft(block: Block, answers: dict, explanations: dict, subjective: dict) -> dict:
    options, complete = clean.align_options(block.options, expected=4)
    raw_answer = answers.get(block.number) or subjective.get(block.number)
    qtype = _type_of(options, raw_answer)
    answer = _answer_of(qtype, raw_answer)
    if qtype == "short":
        # 主观题的答案在「参考答案」区，是多行代码/文字，不能过字母归一
        answer = (subjective.get(block.number) or answers.get(block.number) or None)

    question = clean.join_lines(block.stem)
    confidence = 0.55
    if len(options) >= 2:
        confidence += 0.25
        if complete:
            confidence += 0.1
    if answer is not None:
        confidence += 0.1
    return {
        "number": block.number,
        "raw_no": block.raw_no,
        "type": qtype,
        "question": question,
        "options": options,
        "options_incomplete": bool(options) and not complete,
        "answer": answer,
        "explanation": explanations.get(block.number, ""),
        "score": block.score,
        "material": block.material,
        "group": block.section or None,
        "page_no": block.page_no,
        "confidence": round(min(confidence, 1.0), 2),
    }


def parse(file_id: int, *, use_llm: bool = True) -> dict:
    """解析入口。返回 `{"item_id", "drafts", "stats"}`；0 题抛 `EXAM_NO_QUESTIONS`。"""
    item_id, pages = load_pages(file_id)
    question_pages, answer_pages = split_answer_zone(pages)
    answers, explanations, subjective = read_answers(
        [line for zone in answer_pages for line in zone])

    cleaned = clean.clean_pages([page["lines"] for page in question_pages])
    # 一次喂完整份：章节与「上一题」的上下文要跨页延续，逐页调用会把每页都当成新卷子
    blocks = split_blocks([
        {"page_no": page["page_no"], "lines": lines}
        for page, lines in zip(question_pages, cleaned)
    ])

    drafts = [to_draft(b, answers, explanations, subjective) for b in blocks]
    numbers = [d["number"] for d in drafts]
    conflicts = len(numbers) - len(set(numbers))
    if not drafts:
        raise ApiError("EXAM_NO_QUESTIONS",
                       "这份文件里没找到题目，换一份或手动录入", status=422)

    refined = 0
    if use_llm:
        need = [(d, b.text()) for d, b in zip(drafts, blocks) if d["answer"] is None]
        if need:
            try:
                refined = prompt.refine(need)
            except Exception as exc:        # noqa: BLE001 - 补字段失败不影响规则结果
                log.warning("补字段整体失败（%s），按规则结果返回", type(exc).__name__)

    with_answer = sum(1 for d in drafts if d["answer"] is not None)
    by_type: dict[str, int] = {}
    for draft in drafts:
        by_type[draft["type"]] = by_type.get(draft["type"], 0) + 1
    stats = {
        "item_id": item_id,
        "pages": len(pages),
        "lines": sum(len(page["lines"]) for page in question_pages),
        "questions": len(drafts),
        "with_answer": with_answer,
        "answer_rate": round(with_answer / len(drafts), 3),
        "incomplete_options": sum(1 for d in drafts if d["options_incomplete"]),
        "missing_answer": [d["number"] for d in drafts if d["answer"] is None],
        "by_type": by_type,
        "number_conflicts": conflicts,
        "model_refined": refined,
    }
    return {"item_id": item_id, "drafts": drafts, "stats": stats}
