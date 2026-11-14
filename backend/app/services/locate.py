"""chunk → 第几页（T11.2）：问答点引用，要落到那一页并标出命中段。

**为什么在服务端算**：30 页的 PDF，前端要自己定位就得先把 30 页文字全拉一遍
（30 个往返），而"哪一页包含这段字"是一次文本比对的事，库里本来就有。

**比对忽略空白，行号按原文算**：chunk 是 chunker 拼回来的 —— 换行被规整成空格、
多余空白被收敛，所以**跨行的整段按原样永远比不上**（PPT 那轮才露出来：
300 字的 chunk 一定跨好几行，按原样比只能退化到十几个字的锚点，甚至落空）。
这里两边都去掉空白再比，命中位置再映射回原文本的字符偏移，最后换成行号 ——
行号是给 `pages/{n}` 的 `text` 用的，必须与原文严格对齐。

**比对的是 `text_reviewed or text`**：M10 的校对写的是 `text_reviewed`，
识别原文永不覆盖。拿 `text` 比会「校对完再点引用，跳不过去」——
用户看到的、以及切成 chunk 的都是校对后的文本。
"""
from __future__ import annotations

import re

# 600 起步：chunk 一般 300–800 字，整段命中是最理想的，别一上来就砍
PREFIX_SIZES = (600, 400, 240, 160, 120, 80, 48, 24, 12)
MIN_ANCHOR = 8
# 搜索词可以短："randint" 只有 7 个字符，但它比整段 chunk 更能说明用户想看哪一句
MIN_HINT = 4
_BLANKS = re.compile(r"[\s\u3000]+")


def _squash(text: str) -> str:
    return _BLANKS.sub("", text or "")


def _flatten(text: str) -> tuple[str, list[int]]:
    """去空白后的正文 + 每个字符在原文本里的偏移（行号靠它换算）。"""
    chars: list[str] = []
    offsets: list[int] = []
    for at, ch in enumerate(text or ""):
        if ch.isspace() or ch == "\u3000":
            continue
        chars.append(ch)
        offsets.append(at)
    return "".join(chars), offsets


def locate(chunk_text: str, pages: list[tuple[int, str]], hint: str | None = None) -> dict | None:
    """`pages` 是 `[(page_no, text)]`，按页序找第一处命中。

    返回 `{page_no, line_from, line_to, matched}`：行号是**该页文字按 `\\n` 切**的下标，
    与 `pages/{n}` 返回的 `text` 一致（前端就按这个下标标黄）。
    找不到返回 `None` —— 调用方当成"落不到页"，不要把整次跳转变成报错。

    **`hint` 先试**（搜索词 / 用户真正在找的那几个字）：一个 chunk 常常跨好几页，
    按整段起点落页会把人带到第一页，而他是在第三页那句话上点的搜索。
    hint 落不到才退回整段起点 —— 「这段字从哪一页开始」也是有用的答案，只是不够准。
    """
    for text, floor in ((hint, MIN_HINT), (chunk_text, MIN_ANCHOR)):
        needle = _squash(text)
        if len(needle) < floor:
            continue
        hit = _search(needle, pages)
        if hit:
            return hit
    return None


def _search(needle: str, pages: list[tuple[int, str]]) -> dict | None:
    for page_no, text in pages:
        body = text or ""
        if not body:
            continue
        flat, offsets = _flatten(body)
        if not flat:
            continue
        # 先试整段，再按 600/400/.../12 递减：跨页的 chunk 只有前缀落在这一页
        for size in (*PREFIX_SIZES, len(needle)):
            cut = needle[:size]
            if len(cut) < min(MIN_ANCHOR, len(needle)):
                continue
            at = flat.find(cut)
            if at < 0:
                continue
            start = offsets[at]
            end = offsets[at + len(cut) - 1]
            return {
                "page_no": int(page_no),
                "line_from": body.count("\n", 0, start),
                "line_to": body.count("\n", 0, end),
                # 按**原文**回一段：去空白后的串对不上页面文字，前端要拿它标黄
                "matched": body[start:end + 1],
            }
    return None
