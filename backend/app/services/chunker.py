"""切块：纯函数，不带 IO。M1 §6.4。

按空行分段 → 段内按 。！？；\\n 切句 → 累加到 >=600 字输出一块
→ 下一块从上一块末尾回退 80 字开始（重叠）→ 单块硬上限 900 字。

raw_content 与 structured_note 共用本函数（M1 §6.10）。
"""
from __future__ import annotations

import re

MIN_CHARS = 600
HARD_MAX = 900
OVERLAP = 80

_PARA = re.compile(r"\n\s*\n")
_SENT = re.compile(r"[^。！？；\n]+[。！？；\n]?|[\n]+")
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _fragments(text: str) -> list[str]:
    """切成句子级片段，保留标点与换行，便于无损拼接。"""
    out: list[str] = []
    for para in _PARA.split(text):
        if not para.strip():
            continue
        for seg in _SENT.findall(para):
            if not seg.strip():
                continue
            # 无标点的超长段落按硬上限强制断开，避免单块超限
            if len(seg) > HARD_MAX:
                out.extend(seg[i:i + HARD_MAX] for i in range(0, len(seg), HARD_MAX))
            else:
                out.append(seg)
    return out


def _rewind(end: int, buf: list[str]) -> int:
    """回退到覆盖末尾 OVERLAP 字符的片段起点；至少前进一个片段，防死循环。"""
    total, keep = 0, 0
    for frag in reversed(buf):
        if total >= OVERLAP:
            break
        total += len(frag)
        keep += 1
    keep = min(keep, max(0, len(buf) - 1))
    return end - keep


def split(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    frags = _fragments(text)
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    i = 0
    while i < len(frags):
        frag = frags[i]
        if buf and size + len(frag) > HARD_MAX:
            chunks.append("".join(buf).strip())
            i = _rewind(i, buf)
            buf, size = [], 0
            continue
        buf.append(frag)
        size += len(frag)
        i += 1
        if size >= MIN_CHARS:
            chunks.append("".join(buf).strip())
            i = _rewind(i, buf)
            buf, size = [], 0
    if buf:
        chunks.append("".join(buf).strip())
    return [c for c in chunks if c]


def strip_fence(text: str) -> str:
    match = _FENCE.search(text)
    return match.group(1).strip() if match else text
