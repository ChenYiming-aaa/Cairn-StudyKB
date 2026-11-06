"""繁简归一（ASR 输出后处理）。

**为什么不做在解码里**：给 whisper 加 `initial_prompt` 能把繁体压到 0，但代价是分段粒度
从 88 段掉到 28 段（同一份音频实测）。时间戳是知识库的检索线索，粒度不能丢，所以改成
「识别完再转」——文本一样，段落不动。

**为什么只转汉字段**：zhconv 整段调用会把中文引号 `「」` 规范成 `“”`（实测 #4、#35 各 4/12 处）。
那是**样式**不是繁简，用户粘的原文不该被改。按 `[\\u4e00-\\u9fff]+` 切段后只送汉字进去，
标点、英文、数字、`[mm:ss]` 全部按原样返回。

**为什么不设阈值**：在库里 11 条既有条目上实测，已经是简体的一律 0 改动（含 `乾隆`、`著名`、
`头发`、`台湾`、`只要` 这类容易误判的词，zhconv 的词表处理得对）。既然对简体是恒等变换，
就不需要「改动超过 x% 才转」这种阈值——阈值只会把 #40 那种只残留 3 个繁体字的长文漏掉。

红线：这里只处理字形，**不碰同音错字**（`搅屎棍狂潮` 被识别成 `脚使过光潮` 是声学错误，
换字形救不回来）。
"""
from __future__ import annotations

import re

import zhconv

# 连续汉字串。故意不含标点与全角符号，避免 zhconv 顺手改引号
_HAN_RUN = re.compile(r"[\u4e00-\u9fff]+")


def _diff(src: str, dst: str) -> int:
    """改动字数。转换可能改变长度（少数词组），长度差也计入。"""
    return sum(1 for a, b in zip(src, dst) if a != b) + abs(len(src) - len(dst))


def to_simplified(text: str) -> tuple[str, int]:
    """繁体 → 简体。返回 `(新文本, 改动字数)`；没有繁体时返回原对象、改动数 0。

    `改动字数 == 0` 是「这段本来就是简体/英文/纯数字」的判据，调用方可据此跳过后续处理。
    """
    if not text:
        return text, 0

    changed = 0

    def _sub(match: re.Match[str]) -> str:
        nonlocal changed
        src = match.group(0)
        dst = zhconv.convert(src, "zh-hans")
        if dst != src:
            changed += _diff(src, dst)
        return dst

    out = _HAN_RUN.sub(_sub, text)
    return (out, changed) if changed else (text, 0)
