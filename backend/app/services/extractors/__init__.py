"""抽取适配器注册表（T9.7）：按扩展名分派，把文件读成 `ExtractedDoc`。

四个适配器**懒加载**：`openpyxl` / `python-pptx` / `mammoth` 只在真遇到那种格式时
才 import。它们加起来约 15 MB 常驻，而后端启动路径上 `ingest_file` 会 import 本包 ——
不懒加载就等于每次冷启动都替不用的格式付账。

调用方只有 `services/ingest_file.py`：它按扩展名决定走识别（PDF/图片）还是抽取（这里），
两条链路最后汇到同一个 `_finish()`，共用「整份齐了才覆盖正文」那条不变量。
"""
from __future__ import annotations

from pathlib import Path

from app.services.extractors.base import Asset, ExtractedDoc, Extractor, ExtractError, PageText, \
    join_pages

# 走抽取的格式。加一种格式要同时改三处：这里、`files.ALLOWED_EXT`、适配器本身。
EXTRACT_EXT = {"docx", "pptx", "xlsx", "txt", "md"}

__all__ = [
    "EXTRACT_EXT", "Asset", "ExtractedDoc", "Extractor", "ExtractError", "PageText",
    "for_ext", "extract",
]


def for_ext(ext: str) -> Extractor | None:
    """扩展名 → 适配器实例；不走抽取的格式返回 None（不是抛错）。"""
    key = (ext or "").lower().lstrip(".")
    if key not in EXTRACT_EXT:
        return None
    if key == "docx":
        from app.services.extractors.docx import DocxExtractor
        return DocxExtractor()
    if key == "pptx":
        from app.services.extractors.pptx import PptxExtractor
        return PptxExtractor()
    if key == "xlsx":
        from app.services.extractors.xlsx import XlsxExtractor
        return XlsxExtractor()
    from app.services.extractors.plain import PlainExtractor
    return PlainExtractor(key)


def extract(path: Path, ext: str, original_name: str = "", asset_url=None) -> ExtractedDoc:
    """分派 + 归一。归一在这里做一次，适配器就不必各自保证页码连续。"""
    adapter = for_ext(ext)
    if adapter is None:
        raise ExtractError("EXTRACT_FAILED", f"暂不支持从 .{ext} 里读字")
    doc = adapter.extract(path, original_name=original_name, asset_url=asset_url)

    pages = [p for p in doc.pages]
    if not pages:
        raise ExtractError("EXTRACT_EMPTY", "这个文件里没有可读的内容")
    for index, page in enumerate(pages, start=1):
        page.page_no = index
    if not doc.text.strip():
        doc.text = join_pages(pages)
    doc.page_count = len(pages)
    return doc
