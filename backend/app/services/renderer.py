"""T3.8 学习页渲染：Markdown → HTML → 模板 → 内嵌导图 SVG → 内联样式 → 净化。

三条硬约束（M3 §1）：
- 单文件离线可开：样式全内联，代码高亮用 `noclasses=True` 生成行内 style，零外链
- LLM 产出不许直接拼：正文（笔记）先转义再转 Markdown，最后整段过 bleach
- 导图内联成 `<svg>` 而不是 `<img src="data:...">`，并让白名单放行 SVG 标签

净化与模板的先后顺序：先净化正文，再套模板。反过来会把模板自带的 `<style>` 洗掉，
断网打开就没版式了——这是 §6.7 里最容易踩的一步。
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import datetime

import bleach
import markdown
from bleach.css_sanitizer import CSSSanitizer
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app.paths import app_path
from app.services import mindmap

TEMPLATE_DIR = app_path("templates")
_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# 净化白名单：正文能出现的全部标签。svg 必须放行，否则导图会被吃掉；
# script / iframe / foreignObject / object / embed 一律不给。
_ALLOWED_TAGS = [
    "section", "div", "span", "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "strong", "em", "del", "sup", "sub", "code", "pre",
    "blockquote", "a", "table", "thead", "tbody", "tr", "th", "td",
    "svg", "g", "rect", "circle", "line", "path", "text", "tspan", "title", "desc",
]
_ALLOWED_ATTRS = {
    "*": ["class", "id", "style"],
    "a": ["href", "title"],
    "svg": [
        "xmlns", "viewBox", "width", "height", "preserveAspectRatio",
        "role", "font-family", "font-size",
    ],
    "rect": ["x", "y", "width", "height", "rx", "ry", "fill", "stroke", "stroke-width"],
    "circle": ["cx", "cy", "r", "fill", "stroke", "stroke-width"],
    "line": ["x1", "y1", "x2", "y2", "stroke", "stroke-width"],
    "path": ["d", "fill", "stroke", "stroke-width", "fill-rule"],
    "g": ["transform", "fill", "stroke", "opacity"],
    "text": [
        "x", "y", "fill", "font-size", "font-family", "font-weight",
        "dominant-baseline", "text-anchor", "xml:space",
    ],
    "tspan": ["x", "y", "dx", "dy", "fill", "font-size"],
}
# Pygments 的 noclasses=True 只产出配色与字重，放开这些足够；position/overflow 等一律不放
_CSS = CSSSanitizer(
    allowed_css_properties=[
        "color", "background", "background-color", "font-weight", "font-style",
        "line-height", "padding", "margin", "border", "border-radius", "white-space",
        "text-align", "vertical-align",
    ]
)

_MD_EXTENSIONS = ["fenced_code", "tables", "toc", "sane_lists", "codehilite"]
_MD_CONFIG = {
    # 关键：行内 style，而不是 class（用 class 就必须外链 CSS，断网就废）
    "codehilite": {"noclasses": True, "pygments_style": "friendly", "guess_lang": False},
    "toc": {"permalink": False},
}

_EXTERNAL_REF = re.compile(r"""(?:src|href)\s*=\s*["'](?!#|data:)([^"']+)""", re.I)
_DANGEROUS = re.compile(r"<\s*(script|iframe|object|embed|foreignObject)\b", re.I)


def _esc(text: str) -> str:
    return html_lib.escape(text or "", quote=False)


def _md_text(text: str) -> str:
    """正文先转义再进 Markdown。

    只转 `&` 和 `<`：`>` 单独出现构不成标签，保留它才能让 `> 引用` 和代码块里的箭头
    正常显示。做完这一步，笔记里的 `<script>alert(1)</script>` 变成可见文本而不是标签。
    """
    return (text or "").replace("&", "&amp;").replace("<", "&lt;")


def _section_html(item: dict) -> str:
    note = (item.get("structured_note") or "").strip()
    summary = (item.get("summary") or "").strip()
    points = [p for p in (item.get("key_points") or []) if (p or "").strip()]
    tags = [t for t in (item.get("tags") or []) if (t or "").strip()]

    chips = []
    if item.get("category"):
        chips.append(f'<span class="chip">{_esc(item["category"])}</span>')
    if tags:
        chips.append('<span class="chip">' + _esc(" · ".join(f"#{t}" for t in tags)) + "</span>")
    if item.get("source_type"):
        chips.append(f'<span class="chip">{_esc(item["source_type"])}</span>')

    svg = mindmap.render_item_svg(
        item.get("title") or "", note, points, item.get("mindmap_theme") or "light"
    )

    blocks = [
        f'<section class="item" id="item-{int(item["id"])}">',
        f'<h2>{_esc(item.get("title") or "未命名条目")}</h2>',
    ]
    if chips:
        blocks.append('<p class="item-meta">' + "".join(chips) + "</p>")
    blocks.append(f'<div class="mindmap">{svg}</div>')
    if summary:
        blocks.append(f'<p class="summary">{_esc(summary)}</p>')
    if points:
        blocks.append('<div class="points-title">关键点</div>')
        blocks.append("<ul class=\"points\">")
        blocks.extend(f"<li>{_esc(p)}</li>" for p in points[:10])
        blocks.append("</ul>")

    blocks.append('<div class="note-title">结构化笔记</div>')
    if note:
        md = markdown.Markdown(extensions=_MD_EXTENSIONS, extension_configs=_MD_CONFIG)
        blocks.append(f'<div class="note">{md.convert(_md_text(note))}</div>')
    else:
        blocks.append('<div class="note"><p>（这篇还没有结构化笔记，先回知识库整理一下）</p></div>')
    blocks.append("</section>")
    return "\n".join(blocks)


def sanitize(body_html: str) -> str:
    return bleach.clean(
        body_html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=["http", "https", "mailto"],
        strip=True,
        css_sanitizer=_CSS,
    )


# ── 原文页签的版式 HTML（docx，T11.3）────────────────────
# 比学习页多放行 `img`，但**只认本站附件地址**：图是抽取时落盘、由
# `GET /api/knowledge/{id}/assets/{name}` 发出来的。外站地址整条删掉 ——
# 学习页那条「零外链」的约束不能因为原文页签要显示图就被放宽。
_PAGE_TAGS = [*_ALLOWED_TAGS, "img"]
_PAGE_ATTRS = {**_ALLOWED_ATTRS, "img": ["src", "alt", "width", "height"]}
_ASSET_SRC = re.compile(
    r"^/api/knowledge/\d+/assets/[0-9a-f]{8,32}\.(?:png|jpe?g|gif|webp|bmp)$"
)
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_SRC_ATTR = re.compile(r"""src\s*=\s*["']([^"']*)["']""", re.I)


def sanitize_page_html(body_html: str) -> str:
    """docx 的版式 HTML：白名单过一遍，`<img>` 逐条核对来源，顺手加懒加载。

    一份带图讲义几十张图，一次全下没必要 —— `loading="lazy"` 让浏览器只取看得见的。
    """
    clean = bleach.clean(
        body_html,
        tags=_PAGE_TAGS,
        attributes=_PAGE_ATTRS,
        protocols=["http", "https", "mailto"],
        strip=True,
        css_sanitizer=_CSS,
    )

    def keep(match: re.Match) -> str:
        tag = match.group(0)
        found = _SRC_ATTR.search(tag)
        if not found or not _ASSET_SRC.match(found.group(1)):
            return ""
        end = "/>" if tag.endswith("/>") else ">"
        body = tag[: -len(end)].rstrip()
        if re.search(r"\bloading\s*=", body, re.I):
            return body + end
        return f'{body} loading="lazy"{end}'

    return _IMG_TAG.sub(keep, clean)


def find_external_refs(page_html: str) -> list[str]:
    """找出所有会触发网络请求的引用（含 xmlns 不算，它是命名空间不是地址）。"""
    hits = [m.group(1) for m in _EXTERNAL_REF.finditer(page_html)]
    if "@import" in page_html or re.search(r"url\(\s*['\"]?https?:", page_html, re.I):
        hits.append("css-import")
    return hits


def render_page(title: str, items: list[dict], generated_at: str | None = None) -> str:
    """把若干条目渲染成一份完整的离线 HTML。"""
    if not items:
        raise ValueError("没有内容可生成学习页")

    body = sanitize("\n".join(_section_html(item) for item in items))
    if _DANGEROUS.search(body):
        raise ValueError("净化后仍含危险标签，拒绝产出")
    if (refs := find_external_refs(body)):
        raise ValueError(
            f"正文里有 {len(refs)} 处外部图片或链接，离线打开会缺内容。去掉后再生成"
        )

    stamp = generated_at or datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    template = _ENV.get_template("learning_page.html")
    page = template.render(
        title=title,
        item_count=len(items),
        generated_at=stamp,
        toc=[{"id": int(i["id"]), "title": i.get("title") or "未命名内容"} for i in items],
        body=Markup(body),
    )
    # 模板部分是自己写的静态结构，这里只做一次兜底扫描（防将来改模板带进外链）
    if (refs := find_external_refs(page)):
        raise ValueError(f"页面模板里混进了外部引用（{len(refs)} 处），这是程序问题，请反馈")
    return page


def size_bytes(page_html: str) -> int:
    return len(page_html.encode("utf-8"))
