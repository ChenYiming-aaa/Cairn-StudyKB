"""chunk → 第几页（T11.2）：问答点引用，要落到那一页并标出命中段。

**为什么在服务端算**：30 页的 PDF，前端要自己定位就得先把 30 页文字全拉一遍
（30 个往返），而"哪一页包含这段字"是一次文本比对的事，库里本来就有。

**为什么不整段 `indexOf`**：chunk 是 chunker 拼回来的，不是原文的连续切片 ——
分段与换行会被规整，整段常常落空。所以按长度递减退到「够长且确实存在的前缀」，
和 `TextRawPane.findAnchor` 同一思路（那边是前端兜底，这里是主路径）。
命中位置仍然准确，只是高亮的是前一两百字，不是整段。

**比对的是 `text_reviewed or text`**：M10 的校对写的是 `text_reviewed`，
识别原文永不覆盖。拿 `text` 比会「校对完再点引用，跳不过去」——
用户看到的、以及切成 chunk 的都是校对后的文本。
"""
from __future__ import annotations

# 600 起步：chunk 一般 300–800 字，整段命中是最理想的，别一上来就砍
PREFIX_SIZES = (600, 400, 240, 160, 120, 80, 48, 24, 12)
MIN_ANCHOR = 8


def _anchor(body: str, needle: str) -> str:
    """在 body 里找一个「够长且确实存在」的锚点；找不到返回空串。"""
    if needle in body:
        return needle
    for size in PREFIX_SIZES:
        cut = needle[:size].strip()
        if len(cut) >= MIN_ANCHOR and cut in body:
            return cut
    return ""


def locate(chunk_text: str, pages: list[tuple[int, str]]) -> dict | None:
    """`pages` 是 `[(page_no, text)]`，按页序找第一处命中。

    返回 `{page_no, line_from, line_to, matched}`：行号是**该页文字按 `\\n` 切**的下标，
    与 `pages/{n}` 返回的 `text` 一致（前端就按这个下标标黄）。
    找不到返回 `None` —— 调用方当成"落不到页"，不要把整次跳转变成报错。
    """
    needle = (chunk_text or "").strip()
    if not needle:
        return None
    for page_no, text in pages:
        body = text or ""
        if not body:
            continue
        anchor = _anchor(body, needle)
        if not anchor:
            continue
        at = body.index(anchor)
        line_from = body.count("\n", 0, at)
        return {
            "page_no": int(page_no),
            "line_from": line_from,
            "line_to": line_from + anchor.count("\n"),
            "matched": anchor,
        }
    return None
