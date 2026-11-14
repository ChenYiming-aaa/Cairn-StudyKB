"""演示站走查：v0.3 的三类原件 + 引用跳转 + 自带 Key 试用页。

**为什么需要它**：演示站是静态的，`npm run build` 通过不代表点得开。这条链上每一步都
可能在构建之后才断：
- pdf.js 的 worker 是 `.mjs`，静态服务器不认就会送 `text/plain`，浏览器拒载 →
  表现为「页图画得好好的，canvas 一个都没有」（其实已经退回页图模式了）；
- 页图 / 原件地址是从 `/api/...` 换成本地静态文件的，漏一条就是 404；
- 演示层的定位要现算，判据写错就会把人带到第 1 页。

用法：
    cd frontend && VITE_DEMO=1 npx vite build --base=./ --outDir dist-demo
    python tools/walk_demo.py                 # 起本地服务 + 跑（默认 8899）
    python tools/walk_demo.py --url https://chenyiming-aaa.github.io/Cairn-StudyKB/   # 跑线上
    python tools/walk_demo.py --headful       # 看着它点

退出码：0 全绿 / 1 有 FAIL / 2 环境不满足（缺 dist-demo / 缺 Playwright）
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist-demo"
SHOTS = ROOT / "tmp" / "demo-shots"

EXTRA = {
    ".mjs": "text/javascript",
    ".wasm": "application/wasm",
    ".bcmap": "application/octet-stream",
}


class Handler(SimpleHTTPRequestHandler):
    """只多干一件事：给 .mjs 送 text/javascript（GitHub Pages 本来就是对的做法）。"""

    def guess_type(self, path):
        for suffix, mime in EXTRA.items():
            if str(path).endswith(suffix):
                return mime
        return super().guess_type(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def serve(port: int) -> str:
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(DIST)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/"
    for _ in range(40):
        try:
            with urllib.request.urlopen(base, timeout=1):
                return base
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("本地服务没起来")


class Report:
    def __init__(self) -> None:
        self.fail: list[str] = []
        self.errors: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        print(("PASS " if ok else "FAIL ") + name + (f" · {detail}" if detail else ""), flush=True)
        if not ok:
            self.fail.append(name)


def open_raw(page, base: str, title_hint: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    page.wait_for_timeout(1300)
    page.get_by_text(title_hint, exact=False).first.click()
    page.wait_for_timeout(1200)
    tabs = page.get_by_text("原文", exact=True)
    if tabs.count():
        tabs.first.click()
        page.wait_for_timeout(2500)


def run(base: str, headful: bool) -> Report:
    from playwright.sync_api import sync_playwright

    rep = Report()
    SHOTS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="msedge", headless=not headful)
        except Exception:
            browser = pw.chromium.launch(headless=not headful)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.on("console", lambda m: rep.errors.append(f"{m.type}: {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: rep.errors.append(f"pageerror: {e}"))

        # ── 列表：三类原件都在 ──
        page.goto(base, wait_until="domcontentloaded")
        page.wait_for_timeout(1600)
        page.screenshot(path=str(SHOTS / "01-home.png"))
        body = page.inner_text("body")
        rep.check("侧栏里有 PDF 讲义、Word 讲义、试卷",
                  "冲刺" in body and "题型结构" in body and "模拟卷" in body)

        # ── PDF：页图先出、canvas 后盖 ──
        open_raw(page, base, "考点精讲")
        page.screenshot(path=str(SHOTS / "02-pdf.png"))
        rep.check("PDF 连续滚动容器在", page.locator(".scroller").count() > 0)
        rep.check("页图垫底在", page.locator(".scroller img.shot").count() > 0)
        rep.check("canvas 画出来了（worker 起得来）",
                  page.locator(".scroller canvas.in").count() > 0)
        rep.check("没有退化成「没能按原样画出来」",
                  "没能按原样画出来" not in page.inner_text("body"))
        rep.check("右栏有这一页的文字", "命题" in page.inner_text("body"))

        # ── 引用跳转：检索 → 点命中 → 原文页签 + 落到第 N 页 + 标黄 ──
        page.goto(base + "#/ask", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        # 检索页默认是「问答」（要调模型，演示版拒绝），搜原文得切到「原文命中」
        page.get_by_text("原文命中", exact=True).first.click()
        page.wait_for_timeout(400)
        # 这句只在识别的原文里出现，整理笔记里没有 —— 才会走「切原文并定位」那条路
        page.locator("textarea").first.fill("操作题的评分点是文件")
        page.locator("textarea").first.press("Enter")
        page.wait_for_timeout(1800)
        page.screenshot(path=str(SHOTS / "03-search.png"))
        hits = page.locator(".hit")
        rep.check("检索能搜到 PDF 里的词", hits.count() > 0, f"{hits.count()} 条")
        if hits.count():
            target = page.locator(".hit", has_text="考点精讲").first
            (target if target.count() else hits.first).click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(SHOTS / "04-jump.png"))
            rep.check("点命中直接切到「原文」页签", page.locator(".scroller").count() > 0)
            shown = page.inner_text("body")
            found = re.search(r"第 (\d+) 页 / 共 (\d+) 页", shown)
            rep.check("翻到了具体某一页", bool(found),
                      found.group(0) if found else shown[:60].replace("\n", " "))
            rep.check("命中的那一行标出来了",
                      page.locator(".line.hit").count() > 0,
                      f"{page.locator('.line.hit').count()} 行")

        # ── Word：内嵌图 ──
        open_raw(page, base, "题型结构")
        page.screenshot(path=str(SHOTS / "05-docx.png"))
        n_img = page.locator(".doc img").count()
        rep.check("Word 内嵌图显示出来", n_img > 0, f"{n_img} 张")
        srcs = page.locator(".doc img").evaluate_all(
            "els => els.map(e => e.getAttribute('src'))")
        rep.check("图走的是静态地址（不是 /api/...）",
                  all("demo/" in (s or "") for s in srcs), str(srcs)[:120])
        rep.check("图真的加载成功（不是坏图）",
                  page.locator(".doc img").evaluate_all(
                      "els => els.every(e => e.complete && e.naturalWidth > 0)"))

        # ── 试卷：按卷练 ──
        page.goto(base + "#/practice", wait_until="domcontentloaded")
        page.wait_for_timeout(1800)
        page.get_by_text("模拟卷", exact=False).first.click()
        page.wait_for_timeout(1200)
        run_btn = page.get_by_role("button", name="按卷练")
        rep.check("试卷能点「按卷练」", run_btn.count() > 0)
        if run_btn.count():
            run_btn.first.click()
            page.wait_for_timeout(2000)
            page.screenshot(path=str(SHOTS / "06-quiz.png"))
            shown = page.inner_text("body")
            found = re.search(r"第 (\d+) / (\d+) 题", shown)
            rep.check("按卷练取到整卷", bool(found),
                      found.group(0) if found else shown[:80].replace("\n", " "))

        # ── 试用页（自带 Key）──
        page.goto(base + "#/try", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(SHOTS / "07-try.png"))
        t = page.inner_text("body")
        rep.check("试用页渲染", "用自己的 Key" in t)
        rep.check("三家能跨域直连的服务商都在",
                  "DeepSeek" in t and "OpenAI" in t and "通义" in t)
        rep.check("写明了请求不经过本项目服务器",
                  "不经过本项目的任何服务器" in t.replace("\n", ""))
        page.get_by_role("button", name="用示例材料").click()
        page.wait_for_timeout(700)
        value = page.locator("textarea").first.input_value()
        rep.check("示例材料能填进输入框", "切片" in value and len(value) > 300, f"{len(value)} 字")
        page.screenshot(path=str(SHOTS / "08-try-sample.png"))

        browser.close()
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="演示站走查")
    ap.add_argument("--url", default="", help="跑线上地址；不给就起本地服务")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    args = ap.parse_args()

    if args.url:
        base = args.url if args.url.endswith("/") else args.url + "/"
    else:
        if not (DIST / "index.html").is_file():
            print(f"× 缺 {DIST}，先 cd frontend && VITE_DEMO=1 npx vite build --base=./ --outDir dist-demo")
            return 2
        base = serve(args.port)
        print(f"本地服务 {base}")

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("× 没装 Playwright：backend/.venv/Scripts/python.exe -m pip install playwright")
        return 2

    print(f"走查 {base}")
    rep = run(base, args.headful)

    print(f"\n截图：{SHOTS}")
    if rep.errors:
        print(f"console 错误 {len(rep.errors)} 条：")
        for line in rep.errors[:10]:
            print("   ", line[:170])
    else:
        print("console 没有错误")
    if rep.fail:
        print(f"\n{len(rep.fail)} 条 FAIL：", rep.fail)
        return 1
    print("\n全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
