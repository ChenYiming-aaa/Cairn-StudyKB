"""PDF 页图渲染（T9.6）：把每一页变成一张 JPEG，交给识别组件。

**为什么必须有页图**：识别会认错，但用户没法凭空判断"这行字是不是它认错了"。
页图与文字同页配对（`item_page.image_path`）是"认错也看得出来"的唯一保障（ADR-031 / 数据契约 §6）。

四条约束：

1. **长边钳到 1600 px、不超过 300 dpi**。300 dpi 的 30 页 PDF 光是图就 100 MB+，
   识别时间也从 2.8 s/页涨到十几秒（实测，见执行计划 §8.3）。`render(scale=)` 的 scale 是
   **相对 72 dpi 的倍数**，把 150 当 scale 传会得到 150 倍图 —— 这里统一由 `_scale()` 算。
2. **JPEG q85**，不用 PNG：同样一页，PNG 3–5 倍大，且对识别没有任何好处。
3. **一次只持有一页的位图**：调用方逐页 `render()` 后立刻落盘，不把 bitmap 留在内存里
   （`with` 里拿到的是尺寸，位图出了函数就没了）。
4. **盘上路径一律相对数据目录**（`pages/<file_id>/<page_no>.jpg`），和 `item_file.stored_path`
   同一口径 —— 数据目录整体搬走还能读（ADR-031）。

图片文件（png/jpg/webp）不走这里：它本身就是要认的那张图，直接把 `item_file.stored_path`
当页图，不复制、不重编码。
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from app.config import get_settings

log = logging.getLogger(__name__)

MAX_SIDE_PX = 1600      # 长边上限
MAX_DPI = 300           # 放大上限（小页面不硬拉到 1600）
JPEG_QUALITY = 85
_DPI_BASE = 72.0        # PDFium 的坐标单位是 1/72 英寸


@dataclass
class PageImage:
    """一页渲染结果。`path` 是相对数据目录的 posix 路径。"""

    path: str
    width: int
    height: int


def root() -> Path:
    return get_settings().data_dir / "pages"


def file_dir(file_id: int) -> Path:
    return root() / str(file_id)


def rel_path(file_id: int, page_no: int) -> str:
    """盘上文件名只用页号：页号是这份原件里唯一的，中文原名一律不进路径。"""
    return f"pages/{file_id}/{page_no:04d}.jpg"


def abs_path(image_path: str) -> Path:
    return get_settings().data_dir / image_path


def page_count(pdf) -> int:
    """`len()` 在 pypdfium2 上可用，但显式包一层，调用处不必知道库的细节。"""
    return len(pdf)


def open_pdf(path: str | Path):
    """打开 PDF。调用方负责 `close()`，或者用 `closing()` 包住。"""
    return pdfium.PdfDocument(str(path))


def _scale(width_pt: float, height_pt: float) -> float:
    """长边 ≤1600 px 且 ≤300 dpi 的缩放倍数（相对 72 dpi）。

    先求"按长边钳到 1600"的倍数，再与 300/72 取小 —— 小页面（如 400 pt 宽的名片）
    不会被硬拉到 1600 px，那样只会让识别更慢、更不准。
    """
    long_side = max(width_pt, height_pt) or 1.0
    return min(MAX_SIDE_PX / long_side, MAX_DPI / _DPI_BASE)


def render(pdf, page_index: int, file_id: int) -> PageImage:
    """渲染第 `page_index`（从 0 开始）页到盘上，返回相对路径与像素尺寸。

    已存在的页图直接复用：原件按 sha256 命名、内容不可变，同一页图不会变。
    单页重试因此省掉一次重新渲染（大页面渲染约 0.2–0.4 s）。
    """
    rel = rel_path(file_id, page_index + 1)
    out = get_settings().data_dir / rel
    page = pdf[page_index]
    try:
        width_pt, height_pt = page.get_size()
        scale = _scale(width_pt, height_pt)

        if out.is_file() and out.stat().st_size > 0:
            # 原件按 sha256 命名、内容不可变，同一页图不会变 —— 单页重试省掉一次渲染
            return PageImage(path=rel, width=round(width_pt * scale),
                             height=round(height_pt * scale))

        out.parent.mkdir(parents=True, exist_ok=True)
        bitmap = page.render(scale=scale)
        try:
            image = _flatten(bitmap.to_pil())
            image.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
            size = image.size
        finally:
            bitmap.close()
    finally:
        page.close()
    return PageImage(path=rel, width=size[0], height=size[1])


def _flatten(image):
    """带透明通道的位图转 JPEG 前必须并到白底。

    直接 `convert("RGB")` 会把透明区变成**黑块**（samples 生成时踩过一次），
    而 PDF 里"白底"恰好是最常见的背景，一旦变黑整页都糊。
    """
    if image.mode not in ("RGBA", "LA"):
        return image
    from PIL import Image  # 组件的依赖，主包由 pypdfium2 的 to_pil 一并带上

    white = Image.new("RGB", image.size, (255, 255, 255))
    white.paste(image, mask=image.split()[-1])
    return white


def purge_file(file_id: int) -> None:
    """删内容时连带删页图目录（T9.10 之前由 `knowledge.delete_item` 调用）。"""
    folder = file_dir(file_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
        log.info("已删除页图目录 pages/%s", file_id)


def usage() -> dict:
    """页图占用统计（设置页「原件占了多少盘」会连带看这个）。"""
    base = root()
    if not base.exists():
        return {"count": 0, "bytes": 0}
    count = total = 0
    for path in base.rglob("*.jpg"):
        count += 1
        total += path.stat().st_size
    return {"count": count, "bytes": total}
