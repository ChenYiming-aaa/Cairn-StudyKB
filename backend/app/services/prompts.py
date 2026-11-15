"""`app/prompts/` 下模板的读取与 `{{占位符}}` 替换。

模板分两类，都从这里读：带占位符的（问答/出题/整理/批改）用 `render()` 填值，
正文由调用方整段拼的（初审/解析/校对）直接 `render("exam_audit")` 取原文。

替换是**单趟**的：值里若碰巧含 `{{XXX}}` 也不会被再替一遍 —— 标题里出现
`{{CONTENT}}` 这类字样时，两趟替换会把整篇正文抄进标题。模板里没给值的
占位符原样留着，拼错变量名时在 prompt 里能一眼看见 `{{TITLE}}`。
"""
from __future__ import annotations

import re

from app.paths import app_path

PROMPT_DIR = app_path("prompts")

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_]+)\}\}")


def render(name: str, **values: str) -> str:
    """读 `prompts/<name>.md` 并替换占位符（键不区分大小写，`.md` 可带可不带）。"""
    body = (PROMPT_DIR / (name if name.endswith(".md") else f"{name}.md")).read_text(
        encoding="utf-8"
    )
    if not values:
        return body
    table = {key.upper(): str(value) for key, value in values.items()}
    return _PLACEHOLDER.sub(lambda m: table.get(m.group(1).upper(), m.group(0)), body)
