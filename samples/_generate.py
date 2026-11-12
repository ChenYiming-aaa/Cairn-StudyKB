# -*- coding: utf-8 -*-
"""把 _content.py 的数据渲染成 16 份真实样本。

用法（需独立 venv，见 samples/README.md）：
    python samples/_generate.py            # 生成 16 份 + 自检报告 _check.json
    python samples/_generate.py --verify   # 只跑自检

产物布局：samples/<主题>/{course.docx, twocol.pdf, exam.pdf, scan.pdf}
"""
from __future__ import annotations

import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image as RLImage, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
IMGDIR = ROOT / "images"
FONT_DIR = Path("C:/Windows/Fonts")
SONG, HEI, KAI, YH = "CN_Song", "CN_Hei", "CN_Kai", "CN_YaHei"
pdfmetrics.registerFont(TTFont(SONG, str(FONT_DIR / "simsun.ttc"), subfontIndex=0))
pdfmetrics.registerFont(TTFont(HEI, str(FONT_DIR / "simhei.ttf")))
pdfmetrics.registerFont(TTFont(KAI, str(FONT_DIR / "simkai.ttf")))
# 微软雅黑：数学符号（− ∂ ″ 等）覆盖最全，也是项目 OCR 基准用字
pdfmetrics.registerFont(TTFont(YH, str(FONT_DIR / "msyh.ttc"), subfontIndex=0))
pdfmetrics.registerFontFamily(SONG, normal=SONG, bold=HEI, italic=SONG, boldItalic=HEI)
pdfmetrics.registerFontFamily(YH, normal=YH, bold=HEI, italic=YH, boldItalic=HEI)

sys.path.insert(0, str(ROOT))
from _content import TOPICS as _RAW_TOPICS  # noqa: E402

# 微软雅黑 / 宋体缺这 5 个字形，会渲染成方框；统一换成等价写法，避免样本里出现假生僻字
CHAR_FIX = str.maketrans({"₀": "0", "₁": "1", "₂": "2", "⇒": "=>", "⇏": "!=>"})


def normalize(obj):
    if isinstance(obj, str):
        return obj.translate(CHAR_FIX)
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(normalize(v) for v in obj)
    return obj


TOPICS = normalize(_RAW_TOPICS)

# 每个主题在双栏讲义里轮换使用的配图
LECTURE_IMAGES = {
    "python": ["python_logo_notext.png", "python_turtle_star.png"],
    "java": ["java_logo.png", "java_uml_class.png", "java_duke.png"],
    "cet6": ["cet6_score_report.jpg", "cet6_report_baike.png"],
    "math": ["math_parabola.png", "math_integral_area.png", "math_normal_dist.png"],
}

W, H = A4
ML = 2 * cm
GUTTER = 0.7 * cm
COLW = (W - 2 * ML - GUTTER) / 2
FRAME_BOTTOM = 2 * cm
FRAME_HEIGHT = H - 2.2 * cm - FRAME_BOTTOM


# ── 通用小工具 ────────────────────────────────────────────────
def txt_para(text, style):
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def code_para(text, style):
    """保留缩进空格、允许自动折行，避免 Preformatted 在窄栏里溢出。"""
    lines = []
    for line in str(text).split("\n"):
        body = line.lstrip(" ")
        pad = len(line) - len(body)
        lines.append("&nbsp;" * pad + escape(body))
    return Paragraph("<br/>".join(lines), style)


_RGB_CACHE = {}


def rgb_path(path):
    """统一转成不透明 RGB：源图有 LA / RGBA / JPEG；照片类降采样存 JPEG，线条图存 PNG。"""
    key = str(path)
    if key not in _RGB_CACHE:
        cache = Path(tempfile.gettempdir()) / "cairn_samples_rgb"
        cache.mkdir(exist_ok=True)
        stem = Path(key).stem
        src = Image.open(path)
        # LA / RGBA 图直接 convert("RGB") 会把透明区变成黑块，必须先合成白底
        if src.mode in ("RGBA", "LA") or "transparency" in src.info:
            rgba = src.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            bg.alpha_composite(rgba)
            pil = bg.convert("RGB")
        else:
            pil = src.convert("RGB")
        pil.thumbnail((1100, 1100), Image.LANCZOS)
        photo = Path(key).suffix.lower() in (".jpg", ".jpeg") or pil.width * pil.height > 400000
        if photo:
            dst = cache / (stem + ".jpg")
            pil.save(dst, "JPEG", quality=86, optimize=True)
        else:
            dst = cache / (stem + ".png")
            pil.save(dst, "PNG", optimize=True)
        _RGB_CACHE[key] = dst
    return _RGB_CACHE[key]


