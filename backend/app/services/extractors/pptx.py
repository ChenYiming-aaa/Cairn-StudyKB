"""pptx 抽取（T9.7）：一页幻灯片 = 一页文字。

**不做版式还原**：坐标、主题色、动画都不进 `raw_content` —— 检索要的是"讲了什么"，
不是"框在哪"。要还原版式得上 LibreOffice 渲染成图，那是另一个量级的依赖。
所以每页只出三样：标题 / 正文要点 / 演讲者备注。

**备注是宝藏**：讲义的备注里常写"这里要强调 XX"，是整理笔记时最值钱的一句话，
而且用户肉眼在幻灯片上看不到它 —— 不抽就等于丢了。
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from app.services.extractors.base import ExtractedDoc, Extractor, ExtractError, PageText, \
    md_table, tidy


class PptxExtractor(Extractor):
    ext = "pptx"

    def extract(self, path: Path, original_name: str = "") -> ExtractedDoc:
        try:
            pres = Presentation(str(path))
        except Exception as exc:                       # noqa: BLE001
            raise ExtractError(
                "EXTRACT_FAILED", "这个 PPT 文件打不开，可能已损坏或是旧版 .ppt 改的后缀",
                f"{type(exc).__name__}: {exc}",
            ) from exc

        pages: list[PageText] = []
        images = 0
        for index, slide in enumerate(pres.slides, start=1):
            blocks, shots = _slide_blocks(slide)
            images += shots
            pages.append(PageText(page_no=index, text=tidy("\n".join(blocks))))

        meta = {
            "slides": len(pages),
            "images": images,
            "title": (pres.core_properties.title or "").strip(),
            "author": (pres.core_properties.author or "").strip(),
            "empty_pages": sum(1 for p in pages if not p.text.strip()),
        }
        text = tidy("\n\n".join(p.text for p in pages if p.text.strip()))
        return ExtractedDoc(text=text, pages=pages, page_count=len(pages), meta=meta)


def _slide_blocks(slide) -> tuple[list[str], int]:
    """一页的全部文字，顺序按 shape 树的自然顺序（标题通常第一个）。返回（文本行, 图片数）。"""
    blocks: list[str] = []
    images = 0
    for shape in _iter_shapes(slide.shapes):
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            images += 1
            continue
        if shape.has_table:
            rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
            table = md_table(rows)
            if table:
                blocks.append(table)
            continue
        if not shape.has_text_frame:
            continue
        for paragraph in shape.text_frame.paragraphs:
            line = "".join(run.text for run in paragraph.runs).strip()
            if not line:
                continue
            # 缩进级别带成 Markdown 列表层级：PPT 的要点层级就是它的结构
            level = min(int(getattr(paragraph, "level", 0) or 0), 3)
            blocks.append("  " * level + "- " + line if level else line)

    notes = _notes_text(slide)
    if notes:
        blocks.append("备注：" + notes)
    return blocks, images


def _iter_shapes(shapes):
    """组合形状里的文字也在 shape 树里，递归拿全（不然一组要点整块丢掉）。"""
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _iter_shapes(shape.shapes)


def _notes_text(slide) -> str:
    try:
        frame = slide.notes_slide.notes_text_frame
    except Exception:                                  # noqa: BLE001
        return ""
    if frame is None:
        return ""
    return tidy("\n".join(p.text for p in frame.paragraphs if p.text.strip()))
