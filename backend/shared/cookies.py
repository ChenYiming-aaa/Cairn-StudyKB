"""cookie 文件的读写规则 —— **主程序与 browser 组件共用**。

只依赖标准库，所以即使 playwright 被 `excludes` 剔掉（冻结包的基础形态）
也能 import：`browser.py` 在"没有 playwright"时仍要能读 cookies.txt 判断登录态。

`to_netscape` 的坑见函数 docstring（HttpOnly 前缀），这条规则两处必须一致：
一处写错，yt-dlp 那边就当未登录，而且文件看着完全正常。
"""
from __future__ import annotations

from pathlib import Path

COOKIE_HEADER = ["# Netscape HTTP Cookie File", "# 由 Cairn 登录助手导出", ""]


def to_netscape(cookies: list[dict]) -> str:
    """Playwright 的 cookie 列表 → Netscape cookies.txt（yt-dlp / curl 通用格式）。

    HttpOnly 的 cookie 必须加 `#HttpOnly_` 前缀，否则 MozillaCookieJar 会把整行
    当注释跳过。B 站的 SESSDATA 正是 HttpOnly —— 漏了这个前缀，文件看着正常，
    yt-dlp 却当未登录，这个坑很隐蔽。
    """
    lines = list(COOKIE_HEADER)
    for c in cookies:
        domain = (c.get("domain") or "").strip()
        name = (c.get("name") or "").strip()
        if not domain or not name:
            continue
        expires = int(c.get("expires") or 0)
        if expires <= 0:
            expires = 0                  # 会话 cookie：0 是 Netscape 的约定
        prefix = "#HttpOnly_" if c.get("httpOnly") else ""
        lines.append("\t".join([
            prefix + domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            c.get("path") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(expires),
            name,
            c.get("value") or "",
        ]))
    return "\n".join(lines) + "\n"


def cookie_names(path: Path) -> set[str]:
    """只读文件名，不启动浏览器 —— 状态查询要快。"""
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    for line in text.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            names.add(parts[5].strip())
    return names