def scaled_image(path, max_w, max_h):
    p = rgb_path(path)
    with Image.open(p) as pil:
        iw, ih = pil.size
    k = min(max_w / iw, max_h / ih)
    return RLImage(str(p), width=iw * k, height=ih * k)


def make_styles(size=10.5, leading=17, font=SONG):
    return {
        "body": ParagraphStyle("body", fontName=font, fontSize=size, leading=leading,
                               alignment=TA_JUSTIFY, spaceAfter=5, firstLineIndent=2 * size),
        "h1": ParagraphStyle("h1", fontName=HEI, fontSize=14, leading=20, spaceBefore=10,
                             spaceAfter=7, textColor=colors.HexColor("#1b3a5c")),
        "h2": ParagraphStyle("h2", fontName=HEI, fontSize=11.5, leading=17, spaceBefore=8,
                             spaceAfter=5, textColor=colors.HexColor("#244a6b")),
        "code": ParagraphStyle("code", fontName=font, fontSize=8.2, leading=11.5,
                               backColor=colors.HexColor("#f2f4f6"), borderPadding=5,
                               leftIndent=4, rightIndent=4, spaceBefore=3, spaceAfter=6),
        "note": ParagraphStyle("note", fontName=font, fontSize=9.3, leading=14,
                               backColor=colors.HexColor("#fff6e5"), borderPadding=5,
                               leftIndent=4, rightIndent=4, spaceBefore=3, spaceAfter=7,
                               textColor=colors.HexColor("#6b4a12")),
        "cap": ParagraphStyle("cap", fontName=font, fontSize=8.5, leading=12,
                              alignment=TA_CENTER, spaceBefore=3, spaceAfter=8,
                              textColor=colors.HexColor("#555555")),
        "cell": ParagraphStyle("cell", fontName=font, fontSize=8.5, leading=12),
        "cellh": ParagraphStyle("cellh", fontName=HEI, fontSize=8.7, leading=12,
                                textColor=colors.white),
        "title": ParagraphStyle("title", fontName=HEI, fontSize=19, leading=26,
                                alignment=TA_CENTER, spaceAfter=8),
        "sub": ParagraphStyle("sub", fontName=font, fontSize=10.5, leading=16,
                              alignment=TA_CENTER, spaceAfter=14,
                              textColor=colors.HexColor("#555555")),
        "sect": ParagraphStyle("sect", fontName=HEI, fontSize=12, leading=18,
                               spaceBefore=12, spaceAfter=7),
    }


def pdf_table(cap, head, rows, st, max_w):
    data = [[Paragraph(escape(str(c)), st["cellh"]) for c in head]]
    for row in rows:
        data.append([Paragraph(escape(str(c)), st["cell"]) for c in row])
    ncol = len(head)
    widths = [max_w / ncol] * ncol
    tb = Table(data, colWidths=widths, repeatRows=1, hAlign="CENTER")
    tb.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#315b80")),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#9aa9b5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fa")]),
    ]))
    return [tb, Paragraph(cap, st["cap"]), Spacer(1, 5)]


