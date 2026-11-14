"""M11 验收脚本（T11.4）：原件级呈现 —— pdf.js 连续滚动 / 引用落到那一段 / Word 内嵌图片。

用法：
    cd frontend && npm run build          # 必须：本脚本测的是后端吐的 dist
    cd backend && uv run python scripts/verify_m11.py
    cd backend && uv run python scripts/verify_m11.py --only pdf      # 只跑 pdf.js 那条
    cd backend && uv run python scripts/verify_m11.py --only locate   # 只跑 chunk→页（纯接口）
    cd backend && uv run python scripts/verify_m11.py --only assets   # 只跑 Word 内嵌图片
    cd backend && uv run python scripts/verify_m11.py --only ui       # 只跑四种格式的引用定位
    cd backend && uv run python scripts/verify_m11.py --only pdf,ui   # 逗号分隔跑多组（同 regress 的 --only 7,9）

退出码：0 全绿 / 1 有用例失败 / 2 环境不满足（缺 dist / 缺浏览器 / 缺样本）

覆盖：
  §pdf    T11.1 连续滚动：`.scroller` 在、页图先出（垫底）、canvas 后盖上、
          只挂可视页（滚到顶/底时挂着的页数远小于总页数）、首屏页面可见 ≤1 秒、
          **没有真原件时退回页图**并说清原因（不能白屏）
  §locate T11.2 `knowledge/{id}/locate`：跨行 chunk 落页、行号与 `pages/{n}` 对齐、
          `q`（搜索词）优先于整段起点、**长锚点优先**（第 1 页的相似半句不能截胡
          第 3 页的完整段落 —— 真讲义重述页逼出来的缺陷）、落不到页给 null 不是 500、
          chunk 不属于这条内容给 null、内容不存在给 404、**校对文本优先于识别原文**
  §assets T11.3 Word 内嵌图片：真上传 `samples/python/course.docx`，图落盘、HTML 里只有地址、
          每张图可取、带 `loading="lazy"`、坏附件名一律 404、库文件没被图撑大、
          图被删掉时给 404 而不是 500
  §ui     四种格式点引用都要落到那一段：Word 标在含那句话的那一段、PPT 翻到第 N 页并标那一条、
          图片按行标黄、PDF 翻页并标行；顺带验 Word 的图在界面上真画出来了

**不联网、不调模型**：临时数据目录 + 假页文字（识别组件没装也能验，除了真上传 Word 那份）。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DIST = ROOT / "frontend" / "dist"
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m11-"))
(TMP / ".env").write_text("LLM_API_KEY=sk-verify-m11-not-a-real-key\n", encoding="utf-8")
os.environ["DATA_DIR"] = str(TMP)          # 必须早于 import app
os.environ["VECTOR_ENABLED"] = "0"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, str(BACKEND))
from app.db.conn import get_conn            # noqa: E402
from app.db.migrate import init_db          # noqa: E402
from app.main import app                    # noqa: E402
from app.services import files as file_store   # noqa: E402
from app.services import pdf_pages          # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []
WARNINGS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def skip(name: str, why: str) -> None:
    WARNINGS.append(f"{name}（{why}）")
    print(f"SKIP {name}  [{why}]")


# ── 夹具 ────────────────────────────────────────────────
def _stamp() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat(timespec="seconds")


def _add_item(title: str, raw: str, ext: str, mime: str, size: int, stored: str, pages: int) -> tuple[int, int]:
    conn = get_conn()
    try:
        with conn:
            item = conn.execute(
                """INSERT INTO knowledge_item (title, source_type, raw_content, content_hash, status,
                       created_at, updated_at, kind)
                   VALUES (?, 'file', ?, ?, 'ready', ?, ?, 'material')""",
                (title, raw, f"verify-m11-{title}", _stamp(), _stamp()),
            ).lastrowid
            file_id = conn.execute(
                """INSERT INTO item_file (item_id, role, original_name, ext, mime, size,
                       stored_path, page_count, has_text_layer, ocr_status)
                   VALUES (?, 'main', ?, ?, ?, ?, ?, ?, 1, 'done')""",
                (item, f"{title}.{ext}", ext, mime, size, stored, pages),
            ).lastrowid
            conn.execute("UPDATE knowledge_item SET file_id=? WHERE id=?", (file_id, item))
    finally:
        conn.close()
    return int(item), int(file_id)


def _add_pages(item_id: int, file_id: int, pages: list[str], *, with_shot: bool = True,
               reviewed: dict[int, str] | None = None) -> None:
    from PIL import Image

    folder = pdf_pages.file_dir(file_id)
    folder.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        with conn:
            for index, text in enumerate(pages, start=1):
                rel = f"pages/{file_id}/{index:04d}.jpg" if with_shot else None
                conn.execute(
                    """INSERT INTO item_page (item_id, file_id, page_no, text, source, avg_conf,
                           line_conf, image_path, text_reviewed)
                       VALUES (?, ?, ?, ?, 'ocr', 0.96, ?, ?, ?)""",
                    (item_id, file_id, index, text, json.dumps([0.97] * max(1, text.count("\n") + 1)),
                     rel, (reviewed or {}).get(index)),
                )
                if rel:
                    Image.new("RGB", (800, 1130), (250, 249, 245)).save(folder / f"{index:04d}.jpg",
                                                                       format="JPEG")
    finally:
        conn.close()


def _add_chunk(item_id: int, content: str, position: int = 0) -> int:
    conn = get_conn()
    try:
        with conn:
            return int(conn.execute(
                "INSERT INTO chunk (item_id, position, content, source) VALUES (?, ?, ?, 'raw')",
                (item_id, position, content),
            ).lastrowid)
    finally:
        conn.close()


PDF_PAGES = [
    "第一页\n这一段只讲环境",
    "第二页\n这里开始讲引用，句子跨到下一页",
    "继续上一页的句子，到这一页收尾。\n第三页独立的一句",
] + [f"第 {n} 页\n这一页只是把页数撑起来，用来验虚拟滚动" for n in range(4, 11)]
# 跨页 chunk：起点在第 2 页，用户真正在找的那句在第 3 页
CROSS_CHUNK = "第二页 这里开始讲引用，句子跨到下一页 继续上一页的句子，到这一页收尾。"
CROSS_HINT = "到这一页收尾"

FIXTURES: dict[str, tuple[int, int]] = {}

# 假命中陷阱（2026-11-14 真样本走查逼出来的）：第 1 页重述了第 3 页那句的**前半截**，
# 而完整那段只在第 3 页。页优先的写法会落到第 1 页 —— 真讲义里这种重述到处都是。
TRAP_PAGES = [
    "第一页\n注意冒号后的格式串与变量之间用冒号分隔，这句是相似的假命中；"
    "记数都用 counts[word]=counts. 这种写法",
    "第二页\n这一页只是把页数撑起来",
    "第三页\n注意冒号后的格式串与变量之间用冒号分隔。 5. 词频统计题的标准写法："
    "counts[word]=counts.get(word,0)+1，这是完整的那一段",
]
TRAP_CHUNK = ("注意冒号后的格式串与变量之间用冒号分隔。 5. 词频统计题的标准写法："
              "counts[word]=counts.get(word,0)+1，这是完整的那一段")
# 搜索词同理：前 18 个字（`counts[word]=counts.`）第 1 页也有，整句只在第 3 页
TRAP_HINT = "counts[word]=counts.get(word,0)+1，这是完整的那一段"


def trap_fixture() -> tuple[int, int]:
    """只有文字、没有页图页数：专验「长锚点优先」，不做界面。"""
    if "trap" in FIXTURES:
        return FIXTURES["trap"]
    item, file_id = _add_item("重述陷阱讲义", "\n".join(TRAP_PAGES), "pdf", "application/pdf",
                              1024, "files/verify-m11-trap.pdf", len(TRAP_PAGES))
    _add_pages(item, file_id, TRAP_PAGES, with_shot=False)
    _add_chunk(item, TRAP_CHUNK, 0)
    FIXTURES["trap"] = (item, file_id)
    return FIXTURES["trap"]


def pdf_fixture() -> tuple[int, int]:
    """真 PDF 原件 + 10 页假文字与页图（不装识别组件也能验连续滚动）。"""
    if "pdf" in FIXTURES:
        return FIXTURES["pdf"]
    src = ROOT / "samples" / "python" / "twocol.pdf"
    item, file_id = _add_item("页图讲义", "\n".join(PDF_PAGES), "pdf", "application/pdf",
                              src.stat().st_size, "files/verify-m11-pdf.pdf", len(PDF_PAGES))
    _add_pages(item, file_id, PDF_PAGES, reviewed={4: "第四页\n这是校对之后的句子"})
    dst = TMP / "files/verify-m11-pdf.pdf"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    _add_chunk(item, CROSS_CHUNK, 0)
    _add_chunk(item, "第二页 这里开始讲引用，句子跨到下一页", 1)
    _add_chunk(item, "第三页独立的一句", 2)
    FIXTURES["pdf"] = (item, file_id)
    return FIXTURES["pdf"]


def pdf_no_file_fixture() -> tuple[int, int]:
    """有页图、没有真原件：pdf.js 必然打不开，验「退回页图」那条路。"""
    if "pdf_missing" in FIXTURES:
        return FIXTURES["pdf_missing"]
    pages = ["第一页\n没有原件的讲义", "第二页\n页图照旧能看"]
    item, file_id = _add_item("缺原件讲义", "\n".join(pages), "pdf", "application/pdf",
                              2048, "files/verify-m11-missing.pdf", len(pages))
    _add_pages(item, file_id, pages)
    FIXTURES["pdf_missing"] = (item, file_id)
    return FIXTURES["pdf_missing"]


def _mk_pptx() -> Path:
    path = TMP / "夹具deck.pptx"
    if path.exists():
        return path
    from pptx import Presentation

    deck = Presentation()
    slides = [
        ("第一章 环境", "先装 Python 3.11"),
        ("第二章 语法", "缩进就是语法结构"),
        ("第三章 引用与定位", "这句话只在第三页出现，用来验引用会不会翻页"),
    ]
    for title, bullet in slides:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = bullet
    deck.save(str(path))
    return path


def image_fixture() -> tuple[int, int]:
    """图片：真图 + 假识别结果（不装组件也能验按行标黄）。"""
    if "image" in FIXTURES:
        return FIXTURES["image"]
    text = "图片第一行\n中间这句是图片里的关键内容，用来验引用定位\n图片最后一行"
    src = ROOT / "samples" / "images" / "python_logo.png"
    item, file_id = _add_item("定位图", text, "png", "image/png", src.stat().st_size,
                              f"files/verify-m11-img.png", 1)
    _add_pages(item, file_id, [text])
    _add_chunk(item, "中间这句是图片里的关键内容，用来验引用定位")
    dst = TMP / "files/verify-m11-img.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    FIXTURES["image"] = (item, file_id)
    return FIXTURES["image"]


# ── 服务与浏览器 ────────────────────────────────────────
SERVER: dict = {}


def base_url() -> str:
    if "base" in SERVER:
        return SERVER["base"]
    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            with urllib.request.urlopen(base + "api/health", timeout=1):
                SERVER["base"] = base
                return base
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("后端没能在 30 秒内起来")


def get_json(path: str):
    with urllib.request.urlopen(base_url() + path, timeout=15) as resp:
        return json.load(resp)


def get_raw(path: str):
    with urllib.request.urlopen(base_url() + path, timeout=15) as resp:
        # 直接回 HTTPMessage（大小写不敏感）：转 dict 后 `Content-Type` 会取不到
        return resp.status, resp.headers, resp.read()


def post_file(path: Path, name: str | None = None) -> dict:
    boundary = uuid.uuid4().hex
    filename = name or path.name
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mimetypes.guess_type(filename)[0] or 'application/octet-stream'}\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        base_url() + "api/files", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def wait_done(item_id: int, timeout: float = 180.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        got = get_json(f"api/knowledge/{item_id}/ocr")
        if got.get("status") in ("done", "partial", "failed"):
            return got
        time.sleep(0.25)
    return {}


class Browser:
    """Playwright 只开一次：每组用例共用，省掉重复启动的 1–2 秒。"""

    def __init__(self) -> None:
        self.pw = None
        self.browser = None
        self.page = None
        self.errors: list[str] = []

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self.pw = sync_playwright().start()
        try:
            self.browser = self.pw.chromium.launch(channel="msedge")
        except Exception:
            self.browser = self.pw.chromium.launch()
        ctx = self.browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script("try{localStorage.setItem('cairn.setup.dismissed','1')}catch(e){}")
        self.page = ctx.new_page()
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        return self

    def __exit__(self, *_):
        for closer in (self.browser, self.pw):
            try:
                (closer.close() if closer is self.browser else closer.stop())
            except Exception:
                pass

    def open_raw(self, title: str) -> None:
        """打开内容列表里的某条，切到「原文」页签。"""
        page = self.page
        page.goto(base_url(), wait_until="networkidle")
        page.locator("aside[aria-label='内容列表'] .row").filter(has_text=title).first.click()
        page.wait_for_timeout(500)
        page.locator(".tabs").get_by_role("button", name="原文").click()

    def jump(self, phrase: str, title: str) -> None:
        """从「原文命中」点一条检索结果（引用跳转的真实入口）。"""
        page = self.page
        page.goto(base_url() + "#/ask", wait_until="networkidle")
        page.get_by_role("button", name="原文命中").click()
        box = page.locator("textarea").first
        box.fill(phrase)
        box.press("Enter")
        page.locator(".hits .hit").first.wait_for(timeout=20000)
        page.locator(".hits .hit").filter(has_text=title).first.click()
        page.locator(".tabs").get_by_role("button", name="原文").click()

    def console_clean(self, where: str) -> None:
        real = [e for e in self.errors if "favicon" not in e]
        check(f"{where}：console 没有错误", not real, " | ".join(real[:3]))
        self.errors.clear()


# ── §pdf ───────────────────────────────────────────────
def group_pdf() -> None:
    pdf_fixture()
    pdf_no_file_fixture()
    with Browser() as br:
        page = br.page
        page.goto(base_url(), wait_until="networkidle")
        started = time.monotonic()
        page.locator("aside[aria-label='内容列表'] .row").filter(has_text="页图讲义").first.click()
        page.wait_for_timeout(400)
        page.locator(".tabs").get_by_role("button", name="原文").click()
        page.wait_for_function(
            "() => { const el = document.querySelector('.pdf-view .shot');"
            " return el && el.naturalWidth > 0 }",
            timeout=20000,
        )
        first_ms = round((time.monotonic() - started) * 1000)
        check("连续滚动区在（不是单页翻页）", page.locator(".pdf-view .scroller").count() == 1)
        check(f"首屏页图 {first_ms} ms 可见（≤1000）", first_ms <= 1000, f"{first_ms} ms")
        check("页图垫底，不是白框",
              page.eval_on_selector(".pdf-view .shot", "el => el.naturalWidth") > 0)

        page.wait_for_selector(".pdf-view canvas.canvas.in", timeout=30000)
        check("pdf.js 的 canvas 盖上了",
              page.locator(".pdf-view canvas.canvas.in").count() >= 1,
              str(page.locator(".pdf-view canvas.canvas.in").count()))
        total = int(page.locator(".pdf-view .sheet").count())
        check("一开始只挂视口附近的页", total <= 5, f"挂了 {total} 页 / 共 {len(PDF_PAGES)} 页")

        page.eval_on_selector(".pdf-view .scroller", "el => el.scrollTo({ top: el.scrollHeight })")
        page.wait_for_timeout(900)
        after = int(page.locator(".pdf-view .sheet").count())
        check("滚到底依然只挂少量页（虚拟滚动生效）", after <= 6, f"滚到底挂了 {after} 页")
        check("滚到底时当前页跟着变（第 10 页）",
              "第 10 页" in page.inner_text(".pdf-view .pager"), page.inner_text(".pdf-view .pager"))
        br.console_clean("§pdf")

        # 没有真原件：pdf.js 必然打不开，必须退回页图并说清原因
        br.open_raw("缺原件讲义")
        page.wait_for_function(
            "() => document.querySelector('.pdf-view')?.innerText.includes('没能按原样画出来')",
            timeout=20000,
        )
        page.wait_for_function(
            "() => { const el = document.querySelector('.pdf-view .shot');"
            " return el && el.naturalWidth > 0 }",
            timeout=20000,
        )
        check("没有原件时退回页图，页图照旧能看",
              page.eval_on_selector(".pdf-view .shot", "el => el.naturalWidth") > 0)
        check("退回时页面文字照旧可用",
              "没有原件的讲义" in page.inner_text(".pdf-view"), page.inner_text(".pdf-view")[-40:])
        # 这条夹具**故意**没有原件，`file` 的 404 是预期的；除它之外不许有别的错
        leftover = [e for e in br.errors if "favicon" not in e and "404" not in e]
        check("退回页图：除了故意缺的原件 404，没有别的报错", not leftover, " | ".join(leftover[:3]))
        br.errors.clear()


# ── §locate ────────────────────────────────────────────
def group_locate() -> None:
    item, _ = pdf_fixture()
    conn = get_conn()
    try:
        rows = [(r["content"], int(r["id"])) for r in conn.execute(
            "SELECT id, content FROM chunk WHERE item_id=?", (item,))]
    finally:
        conn.close()
    cross = next(cid for text, cid in rows if text.startswith("第二页 这里开始讲引用"))
    page2 = next(cid for text, cid in rows
                  if text == "第二页 这里开始讲引用，句子跨到下一页")

    hit = get_json(f"api/knowledge/{item}/locate?chunk_id={cross}")
    check("跨行 chunk 能落页（不是整段 indexOf 空手而归）", hit.get("page_no") == 2, str(hit))
    check("matched 回的是原文里的那几句",
          bool(hit.get("matched")) and hit["matched"].strip() in PDF_PAGES[1], str(hit.get("matched")))

    p2 = get_json(f"api/knowledge/{item}/pages/2")
    lines = p2["text"].split("\n")
    span = lines[hit["line_from"]: hit["line_to"] + 1]
    check("行号与 pages/{n} 的 text 对齐（按 \\n 切）",
          span and hit["matched"].split("\n")[0].strip()[:8] in "".join(span),
          f"行 {hit['line_from']}–{hit['line_to']} → {span}")

    hinted = get_json(f"api/knowledge/{item}/locate?chunk_id={cross}&q={urllib.parse.quote(CROSS_HINT)}")
    check("带 q 时按搜索词落页（第 3 页，不是 chunk 起点的第 2 页）",
          hinted.get("page_no") == 3, str(hinted))
    check("带 q 时命中段就是搜索词那一段", CROSS_HINT in (hinted.get("matched") or ""),
          hinted.get("matched"))

    solo = get_json(f"api/knowledge/{item}/locate?chunk_id={page2}")
    check("只覆盖第 2 页的 chunk 落在第 2 页", solo.get("page_no") == 2, str(solo))

    # 校对优先：第 4 页的 text 是原文，text_reviewed 是校对稿
    reviewed_chunk = _add_chunk(item, "这是校对之后的句子", 9)
    rev = get_json(f"api/knowledge/{item}/locate?chunk_id={reviewed_chunk}")
    check("比对用校对后的文本（text_reviewed 优先）", rev.get("page_no") == 4, str(rev))
    old_chunk = _add_chunk(item, "第四页 这一页只是把页数撑起来", 10)
    old = get_json(f"api/knowledge/{item}/locate?chunk_id={old_chunk}")
    check("拿被校对掉的原文找不到（不会指到错的地方）", old.get("page_no") is None, str(old))

    missing = _add_chunk(item, "这段话在任何一页都不存在，纯属故意写来试探的", 11)
    gone = get_json(f"api/knowledge/{item}/locate?chunk_id={missing}")
    check("落不到页时给 page_no: null（不是 500）", gone.get("page_no") is None, str(gone))

    other, _ = image_fixture()
    wrong = get_json(f"api/knowledge/{other}/locate?chunk_id={cross}")
    check("别的内容的 chunk 不会串门", wrong.get("page_no") is None, str(wrong))

    # 长锚点优先：第 1 页有相似半句，完整那段只在第 3 页
    trap, _ = trap_fixture()
    conn = get_conn()
    try:
        trap_chunk = int(conn.execute(
            "SELECT id FROM chunk WHERE item_id=?", (trap,)).fetchone()["id"])
    finally:
        conn.close()
    got = get_json(f"api/knowledge/{trap}/locate?chunk_id={trap_chunk}")
    check("长锚点优先：完整那段在第 3 页，不被第 1 页的相似半句截胡",
          got.get("page_no") == 3, str(got)[:120])
    check("截胡时命中段也不会是那半句", "完整的那一段" in (got.get("matched") or ""),
          (got.get("matched") or "")[:60])
    hinted_trap = get_json(
        f"api/knowledge/{trap}/locate?chunk_id={trap_chunk}&q={urllib.parse.quote(TRAP_HINT)}")
    check("带 q 时整句优先（第 3 页），不被第 1 页的半截截胡",
          hinted_trap.get("page_no") == 3, str(hinted_trap)[:120])
    check("带 q 时命中段就是整句搜索词",
          TRAP_HINT in (hinted_trap.get("matched") or ""), (hinted_trap.get("matched") or "")[:60])

    try:
        get_json(f"api/knowledge/999999/locate?chunk_id={cross}")
        check("内容不存在时给 404", False, "居然 200")
    except urllib.error.HTTPError as err:
        check("内容不存在时给 404", err.code == 404, str(err.code))


# ── §assets ────────────────────────────────────────────
def ensure_docx():
    """Word 夹具：真上传一份带图讲义（只上传一次，§assets 与 §ui 共用）。"""
    if "docx" in FIXTURES:
        return FIXTURES["docx"]
    src = ROOT / "samples" / "python" / "course.docx"
    if not src.is_file():
        return None
    up = post_file(src)
    item, file_id = int(up["item_id"]), int(up["file_id"])
    FIXTURES["docx"] = (item, file_id, wait_done(item))
    return FIXTURES["docx"]


def group_assets() -> None:
    src = ROOT / "samples" / "python" / "course.docx"
    fixture = ensure_docx()
    if fixture is None:
        skip("§assets Word 内嵌图片", "缺 samples/python/course.docx")
        return
    item, file_id, got = fixture
    check("Word 抽取收口为 done", got.get("status") == "done", str(got))

    page = get_json(f"api/knowledge/{item}/pages/1")
    html = page.get("html") or ""
    imgs = re.findall(r"<img[^>]*>", html)
    check("版式里有图（图不再被丢掉）", len(imgs) >= 2, f"{len(imgs)} 张")
    check("图走本站附件地址", all(f"/api/knowledge/{item}/assets/" in tag for tag in imgs),
          imgs[0][:70] if imgs else "无图")
    check("HTML 里没有 base64 图", "data:image" not in html)
    check("每张图都带 loading=lazy", all('loading="lazy"' in tag for tag in imgs), str(len(imgs)))

    urls = [re.search(r'src="([^"]+)"', tag).group(1) for tag in imgs]
    for url in urls:
        status, headers, blob = get_raw(url[1:] if url.startswith("/") else url)
        check(f"图能取到（{url.rsplit('/', 1)[-1]}）",
              status == 200 and headers.get("Content-Type", "").startswith("image/") and len(blob) > 500,
              f"{headers.get('Content-Type')} {len(blob)} B")
        check("图片可长缓存（名字是内容哈希）",
              "max-age" in (headers.get("Cache-Control") or ""), headers.get("Cache-Control") or "无")

    folder = pdf_pages.file_dir(file_id) / "assets"
    files = sorted(folder.glob("*")) if folder.exists() else []
    check("图落在 pages/<原件>/assets/ 下", len(files) == len(urls), f"{len(files)} 个文件")
    check("盘上存的是压缩后的图（比原件小）",
          all(f.stat().st_size < src.stat().st_size for f in files),
          " · ".join(f"{f.name} {f.stat().st_size}B" for f in files))

    conn = get_conn()
    try:
        raw = conn.execute("SELECT raw_content FROM knowledge_item WHERE id=?", (item,)).fetchone()
    finally:
        conn.close()
    check("正文里没有 base64", "base64" not in (raw["raw_content"] or ""))
    db_bytes = (TMP / "data.db").stat().st_size
    check("库文件没被图撑大（图不进 SQLite）", db_bytes < 4 * 1024 * 1024, f"{db_bytes / 1024:.0f} KB")

    for bad in ("..%2F..%2Fdata.db", "data.db", "aad739989cde.jpg.exe", "%2e%2e", "x.png"):
        try:
            urllib.request.urlopen(base_url() + f"api/knowledge/{item}/assets/{bad}", timeout=5)
            check(f"坏附件名被拒（{bad}）", False, "居然 200")
        except urllib.error.HTTPError as err:
            check(f"坏附件名被拒（{bad}）", err.code in (404, 422), str(err.code))

    # 图被删掉（老内容没重新读过）时必须是 404，不能 500
    victim = files[0]
    saved = victim.read_bytes()
    victim.unlink()
    try:
        urllib.request.urlopen(base_url() + f"api/knowledge/{item}/assets/{victim.name}", timeout=5)
        check("图不在盘上时给 404（不是 500）", False, "居然 200")
    except urllib.error.HTTPError as err:
        check("图不在盘上时给 404（不是 500）", err.code == 404, str(err.code))
    finally:
        victim.write_bytes(saved)          # 还原：§ui 还要看这张图


# ── §ui ────────────────────────────────────────────────
def _docx_phrase() -> tuple[int, int, str]:
    """Word：取一段正文当搜索词（夹具由 `ensure_docx()` 准备）。"""
    item, file_id, _ = ensure_docx()
    page = get_json(f"api/knowledge/{item}/pages/1")
    phrase = ""
    for line in page["text"].split("\n"):
        line = line.strip()
        if len(line) >= 12 and not line.startswith(("#", "|")):
            phrase = line[:18]
            break
    return item, file_id, phrase


def group_ui() -> None:
    pdf_item, _ = pdf_fixture()
    image_fixture()
    _, _, docx_phrase = _docx_phrase()

    deck = _mk_pptx()
    up = post_file(deck)
    ppt_item = int(up["item_id"])
    got = wait_done(ppt_item)
    check("PPT 读完了", got.get("status") == "done", str(got))
    ppt_page3 = get_json(f"api/knowledge/{ppt_item}/pages/3")
    ppt_phrase = next(line.strip()[:18] for line in ppt_page3["text"].split("\n")
                      if len(line.strip()) >= 12)

    with Browser() as br:
        page = br.page

        br.jump(docx_phrase, "course")
        page.wait_for_selector(".docx-view .doc [data-hit='1']", timeout=25000)
        marked = page.locator(".docx-view .doc [data-hit='1']")
        check("Word：命中段标出来了", marked.count() == 1, str(marked.count()))
        check("Word：标的是含那句话的那一段", docx_phrase in (marked.first.inner_text() or ""),
              (marked.first.inner_text() or "")[:40])
        rect = marked.first.bounding_box()
        check("Word：滚进了可视区", bool(rect) and -50 <= rect["y"] < 900, str(rect))
        page.wait_for_function(
            "() => { const el = document.querySelector('.docx-view .doc img');"
            " return el && el.complete && el.naturalWidth > 0 }",
            timeout=25000,
        )
        check("Word：内嵌图片在界面上真画出来了",
              page.eval_on_selector(".docx-view .doc img", "el => el.naturalWidth") > 0)
        br.console_clean("§ui Word")

        br.jump(ppt_phrase, "夹具deck")
        page.wait_for_function(
            "() => { const el = document.querySelector('.pptx-view .pager');"
            " return el && el.innerText.includes('第 3 页') }",
            timeout=25000,
        )
        page.wait_for_selector(".pptx-view .hit", timeout=20000)
        check("PPT：翻到第 3 页", "第 3 页" in page.inner_text(".pptx-view .pager"),
              page.inner_text(".pptx-view .pager"))
        check("PPT：命中的那一条标出来了", page.locator(".pptx-view .hit").count() == 1,
              str(page.locator(".pptx-view .hit").count()))
        br.console_clean("§ui PPT")

        br.jump("中间这句是图片里的关键内容", "定位图")
        page.wait_for_selector(".image-view .line.hit", timeout=25000)
        hits = page.locator(".image-view .line.hit").all_inner_texts()
        check("图片：命中行标出来了（且只标一行）", len(hits) == 1, " | ".join(hits)[:60])
        check("图片：标的是对的那一行", any("关键内容" in h for h in hits), str(hits))
        br.console_clean("§ui 图片")

        br.jump(CROSS_HINT, "页图讲义")
        page.wait_for_function(
            "() => { const el = document.querySelector('.pdf-view .pager');"
            " return el && el.innerText.includes('第 3 页') }",
            timeout=25000,
        )
        page.wait_for_selector(".pdf-view .line.hit", timeout=20000)
        pdf_hits = page.locator(".pdf-view .line.hit").all_inner_texts()
        check("PDF：按搜索词翻到第 3 页", "第 3 页" in page.inner_text(".pdf-view .pager"),
              page.inner_text(".pdf-view .pager"))
        check("PDF：命中行标出来了", len(pdf_hits) == 1, " | ".join(pdf_hits)[:60])
        check("PDF：标的是对的那一行", any(CROSS_HINT in h for h in pdf_hits), str(pdf_hits))
        br.console_clean("§ui PDF")


GROUPS = [("pdf", group_pdf), ("locate", group_locate), ("assets", group_assets), ("ui", group_ui)]


def main() -> int:
    only: set[str] = set()
    if "--only" in sys.argv:
        raw = sys.argv[sys.argv.index("--only") + 1]
        only = {s.strip() for s in raw.split(",") if s.strip()}
        # 拼错组名不能静默什么都不跑（那会让人以为「全绿」）
        unknown = only - {name for name, _ in GROUPS}
        if unknown:
            print(f"× 没有这组：{'、'.join(sorted(unknown))}（可选：{' / '.join(n for n, _ in GROUPS)}）")
            return 2
    if not (DIST / "index.html").is_file():
        print(f"× 缺构建产物 {DIST}，先 cd frontend && npm run build")
        return 2
    print(f"Cairn M11 验收 · 临时数据目录 {TMP}")
    init_db()
    started = time.monotonic()
    for name, fn in GROUPS:
        if only and name not in only:
            continue
        print(f"§{name}")
        try:
            fn()
        except Exception:
            traceback.print_exc()
            check(f"§{name} 跑完", False, "异常中断，见上面的栈")
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS · {time.monotonic() - started:.0f} s")
    if WARNINGS:
        print(f"{len(WARNINGS)} 项 SKIP（缺样本/缺前置，不影响结论）")
        for name in WARNINGS:
            print(f"  · {name}")
    print(f"临时数据目录：{TMP}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
