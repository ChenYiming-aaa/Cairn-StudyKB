"""docx 抽取（T9.7）：python-docx 取结构，mammoth 转 HTML 供原文页签用。

**两套读取不是重复劳动**：python-docx 给的是可检索的纯文本（进 `raw_content`），
mammoth 给的是"长得像原文"的 HTML（T9.10 的原文页签）。只留一个都不够 ——
HTML 里塞满 `<p>` 标签会让切块和关键词命中变差，纯文本又没法在原文页签里看版式。

**顺序必须按 body 走**：`document.paragraphs` 与 `document.tables` 是两个独立列表，
分开取会把所有表格堆到正文末尾（讲义里"见表 3"指向前文的表，一挪就对不上）。
所以按 `document.element.body` 的子元素顺序遍历。

**内嵌图片（T11.3）不进库、不 base64**：mammoth 默认把图转成 `data:image/png;base64,...`，
一份带图讲义能到几十 MB。这里在转换回调里把图**抠出来单独存盘**（内容哈希命名，
同图只存一份），HTML 里只留 `/api/knowledge/{id}/assets/{name}`。

体积口径与 PDF 页图一致：长边钳到 1600 px，转 JPEG q85；**带透明通道的留 PNG**
（透明区压成 JPEG 会变黑，讲义里的公式图、流程图常有透明底）。
已经够小的 JPEG 原样留，不做二次压缩 —— 重编码一次就掉一次画质，没有收益。
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import mammoth
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services import renderer
from app.services.extractors.base import Asset, ExtractedDoc, Extractor, ExtractError, PageText, \
    md_table, tidy

MAX_HEADING = 6
MAX_SIDE = 1600          # 与 pdf_pages.MAX_SIDE_PX 同口径：长边上限
JPEG_QUALITY = 85
KEEP_BYTES = 300 * 1024  # 小图原样留（再压只会掉画质，省不下多少）


class DocxExtractor(Extractor):
    ext = "docx"

    def extract(self, path: Path, original_name: str = "", asset_url=None) -> ExtractedDoc:
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
        html, assets, skipped = _to_html(path, asset_url)

        props = document.core_properties
        meta = {
            "title": (props.title or "").strip(),
            "author": (props.author or "").strip(),
            "paragraphs": len(document.paragraphs),
            "tables": tables,
            "headings": headings,
            "images": len(document.inline_shapes),
            "images_kept": len(assets),
            "images_skipped": skipped,
            "html_chars": len(html),
        }
        page = PageText(page_no=1, text=text, html=html)
        return ExtractedDoc(text=text, pages=[page], page_count=1, meta=meta, assets=assets)


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


def _to_html(path: Path, asset_url):
    """mammoth → HTML → 白名单净化。返回 `(html, assets, 丢掉的图数)`。

    `asset_url` 为空（老调用方 / 单测）时退回"整份不带图"，不生成 base64。
    """
    assets: list[Asset] = []
    dropped = 0
    if asset_url is None:
        convert, counter = _drop_image, None
    else:
        convert, counter = _collector(assets, asset_url)

    try:
        with path.open("rb") as fh:
            result = mammoth.convert_to_html(io.BytesIO(fh.read()), convert_image=convert)
    except Exception:                                          # noqa: BLE001
        # HTML 只是原文页签的"锦上添花"，转不出来不该让整份抽取失败
        return "", [], 0
    if counter is not None:
        dropped = counter[0]
    return renderer.sanitize_page_html(result.value), assets, dropped


def _drop_image(_image) -> list:
    """mammoth 的图片回调：返回空列表 = 这个位置什么都不输出（不出 `<img>`）。"""
    return []


def _collector(assets: list[Asset], asset_url):
    """把图收进 `assets`，只回一个本站地址给 mammoth。

    **必须用 `mammoth.images.img_element` 包一层**：裸回调要返回 HTML **节点**列表
    （`_drop_image` 回 `[]` 就是"什么都不输出"），回属性字典会让 mammoth 在
    `strip_empty` 里抛 `'dict' object has no attribute '_accept0'` ——
    而它被外层 try 吞掉，症状是「整份讲义的版式凭空没了，一个字都不报」。

    **同图只存一份**：讲义里反复出现的校徽、页眉图标按内容哈希天然去重
    （同一张 200 KB 的校徽出现 30 次，盘上只有一份）。
    """
    seen: dict[str, str] = {}
    dropped = [0]

    def attributes(image) -> dict:
        # `img_element` 把 **image 对象**交进来（不是字节），自己开流读；
        # 直接当字节用 PIL 会打不开，症状是"每张图都被跳过"，而 HTML 一切正常。
        try:
            with image.open() as fh:
                raw = fh.read()
        except Exception:                                       # noqa: BLE001
            dropped[0] += 1
            return {"src": "", "alt": ""}
        packed = _pack(raw)
        if packed is None:            # EMF / WMF 这类浏览器画不出来的，直接不要
            dropped[0] += 1
            # 空地址会被净化阶段整条删掉（`_ASSET_SRC` 不认空串），不会留个破图
            return {"src": "", "alt": ""}
        data, ext = packed
        name = f"{hashlib.sha1(data).hexdigest()[:12]}.{ext}"
        if name not in seen:
            seen[name] = name
            assets.append(Asset(name=name, data=data))
        return {"src": asset_url(name), "alt": "插图"}

    return mammoth.images.img_element(attributes), dropped


def _pack(raw: bytes) -> tuple[bytes, str] | None:
    """`(字节, 扩展名)`；画不出来或解不开的返回 None。"""
    try:
        # Pillow 由主依赖里的 rapidocr 带进来（spec 只排 rapidocr/cv2 模块本身，不排 Pillow）；
        # 延迟 import：只有真遇到图片才付这点启动开销
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)     # 手机拍的讲义照片别躺倒
            fmt = (img.format or "").upper()
            small = max(img.size) <= MAX_SIDE and len(raw) <= KEEP_BYTES
            if small and fmt in ("JPEG", "JPG"):
                return raw, "jpg"
            alpha = img.mode in ("RGBA", "LA", "PA") or (
                img.mode == "P" and "transparency" in img.info
            )
            if max(img.size) > MAX_SIDE:
                img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
            buf = io.BytesIO()
            if alpha:
                img.convert("RGBA").save(buf, format="PNG", optimize=True)
                return buf.getvalue(), "png"
            img.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return buf.getvalue(), "jpg"
    except Exception:                                          # noqa: BLE001
        # EMF / WMF（Excel 粘过来的矢量图）PIL 打不开，也没有浏览器能直接画
        return None
