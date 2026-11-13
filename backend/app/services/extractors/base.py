"""抽取适配器的统一返回与基类（T9.7）。

**为什么不用识别**：docx / pptx / xlsx / txt 里文字本来就是结构化的，
渲染成图再认一遍既慢（讲义页实测 15.7 秒/页）又必然带错字。能直读就直读，
识别只留给"只有像素"的 PDF 与图片。

**四个格式的统一形状**（`ExtractedDoc`）刻意与识别链路对齐：都产出
`pages: list[PageText]` + `page_count`，于是 `ingest_file._finish()` 那套
「整份齐了才覆盖正文、才重建 chunk」的不变量只写一次，两条链路共用。

**页码语义**：docx / xlsx / txt 是单页（整份算 1 页，没有真实分页概念，
硬拆成"页"只会让界面出现假页码）；pptx 一页幻灯片算一页。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PageText:
    page_no: int
    text: str
    html: str | None = None      # 只有 docx 有（原文页签用）


@dataclass
class ExtractedDoc:
    text: str                    # 全文，写进 raw_content
    pages: list[PageText]
    page_count: int
    has_text_layer: bool = True  # 非 PDF 恒 True
    meta: dict = field(default_factory=dict)


class ExtractError(Exception):
    """抽取失败。`code` 直接进任务错误码，`message` 是给用户看的一句话。"""

    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class Extractor:
    """一种格式一个子类。`ext` 是不带点的扩展名，注册表靠它分派。"""

    ext: str = ""

    def extract(self, path: Path, original_name: str = "") -> ExtractedDoc:
        raise NotImplementedError


# ── 共用的文本整形 ──────────────────────────────────────
_BLANK_LINES = re.compile(r"\n{3,}")


def tidy(text: str) -> str:
    """收敛空行、去掉首尾空白。**不动行内的空格**：中文混排里那是内容。"""
    return _BLANK_LINES.sub("\n\n", (text or "").replace("\r\n", "\n")).strip()


def join_pages(pages: list[PageText]) -> str:
    """全文按页拼。与识别链路口径一致：**不加「第 N 页」标记**。

    页码在 `item_page.page_no` 里，正文里再写一遍就是版面噪音，
    会把检索与整理带偏（T9.6 已按这条定过，别在抽取里破例）。
    """
    return tidy("\n\n".join(p.text for p in pages if (p.text or "").strip()))


def md_table(rows: list[list[str]]) -> str:
    """二维表 → Markdown 表。第一行当表头。

    `|` 与换行必须转义：单元格里带竖线的表格会把 Markdown 表拆散，
    切块后每行都变成半截（xlsx 的成绩单表尤其常见）。
    """
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    grid = [[_cell(c) for c in (r + [""] * (width - len(r)))] for r in rows]
    head, body = grid[0], grid[1:]
    lines = ["| " + " | ".join(head) + " |",
             "| " + " | ".join("---" for _ in head) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def _cell(value) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("|", "\\|")
    return text.strip()
