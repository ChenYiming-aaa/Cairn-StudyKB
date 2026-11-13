"""docx 抽取（T9.7）：python-docx 取结构，mammoth 转 HTML 供原文页签用。

**两套读取不是重复劳动**：python-docx 给的是可检索的纯文本（进 `raw_content`），
mammoth 给的是"长得像原文"的 HTML（T9.10 的原文页签）。只留一个都不够 ——
HTML 里塞满 `<p>` 标签会让切块和关键词命中变差，纯文本又没法在原文页签里看版式。

**顺序必须按 body 走**：`document.paragraphs` 与 `document.tables` 是两个独立列表，
分开取会把所有表格堆到正文末尾（讲义里"见表 3"指向前文的表，一挪就对不上）。
所以按 `document.element.body` 的子元素顺序遍历。

**图片一律丢掉，两张网都不漏**：mammoth 默认把图转成 `data:image/png;base64,...`，
一份带图讲义能到几十 MB；这里在转换回调里直接不出 `<img>`，
再用 `renderer.sanitize` 过一遍白名单（`img` 本来就不在白名单里）兜底。
"""
from __future__ import annotations

import io
from pathlib import Path

import mammoth
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services import renderer
from app.services.extractors.base import ExtractedDoc, Extractor, ExtractError, PageText, \
    md_table, tidy

MAX_HEADING = 6


class DocxExtractor(Extractor):
    ext = "docx"

    def extract(self, path: Path, original_name: str = "") -> ExtractedDoc:
        try:
            document = Document(str(path))
        except Exception as exc:                       # noqa: BLE001
            # 加密的、只改了后缀的 .doc、半截下载都会走到这里
            raise ExtractError(
                "EXTRACT_FAILED", "这个 Word 文件打不开，可能已损坏或是旧版 .doc 改的后缀",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        lines: list[str] = []
        headings = tables = 0
        for block in _iter_blocks(document):
            if isinstance(block, Table):
                rows = [[cell.text for cell in row.cells] for row in block.rows]
                table = md_table(rows)
                if table:
                    lines.append(table)
                    tables += 1
                continue
            text = block.text.strip()
            if not text:
                continue
            level = _heading_level(block)
            if level:
                headings += 1
                lines.append("#" * level + " " + text)
            else:
                prefix = _list_prefix(block)
                lines.append(prefix + text)

        text = tidy("\n".join(lines))
        html = _to_html(path)

        props = document.core_properties
        meta = {
            "title": (props.title or "").strip(),
            "author": (props.author or "").strip(),
            "paragraphs": len(document.paragraphs),
            "tables": tables,
            "headings": headings,
            "images": len(document.inline_shapes),
            "html_chars": len(html),
        }
        page = PageText(page_no=1, text=text, html=html)
        return ExtractedDoc(text=text, pages=[page], page_count=1, meta=meta)


def _iter_blocks(document):
    """按 body 顺序产出 Paragraph / Table（python-docx 没有现成接口）。"""
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _heading_level(paragraph: Paragraph) -> int:
    """标题层级。中文版 Word 的样式名是「标题 1」，英文版是「Heading 1」，都要认。"""
    style = paragraph.style
    for name in (getattr(style, "name", "") or "", getattr(style, "style_id", "") or ""):
        digits = "".join(ch for ch in name if ch.isdigit())
        lowered = name.lower()
        if digits and ("heading" in lowered or "标题" in name):
            return min(int(digits), MAX_HEADING)
    return 0


def _list_prefix(paragraph: Paragraph) -> str:
    """列表前缀。编号列表统一写 `1. `（Markdown 会自己递增），项目符号写 `- `。"""
    name = (getattr(paragraph.style, "name", "") or "").lower()
    if "list number" in name:
        return "1. "
    if "list" in name or "列表" in name:
        return "- "
    # 样式没取到但段落带 numPr：也是列表（复制粘贴来的段落常见）
    ppr = paragraph._p.pPr                                    # noqa: SLF001
    if ppr is not None and ppr.numPr is not None:
        return "- "
    return ""


def _to_html(path: Path) -> str:
    """mammoth → HTML → 白名单净化。图在转换阶段就丢掉，不生成 base64。"""
    try:
        with path.open("rb") as fh:
            result = mammoth.convert_to_html(io.BytesIO(fh.read()), convert_image=_drop_image)
    except Exception:                                          # noqa: BLE001
        # HTML 只是原文页签的"锦上添花"，转不出来不该让整份抽取失败
        return ""
    return renderer.sanitize(result.value)


def _drop_image(_image) -> list:
    """mammoth 的图片回调：返回空列表 = 这个位置什么都不输出（不出 `<img>`）。"""
    return []