def pdf_blocks(blocks, st, max_w, img_queue=None, image_every=3, chapter_no=0):
    out = []
    for i, (typ, val) in enumerate(blocks):
        if typ == "p":
            out.append(txt_para(val, st["body"]))
        elif typ == "h2":
            out.append(txt_para(val, st["h2"]))
        elif typ in ("list", "num"):
            for j, item in enumerate(val):
                mark = "● " if typ == "list" else "%d. " % (j + 1)
                out.append(txt_para(mark + item, ParagraphStyle(
                    "li", parent=st["body"], firstLineIndent=0, leftIndent=12, spaceAfter=3)))
            out.append(Spacer(1, 4))
        elif typ == "code":
            out.append(code_para(val, st["code"]))
        elif typ == "note":
            out.append(txt_para("【提示】" + val, st["note"]))
        elif typ == "table":
            out.extend(pdf_table(val["caption"], val["head"], val["rows"], st, max_w))
        elif typ == "image":
            out.append(scaled_image(IMGDIR / val["file"], max_w * 0.8, max_w * 0.75))
            out.append(Paragraph(val["caption"], st["cap"]))
    if img_queue and chapter_no % image_every == 1:
        f = img_queue[(chapter_no // image_every) % len(img_queue)]
        out.append(scaled_image(IMGDIR / f, max_w * 0.72, max_w * 0.62))
        out.append(Paragraph("图：本讲配图（来源见 samples/images/_sources.json）", st["cap"]))
    return out


def make_onpage(header, twocol=False):
    counter = [0]

    def cb(canv, doc):
        counter[0] += 1
        canv.saveState()
        canv.setFont(SONG, 8)
        canv.setFillColor(colors.HexColor("#666666"))
        canv.drawString(ML, H - 1.35 * cm, header)
        canv.drawRightString(W - ML, H - 1.35 * cm, "第 %d 页" % doc.page)
        canv.setStrokeColor(colors.HexColor("#c8c8c8"))
        canv.setLineWidth(0.4)
        canv.line(ML, H - 1.6 * cm, W - ML, H - 1.6 * cm)
        canv.line(ML, 1.55 * cm, W - ML, 1.55 * cm)
        canv.drawCentredString(W / 2, 1.0 * cm, "— %d —" % doc.page)
        if twocol:
            x = ML + COLW + GUTTER / 2
            canv.setStrokeColor(colors.HexColor("#e2e2e2"))
            canv.line(x, FRAME_BOTTOM, x, FRAME_BOTTOM + FRAME_HEIGHT)
        canv.restoreState()

    return cb, counter


# ── 1. 课程 docx（标题层级 / 列表 / 图 / 表） ──────────────────
def set_cn(run, font="宋体", size=11, bold=False, color=None):
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font)


def shade(cell, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def add_page_field(paragraph):
    run = paragraph.add_run()
    a = OxmlElement("w:fldChar"); a.set(qn("w:fldCharType"), "begin")
    b = OxmlElement("w:instrText"); b.set(qn("xml:space"), "preserve"); b.text = "PAGE"
    c = OxmlElement("w:fldChar"); c.set(qn("w:fldCharType"), "end")
    for el in (a, b, c):
        run._r.append(el)
    set_cn(run, "宋体", 9)


def render_course(t, out):
    doc = Document()
    sec = doc.sections[0]
    sec.top_margin = Cm(2.2); sec.bottom_margin = Cm(2.0)
    sec.left_margin = Cm(2.4); sec.right_margin = Cm(2.4)
    normal = doc.styles["Normal"]
    normal.font.name = "宋体"; normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    hp = sec.header.paragraphs[0]
    set_cn(hp.add_run(t["label"] + " · 课程讲义"), "宋体", 9, color=(110, 110, 110))
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_cn(fp.add_run("第 "), "宋体", 9)
    add_page_field(fp)
    set_cn(fp.add_run(" 页"), "宋体", 9)

    c = t["course"]
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_cn(p.add_run(c["title"]), "黑体", 19, True)
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_cn(p.add_run(c["subtitle"]), "宋体", 11, color=(90, 90, 90))
    doc.add_paragraph()

    for ch in c["chapters"]:
        h = doc.add_heading(level=1)
        set_cn(h.add_run(ch["title"]), "黑体", 15, True, (27, 58, 92))
        for typ, val in ch["blocks"]:
            if typ == "p":
                pp = doc.add_paragraph()
                pp.paragraph_format.first_line_indent = Cm(0.74)
                pp.paragraph_format.line_spacing = 1.5
                pp.paragraph_format.space_after = Pt(6)
                set_cn(pp.add_run(val), "宋体", 11)
            elif typ == "h2":
                h2 = doc.add_heading(level=2)
                set_cn(h2.add_run(val), "黑体", 12.5, True, (36, 74, 107))
            elif typ in ("list", "num"):
                for j, item in enumerate(val):
                    pp = doc.add_paragraph(style="List Bullet" if typ == "list" else "List Number")
                    pp.paragraph_format.line_spacing = 1.4
                    set_cn(pp.add_run(item), "宋体", 10.5)
            elif typ == "code":
                pp = doc.add_paragraph()
                pp.paragraph_format.left_indent = Cm(0.6)
                pp.paragraph_format.space_before = Pt(4)
                pp.paragraph_format.space_after = Pt(8)
                set_cn(pp.add_run(val), "宋体", 9.5)
                pPr = pp._p.get_or_add_pPr()
                shd = OxmlElement("w:shd"); shd.set(qn("w:fill"), "F2F4F6")
                pPr.append(shd)
            elif typ == "note":
                pp = doc.add_paragraph()
                pp.paragraph_format.left_indent = Cm(0.4)
                pp.paragraph_format.space_after = Pt(8)
                set_cn(pp.add_run("【提示】" + val), "楷体", 10.5, color=(107, 74, 18))
                pPr = pp._p.get_or_add_pPr()
                shd = OxmlElement("w:shd"); shd.set(qn("w:fill"), "FFF6E5")
                pPr.append(shd)
            elif typ == "table":
                tb = doc.add_table(rows=1, cols=len(val["head"]))
                tb.style = "Table Grid"
                tb.alignment = WD_TABLE_ALIGNMENT.CENTER
                for i, hcell in enumerate(val["head"]):
                    cell = tb.rows[0].cells[i]
                    cell.text = ""
                    set_cn(cell.paragraphs[0].add_run(hcell), "黑体", 9.5, True)
                    shade(cell, "315B80")
                for row in val["rows"]:
                    cells = tb.add_row().cells
                    for i, v in enumerate(row):
                        cells[i].text = ""
                        set_cn(cells[i].paragraphs[0].add_run(str(v)), "宋体", 9)
                cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                set_cn(cp.add_run(val["caption"]), "宋体", 9, color=(90, 90, 90))
                doc.add_paragraph()
            elif typ == "image":
                pp = doc.add_paragraph(); pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pp.add_run().add_picture(str(rgb_path(IMGDIR / val["file"])),
                                         width=Cm(val["width"]))
                cp = doc.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                set_cn(cp.add_run(val["caption"]), "宋体", 9, color=(90, 90, 90))
    doc.save(str(out))


# ── 2. 双栏讲义 PDF ───────────────────────────────────────────
def iter_questions(t):
    """按试卷顺序产出 (全局题号, 题目 dict)。"""
    n = 0
    for s in t["exam"]["sections"]:
        for q in s.get("items", []):
            n += 1
            yield n, q
        for pas in s.get("passages", []):
            for q in pas["questions"]:
                n += 1
                yield n, q


def lecture_story(t, st, appendix_level=0):
    lec = t["lecture"]
    story = [
        txt_para(lec["title"], st["title"]),
        txt_para(t["label"] + " · 双栏排版 · " + "考点精讲与例题", st["sub"]),
        HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#315b80"),
                   spaceAfter=10),
    ]
    imgs = LECTURE_IMAGES[t["key"]]
    for i, ch in enumerate(lec["chapters"]):
        story.append(txt_para(ch["title"], st["h1"]))
        story.extend(pdf_blocks(ch["blocks"], st, COLW, imgs, 3, i))
        # 讲义常见版式：每章末尾留出供手写补充的笔记区
        story.append(Spacer(1, 10))
        story.append(Paragraph("课堂笔记（留白）", st["cap"]))
        story.append(Spacer(1, 34))
        story.append(HRFlowable(width="45%", thickness=0.4,
                                color=colors.HexColor("#d5d5d5"), spaceAfter=8))

    if appendix_level >= 1:
        story.append(PageBreak())
        story.append(txt_para("附录 A　真题自测（选择题）", st["h1"]))
        story.append(txt_para("以下题目选自本讲配套模拟卷，答案与解析见附录 B。建议先独立作答，"
                              "再对照解析回看对应章节。", st["body"]))
        for n, q in iter_questions(t):
            story.append(txt_para("%d. %s" % (n, q["q"]), ParagraphStyle(
                "qa", parent=st["body"], firstLineIndent=0, spaceAfter=2)))
            story.append(txt_para("　" + "　".join(q["opts"]), ParagraphStyle(
                "qo", parent=st["body"], fontSize=9, leading=13, firstLineIndent=0,
                spaceAfter=4)))

    if appendix_level >= 2:
        story.append(txt_para("附录 B　参考答案与考点回指", st["h1"]))
        for n, q in iter_questions(t):
            story.append(txt_para("%d.【%s】%s" % (n, q["ans"], q["exp"]),
                                  ParagraphStyle("qe", parent=st["body"], fontSize=9,
                                                 leading=13, firstLineIndent=0, spaceAfter=3)))
        story.append(Spacer(1, 8))
        story.append(txt_para("附录 C　公式与考点速查表", st["h1"]))
        for ch in t["course"]["chapters"]:
            for typ, val in ch["blocks"]:
                if typ == "table":
                    story.extend(pdf_table(val["caption"], val["head"], val["rows"], st, COLW))
        for ch in lec["chapters"]:
            for typ, val in ch["blocks"]:
                if typ == "table":
                    story.extend(pdf_table(val["caption"], val["head"], val["rows"], st, COLW))

    if appendix_level >= 3:
        story.append(txt_para("附录 D　非选择题参考解答", st["h1"]))
        for sec in t["exam"]["open"]:
            story.append(txt_para(sec["title"], st["h2"]))
            for it in sec["items"]:
                story.append(txt_para("题目：" + it["q"], ParagraphStyle(
                    "oe", parent=st["body"], fontSize=9, leading=13, firstLineIndent=0)))
                story.append(code_para(it["ans"], st["code"]))

    if appendix_level >= 4:
        story.append(txt_para("附录 E　易错点清单", st["h1"]))
        notes = []
        for grp in ("course", "lecture"):
            chapters = t[grp]["chapters"]
            for ch in chapters:
                for typ, val in ch["blocks"]:
                    if typ == "note":
                        notes.append(val)
        for i, n in enumerate(notes, 1):
            story.append(txt_para("%d. %s" % (i, n), ParagraphStyle(
                "en", parent=st["body"], firstLineIndent=0, spaceAfter=4)))

    if appendix_level >= 5:
        story.append(PageBreak())
        story.append(txt_para("附录 F　拍照真题选登（考生回忆版）", st["h1"]))
        story.append(txt_para("以下题目来自同主题的另一套试卷，供课堂限时练习使用。"
                              "原卷为手机拍摄，此处按印刷体重排，题号沿用原卷。", st["body"]))
        sl = ParagraphStyle("sl", parent=st["body"], fontSize=9, leading=13,
                            firstLineIndent=0, spaceAfter=1)
        for pg in t["scan"]["pages"]:
            story.append(txt_para(pg["title"], st["h2"]))
            for line in pg["lines"]:
                story.append(txt_para(line or "　", sl))
            story.append(Spacer(1, 8))

    if appendix_level >= 6:
        story.append(PageBreak())
        story.append(txt_para("附录 G　主观题限时练习（留白作答）", st["h1"]))
        n = 0
        for sec in t["exam"]["open"]:
            story.append(txt_para(sec["title"], st["h2"]))
            for it in sec["items"]:
                n += 1
                story.append(txt_para("%d. %s" % (n, it["q"]), ParagraphStyle(
                    "gq", parent=st["body"], firstLineIndent=0, spaceAfter=3)))
                story.append(Spacer(1, 42))
    return story


def render_twocol(story, out, header):
    cb, counter = make_onpage(header, twocol=True)
    doc = BaseDocTemplate(str(out), pagesize=A4, title=header,
                          author="Cairn 样本生成器", leftMargin=ML, rightMargin=ML,
                          topMargin=2.2 * cm, bottomMargin=FRAME_BOTTOM)
    frames = [
        Frame(ML, FRAME_BOTTOM, COLW, FRAME_HEIGHT, id="L",
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
        Frame(ML + COLW + GUTTER, FRAME_BOTTOM, COLW, FRAME_HEIGHT, id="R",
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
    ]
    doc.addPageTemplates([PageTemplate(id="twocol", frames=frames, onPage=cb)])
    doc.build(story)
    return counter[0]


def build_lecture(t, out):
    # 讲义用较大字号与行距：接近真实课堂讲义的留白量，也保证 ≥10 页的双栏判列样本
    st = make_styles(11.5, 21.5, YH if t["key"] == "math" else SONG)
    pages = 0
    for level in range(7):
        story = lecture_story(t, st, level)
        pages = render_twocol(story, out, t["lecture"]["header"])
        if pages >= 10:
            break
    return pages, level


# ── 3. 电子版试卷 PDF（文字层可复制） ──────────────────────────
def render_exam(t, out):
    st = make_styles(10.5, 16, YH if t["key"] == "math" else SONG)
    st["q"] = ParagraphStyle("q", parent=st["body"], firstLineIndent=0, spaceAfter=3)
    st["opt"] = ParagraphStyle("opt", parent=st["body"], fontSize=9.5, leading=14,
                               firstLineIndent=0, leftIndent=16, spaceAfter=1)
    st["pass"] = ParagraphStyle("pass", parent=st["body"], fontSize=9.5, leading=14,
                                leftIndent=8, rightIndent=8, firstLineIndent=0,
                                backColor=colors.HexColor("#f7f8fa"), borderPadding=6,
                                spaceBefore=5, spaceAfter=7)
    cb, _ = make_onpage(t["exam"]["header"])
    doc = BaseDocTemplate(str(out), pagesize=A4, title=t["exam"]["title"],
                          author="Cairn 样本生成器", leftMargin=ML, rightMargin=ML,
                          topMargin=2.2 * cm, bottomMargin=FRAME_BOTTOM)
    frame = Frame(ML, FRAME_BOTTOM, W - 2 * ML, FRAME_HEIGHT, id="single",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="single", frames=[frame], onPage=cb)])

    e = t["exam"]
    story = [txt_para(e["title"], st["title"]), txt_para(e["subtitle"], st["sub"])]
    info = Table([[Paragraph(escape(m), st["cell"]) for m in e["meta"]]],
                 colWidths=[(W - 2 * ML) / 3] * 3)
    info.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                              ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999"))]))
    story += [info, Spacer(1, 10)]
    story.append(txt_para("注意事项：1. 答题前请填写学校、姓名与准考证号；"
                          "2. 选择题答案填涂在答题卡上；3. 保持卷面整洁。", st["note"]))

    qn = 0
    answers = []
    open_answers = []
    for sec in e["sections"]:
        story.append(txt_para(sec["title"], st["sect"]))
        for q in sec.get("items", []):
            qn += 1
            answers.append((qn, q["ans"], q["exp"]))
            story.append(txt_para("%d. %s" % (qn, q["q"]), st["q"]))
            for o in q["opts"]:
                story.append(txt_para(o, st["opt"]))
            story.append(Spacer(1, 4))
        for pas in sec.get("passages", []):
            story.append(txt_para(pas["text"], st["pass"]))
            for q in pas["questions"]:
                qn += 1
                answers.append((qn, q["ans"], q["exp"]))
                story.append(txt_para("%d. %s" % (qn, q["q"]), st["q"]))
                for o in q["opts"]:
                    story.append(txt_para(o, st["opt"]))
                story.append(Spacer(1, 4))

    for sec in e["open"]:
        story.append(PageBreak())
        story.append(txt_para(sec["title"], st["sect"]))
        for it in sec["items"]:
            qn += 1
            open_answers.append((qn, it["ans"]))
            story.append(txt_para("%d. %s" % (qn, it["q"]), st["q"]))
            story.append(Spacer(1, 26))

    story.append(PageBreak())
    story.append(txt_para("参考答案与解析", st["title"]))
    story.append(txt_para("一、客观题答案速查", st["h1"]))
    compact = "　".join("%d.%s" % (n, a) for n, a, _ in answers)
    story.append(txt_para(compact, ParagraphStyle("ans", parent=st["body"],
                                                  fontSize=9.5, leading=14, firstLineIndent=0)))
    story.append(Spacer(1, 8))
    story.append(txt_para("二、逐题解析", st["h1"]))
    for n, a, exp in answers:
        story.append(txt_para("%d.（%s）%s" % (n, a, exp), ParagraphStyle(
            "exp", parent=st["body"], fontSize=9.3, leading=13, firstLineIndent=0, spaceAfter=3)))
    story.append(Spacer(1, 8))
    story.append(txt_para("三、主观题参考答案", st["h1"]))
    for n, ans in open_answers:
        story.append(txt_para("%d. %s" % (n, ans),
                              ParagraphStyle("oa", parent=st["body"], fontSize=9.2,
                                             leading=13, firstLineIndent=0, spaceAfter=5)))
    doc.build(story)
    return qn


# ── 4. 扫描 / 拍照试卷（图片型 PDF，无文字层） ─────────────────
PW, PH = 1240, 1754          # A4 @ 150dpi，与 OCR 组件的样本基准一致
PAPER = (250, 248, 242)


def wrap_line(draw, text, font, max_w):
    out, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w and cur:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out or [""]


def render_scan_page(page, font_size, angle, rng):
    base = Image.new("RGB", (PW, PH), PAPER)
    d = ImageDraw.Draw(base)
    f_title = ImageFont.truetype(str(FONT_DIR / "simhei.ttf"), int(font_size * 1.5))
    # 拍照卷正文用微软雅黑：数学符号齐全，与 OCR 组件的样本基准（雅黑 30px）一致
    f_body = ImageFont.truetype(str(FONT_DIR / "msyh.ttc"), int(font_size))
    f_hand = ImageFont.truetype(str(FONT_DIR / "simkai.ttf"), int(font_size * 1.05))

    d.text((PW // 2, 90), page["title"], font=f_title, fill=(25, 25, 25), anchor="mm")
    d.line((95, 140, PW - 95, 140), fill=(70, 70, 70), width=2)
    d.text((95, 158), "姓名＿＿＿＿＿＿　学号＿＿＿＿＿＿　密封线内不要答题",
           font=ImageFont.truetype(str(FONT_DIR / "msyh.ttc"), int(font_size * 0.8)),
           fill=(95, 95, 95))

    max_w = PW - 190
    lh = int(font_size * 1.55)
    y = 220
    for line in page["lines"]:
        for sub in wrap_line(d, line, f_body, max_w):
            d.text((95, y), sub, font=f_body, fill=(28, 28, 28))
            y += lh
    # 手写批注：楷体、蓝墨、轻微倾斜
    for i, mark in enumerate(page.get("marks", [])[:3]):
        mx = 620 + int(rng.integers(-40, 60))
        my = 1380 + i * 90
        layer = Image.new("RGBA", (540, 80), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((8, 8), "批注：" + mark[:18], font=f_hand, fill=(26, 61, 124, 235))
        layer = layer.rotate(int(rng.integers(-4, 5)), resample=Image.BICUBIC, expand=True)
        base.paste(layer, (mx, my), layer)
    d.line((95, PH - 120, PW - 95, PH - 120), fill=(150, 150, 150), width=1)
    d.text((PW // 2, PH - 85), "本页为拍照采集，字迹与光照以原图为准",
           font=ImageFont.truetype(str(FONT_DIR / "msyh.ttc"), int(font_size * 0.75)),
           fill=(120, 120, 120), anchor="mm")

    arr = np.asarray(base, dtype=np.float32)
    yy, xx = np.mgrid[0:PH, 0:PW]
    shade = 1.0 - 0.13 * (xx / PW) - 0.09 * (yy / PH)     # 单侧光照不均
    arr = arr * shade[..., None]
    arr += rng.normal(0, 4.2, arr.shape)                    # 传感器噪点
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    noisy = Image.fromarray(arr).rotate(angle, resample=Image.BICUBIC,
                                       expand=False, fillcolor=PAPER)
    noisy = noisy.filter(ImageFilter.GaussianBlur(0.35))
    buf = io.BytesIO()
    noisy.save(buf, "JPEG", quality=82)                     # 手机拍照压缩痕迹
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def scan_font_size(page):
    """按实际折行后的总高度挑字号，保证正文不越过页脚与手写批注区。"""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for fs in range(30, 21, -1):
        f = ImageFont.truetype(str(FONT_DIR / "msyh.ttc"), fs)
        total = sum(len(wrap_line(probe, line, f, PW - 190)) for line in page["lines"])
        if 220 + total * int(fs * 1.55) <= PH - 260:
            return fs
    return 22


def render_scan(t, out):
    rng = np.random.default_rng({"python": 11, "java": 22, "cet6": 33, "math": 44}[t["key"]])
    pages = []
    angles = [1.3, -1.1, 0.8, -1.5]
    for i, page in enumerate(t["scan"]["pages"]):
        pages.append(render_scan_page(page, scan_font_size(page), angles[i % len(angles)], rng))
    pages[0].save(str(out), "PDF", resolution=150.0, save_all=True,
                  append_images=pages[1:])
    return len(pages), pages[0].size


# ── 5. 自检 ───────────────────────────────────────────────────
def verify_one(t, d):
    import re
    import zipfile
    res = {"topic": t["label"]}
    # docx
    course = d / "course.docx"
    doc = Document(str(course))
    with zipfile.ZipFile(course) as z:
        media = [n for n in z.namelist() if n.startswith("word/media/")]
    res["course"] = {"bytes": course.stat().st_size, "paragraphs": len(doc.paragraphs),
                     "tables": len(doc.tables), "images": len(media),
                     "headings": sum(1 for p in doc.paragraphs if p.style.name.startswith("Heading"))}
    # 双栏讲义
    tw = d / "twocol.pdf"
    r = PdfReader(str(tw))
    text = "\n".join((p.extract_text() or "") for p in r.pages)
    hdr_count = sum((p.extract_text() or "").count(t["lecture"]["header"]) for p in r.pages)
    res["twocol"] = {"bytes": tw.stat().st_size, "pages": len(r.pages),
                     "chars": len(text), "headers": hdr_count,
                     "cjk": len(re.findall(r"[\u4e00-\u9fff]", text))}
    try:  # 用字符坐标证明「真的分了左右两栏」，而不只是排版看起来像
        import pypdfium2 as pdfium
        tp = pdfium.PdfDocument(str(tw))[0].get_textpage()
        xs = [tp.get_charbox(i)[0] for i in range(tp.count_chars()) if tp.get_charbox(i)]
        res["twocol"]["left_col_chars"] = sum(40 < x < 290 for x in xs)
        res["twocol"]["right_col_chars"] = sum(300 < x < 560 for x in xs)
    except Exception:
        pass
    # 电子试卷
    ex = d / "exam.pdf"
    r2 = PdfReader(str(ex))
    t2 = "\n".join((p.extract_text() or "") for p in r2.pages)
    qnums = re.findall(r"(?m)^(\d{1,2})\.\s", t2)
    res["exam"] = {"bytes": ex.stat().st_size, "pages": len(r2.pages),
                   "chars": len(t2), "question_marks": len(set(qnums)),
                   "options": len(re.findall(r"[A-D]\.\s", t2)),
                   "has_answers": "参考答案" in t2}
    # 扫描卷
    sc = d / "scan.pdf"
    r3 = PdfReader(str(sc))
    t3 = "\n".join((p.extract_text() or "") for p in r3.pages)
    res["scan"] = {"bytes": sc.stat().st_size, "pages": len(r3.pages),
                   "text_layer_chars": len(t3.strip()),
                   "images_per_page": [len(p.images) for p in r3.pages]}
    return res


def main():
    only_verify = "--verify" in sys.argv
    report = {}
    for key, t in TOPICS.items():
        d = ROOT / key
        d.mkdir(exist_ok=True)
        if not only_verify:
            render_course(t, d / "course.docx")
            pages, level = build_lecture(t, d / "twocol.pdf")
            qn = render_exam(t, d / "exam.pdf")
            npages, px = render_scan(t, d / "scan.pdf")
            print(f"[{key:7s}] docx / 双栏 {pages} 页(附录 {level} 级) / 试卷 {qn} 题 / "
                  f"拍照 {npages} 页 {px}")
        report[key] = verify_one(t, d)
        r = report[key]
        print(f"           校验: docx 表{r['course']['tables']} 图{r['course']['images']} "
              f"标题{r['course']['headings']} | 双栏{r['twocol']['pages']}页 "
              f"{r['twocol']['chars']}字 页眉{r['twocol']['headers']} | "
              f"试卷{r['exam']['pages']}页 {r['exam']['chars']}字 "
              f"题号{r['exam']['question_marks']} 答案{r['exam']['has_answers']} | "
              f"拍照{r['scan']['pages']}页 文字层{r['scan']['text_layer_chars']}字")
    (ROOT / "_check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print("自检报告：", ROOT / "_check.json")


if __name__ == "__main__":
    main()
