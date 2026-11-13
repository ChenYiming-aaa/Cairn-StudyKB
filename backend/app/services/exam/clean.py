"""规则清洗层（T10.1）：页眉页脚、断行、全半角、题号、选项对齐。

**五个纯函数，不碰数据库、不调模型、不读文件**——这样 `verify_m10.py` 的 `§clean`
可以拿字面量逐条钉死，改坏了立刻红。清洗层的每一个误改都会直接变成「题干少半句」，
比识别错字更难发现，所以每条规则都配了「不该改」的用例。

需求 §8.3 与执行计划 T10.1 是这五个函数的出处。两处**实现口径**在这里定死：

1. **页眉靠「重复」判，不靠坐标**。`item_page.text` 只存了行序，y 坐标在那一步就丢了
   （`ocr_layout.order_lines` 只出文本）。所以位置信息用「每页首/尾各 N 行」代理，
   并且**两条同时满足才删**：既在某页的页边、又在 ≥20% 的页上重复出现。
   只按重复删会误删正文里反复出现的「答案」；只按位置删会误删每页末尾的题干续行。
2. **页码单独一条规则**：`第 3 页` / `— 3 —` / `3/7` 每页都不一样，重复率判不出来。
   只认这几种明确的形式，且只在页边生效——正文里孤立的一行「3」可能是被拆开的题号。
"""
from __future__ import annotations

import math
import re

# ── 全角/半角 ─────────────────────────────────────────────
# 只换标点，不换字母数字：`ＡＢＣ` 在选项里另有专门规则（align_options 只改行首那个字母），
# 一次把所有全角字母换成半角会把正文里的全角引号、单位符号一起搅乱。
_PUNCT_TO_FULL = {",": "，", "?": "？", ":": "：", ";": "；", "(": "（", ")": "）"}
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
# 每页边上的行数（代理 y 坐标：页眉在首行，页码在末行；双栏页首尾各有 1–2 行页边内容）
EDGE_LINES = 2

# ── 页眉 / 页码 ───────────────────────────────────────────
PAGE_NO = re.compile(
    r"^\s*(?:"
    r"第\s*\d{1,4}\s*页(?:\s*[，,/／]?\s*共\s*\d{1,4}\s*页)?"
    r"|[-—–]{1,2}\s*\d{1,4}\s*[-—–]{1,2}"
    r"|\d{1,4}\s*[/／]\s*\d{1,4}"
    r"|\d{1,4}"
    r")\s*$"
)
_WS = re.compile(r"\s+")

# ── 题号 ─────────────────────────────────────────────────
_CJK_NUM = "一二三四五六七八九十"
# 顺序有讲究：显式「第N题」与括号式比裸数字更具体，先匹配前者
_NUM_PATTERNS = (
    ("explicit", re.compile(r"^\s*第\s*(\d{1,3})\s*题\s*[.．、:：)）]?\s*")),
    ("paren", re.compile(r"^\s*[(（]\s*(\d{1,3})\s*[)）]\s*")),
    # `(?!\d)` 挡住小数与版本号：「3.14」「1.5 倍」不是题号
    ("arabic", re.compile(r"^\s*(\d{1,3})\s*[.．、)）](?!\d)\s*")),
    ("cjk", re.compile(r"^\s*([%s]{1,3})\s*[、.．]\s*" % _CJK_NUM)),
)

# ── 选项 ─────────────────────────────────────────────────
_FW_LETTERS = {chr(0xFF21 + i): chr(0x41 + i) for i in range(26)}
_FW_LETTERS.update({chr(0xFF41 + i): chr(0x61 + i) for i in range(26)})
_LETTER = "A-HＡ-Ｈa-hａ-ｈ"
# 行首选项字母：`A.` `A、` `A)` `(A)` `（Ａ）` `A：`；**必须带分隔符**，
# 否则正文里的英文单词首字母（"Apple 是一种…"）会被当成选项
_OPTION_HEAD = re.compile(r"^\s*(?:[(（]\s*([%s])\s*[)）]|([%s])\s*[.．、,，)）:：])\s*" % (_LETTER, _LETTER))
# 一行里并排多个选项（真实卷子常见）：两个以上空格 + 字母标记处切开
_OPTION_SPLIT = re.compile(r"\s{2,}(?=[A-HＡ-Ｈ]\s*[.．、)）]\s*\S)")

_BULLET = re.compile(r"^\s*(?:[•·▪◦●○*]\s|[①-⑳]|[(（]\d{1,2}[)）])")
# 行尾是这些字符时说明这一句说完了，不再与下一行合并
TERMINAL = "。！？!?；;：:．.…\"'”’）)】」』》>"
_HEADING = re.compile(
    r"^\s*(?:第\s*[%s百零\d]{1,4}\s*[章节部分篇讲]|\d+(?:\.\d+)+\s|[%s]{1,3}\s*、)"
    % (_CJK_NUM, _CJK_NUM)
)


def _squeeze(text: str) -> str:
    return _WS.sub("", text or "")


def normalize_width(text: str) -> str:
    """中文语境下把 ASCII 标点归一到全角；**英文段落与代码行零改动**。

    判定按行：含中文的字符占比 ≥15% 才算「中文语境」。这一条同时挡住了两类误改 ——
    英文阅读理解段（`He said, "yes."`）和代码块（`print(1, 2)`）。
    数字里的 `.` 与 `,` 不动（`3.14` / `1,000`），紧跟字母数字的括号也不动（`round(2.5)`）。
    """
    if not text:
        return text
    solid = [ch for ch in text if not ch.isspace()]
    if not solid:
        return text
    ratio = sum(1 for ch in solid if CJK.match(ch)) / len(solid)
    if ratio < 0.15:
        return text

    out: list[str] = []
    paren: list[bool] = []            # 括号成对决定：`round(2.5)` 两头都得留在半角
    for i, ch in enumerate(text):
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if ch == ".":
            # 小数点、版本号、英文缩写（e.g.）都保持原样
            keep = (prev.isascii() and prev.isalnum()) or (nxt.isascii() and nxt.isalnum())
            out.append("." if keep else "。")
        elif ch == ",":
            out.append("," if (prev.isdigit() and nxt.isdigit()) else "，")
        elif ch == "(":
            keep = (prev.isascii() and prev.isalnum()) or (nxt.isascii() and nxt.isalpha())
            paren.append(keep)
            out.append("(" if keep else "（")
        elif ch == ")":
            keep = paren.pop() if paren else (prev.isascii() and prev.isalnum())
            out.append(")" if keep else "）")
        else:
            out.append(_PUNCT_TO_FULL.get(ch, ch))
    return "".join(out)


def normalize_number(line: str) -> dict | None:
    """行首题号 → 可解析记号；**不是题号返回 None**。

    返回 `{"num", "kind", "raw", "rest"}`：`num` 是纯数字（中文数字原样），
    `kind` 区分 `arabic`（1.）/ `paren`（(1)）/ `explicit`（第1题）/ `cjk`（一、），
    `raw` 是原写法（留给草稿的 `raw_no`，界面上要能照着原卷看），`rest` 是去掉题号后的正文。

    `cjk` 是**大题号**（一、二、三），调用方要拿它当章节而不是题目 —— 这条区分是
    「20 题全可解析」与「把大题标题也当成一道题」的分界线。
    """
    if not line:
        return None
    for kind, pattern in _NUM_PATTERNS:
        hit = pattern.match(line)
        if hit:
            return {"num": hit.group(1), "kind": kind,
                    "raw": line[:hit.end()].strip(), "rest": line[hit.end():].strip()}
    return None


def _letter_of(line: str) -> tuple[str, str] | None:
    """行首选项字母 → (字母, 裸文本)；不是选项行返回 None。"""
    hit = _OPTION_HEAD.match(line)
    if not hit:
        return None
    letter = hit.group(1) or hit.group(2)
    return _FW_LETTERS.get(letter, letter).upper(), line[hit.end():].strip()


def align_options(lines: list[str], *, expected: int = 4) -> tuple[list[str], bool]:
    """选项归一：`A` `A.` `A、` `Ａ` → 一律认作 A，返回**裸文本**（字母交给界面画，同 M4 口径）。

    返回 `(按字母排好的裸文本, 是否不全)`。`expected` 由调用方给：单选/多选 4 个，
    判断题 2 个。行内并排的多个选项会先切开（`A. list  B. dict  C. tuple  D. set`），
    否则真实卷子里四个选项挤一行时只会认出一个。

    **不全要标出来而不是静默补齐**：少一个选项的题，答案比对必然错，
    而「补一个空选项」会让用户以为题是完整的（需求 §8.3）。
    """
    flat: list[str] = []
    for line in lines:
        flat.extend(part for part in _OPTION_SPLIT.split(line or "") if part.strip())

    found: dict[str, str] = {}
    loose: list[str] = []
    for line in flat:
        pair = _letter_of(line)
        if pair is None:
            loose.append(line.strip())
            continue
        letter, text = pair
        if letter in found:          # 重复字母：后一个当续行接上
            found[letter] = f"{found[letter]} {text}".strip()
        else:
            found[letter] = text

    if not found:
        # 没有字母标记（判断题写成「正确 / 错误」）：原样返回，让其按文本选项处理
        return [t for t in loose if t], len(loose) >= 2

    letters = sorted(found)
    want = [chr(ord("A") + i) for i in range(len(letters))]
    complete = letters == want[:len(letters)] and len(letters) == expected
    return [found[letter] for letter in letters], not complete


def _is_page_no(line: str) -> bool:
    return bool(PAGE_NO.match(line or ""))


def drop_headers(
    pages: list[list[str]],
    *,
    edge_lines: int = EDGE_LINES,
    ratio: float = 0.2,
    max_len: int = 40,
) -> list[list[str]]:
    """删页眉页脚：**页边 + 重复**两条同时满足的行，以及明确形态的页码。

    只删页边（每页前 `edge_lines` / 后 `edge_lines` 行）里的候选：
    同一句「本页要点」在正文中间反复出现是内容，不是页眉。
    页数不足 3 页时没有「重复」可言，只清页码。
    """
    if not pages:
        return []

    total = len(pages)
    threshold = max(2, math.ceil(total * ratio))
    counts: dict[str, int] = {}
    for lines in pages:
        # 同一页里页眉重复出现只算一次：短页（正文只有两行）首尾会重叠
        for key in {_squeeze(line) for line in _edge_slices(lines, edge_lines)}:
            if key and len(key) <= max_len:
                counts[key] = counts.get(key, 0) + 1
    repeated = {key for key, n in counts.items() if n >= threshold} if total >= 3 else set()

    out: list[list[str]] = []
    for lines in pages:
        keep: list[str] = []
        head = min(edge_lines, len(lines))
        tail_start = max(head, len(lines) - edge_lines)
        for i, line in enumerate(lines):
            edge = i < head or i >= tail_start
            if edge and (_is_page_no(line) or (repeated and _squeeze(line) in repeated)):
                continue
            keep.append(line)
        out.append(keep)
    return out


def _edge_slices(lines: list[str], edge_lines: int) -> list[str]:
    head = min(edge_lines, len(lines))
    tail = lines[max(head, len(lines) - edge_lines):]
    return list(lines[:head]) + list(tail)


def _is_heading(line: str) -> bool:
    return bool(_HEADING.match(line or ""))


def merge_broken(lines: list[str]) -> list[str]:
    """合并被行宽折断的句子：**行尾没说完 + 下一行不是新单元** 才合并。

    「新单元」= 题号 / 选项字母 / 项目符号 / 标题 —— 这四种都必须另起一行，
    否则「1. 题干…没有标点」会把下一题「2. …」一起吞掉（这是最贵的一种误合：
    两题并成一题，题号还会少一个，用户核对时才会发现）。

    中文之间不加空格；两侧都是英文/数字才补一个空格（英文阅读理解段常见）。
    """
    out: list[str] = []
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        if out and _can_merge(out[-1], line):
            out[-1] = _join(out[-1], line)
        else:
            out.append(line)
    return out


def _can_merge(prev: str, nxt: str) -> bool:
    if not prev or not nxt:
        return False
    if prev[-1] in TERMINAL:
        return False
    if normalize_number(nxt) or _OPTION_HEAD.match(nxt) or _BULLET.match(nxt):
        return False
    if _is_heading(nxt) or _is_page_no(nxt):
        return False
    return True


def _join(prev: str, nxt: str) -> str:
    if prev and nxt and prev[-1].isascii() and nxt[0].isascii() and (
        prev[-1].isalnum() or prev[-1] in ",.;:"
    ) and (nxt[0].isalnum() or nxt[0] in "\"'"):
        return f"{prev} {nxt}"
    return prev + nxt


def clean_pages(pages: list[list[str]]) -> list[list[str]]:
    """三件套的顺序在此定死：**先去页眉 → 再合断行 → 最后归标点**。

    顺序不能换：先归标点会给没说完的行补上「。」，紧接着 `merge_broken` 就认为
    「这句说完了」，断行再也合不上；先合断行再去页眉，页眉会先被合并成一大段。
    """
    dropped = drop_headers(pages)
    return [[normalize_width(line) for line in merge_broken(lines)] for lines in dropped]


def split_pages(text: str) -> list[str]:
    """一页的 `text` → 行列表。识别结果用 `\\n` 分行（`ocr_layout` 的约定）。"""
    return [line for line in (text or "").splitlines() if line.strip()]
