"""一次性冒烟：把本轮改动的交互真点一遍（不提交、不联网、不调模型）。

覆盖：
  1. 知识库「今日」条 → 点「待整理」落到已筛选的列表（不是未筛选首页）
  2. 今天条在同一路由只改 query 也会重载（这是 watch 那条）
  3. 仪表盘「今日待整理」卡带同样条件
  4. 复习页行上的出处可点，点了回知识库并选中那条内容
  5. 复习页「待人工判断」页签在有待判题时出现，行上有「算我对 / 算我错」
  6. 引导页「稍后再说」：提示指向「还差一步」，且**不再**触发组件下载
"""
from __future__ import annotations

import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(r"C:/Users/cwqjk/Desktop/知识库agent开发/backend")
ROOT = BACKEND.parent
DIST = ROOT / "frontend" / "dist"
TMP = Path(tempfile.mkdtemp(prefix="cairn-smoke-ui-"))
(TMP / ".env").write_text("LLM_API_KEY=sk-smoke-not-a-real-key\n", encoding="utf-8")
os.environ["DATA_DIR"] = str(TMP)
os.environ["VECTOR_ENABLED"] = "0"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, str(BACKEND))

from app.db.conn import get_conn          # noqa: E402
from app.db.migrate import init_db        # noqa: E402
from app.main import app                  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))


def seed() -> None:
    init_db()
    now = datetime.now().astimezone().replace(microsecond=0)
    conn = get_conn()
    try:
        for title in ("待整理甲", "待整理乙", "待整理丙"):
            conn.execute(
                """INSERT INTO knowledge_item
                   (title, source_type, raw_content, content_hash, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (title, "text", f"{title} 的正文。", f"h-{title}", "pending",
                 now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
            )
        cur = conn.execute(
            """INSERT INTO knowledge_item
               (title, source_type, raw_content, content_hash, summary, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("已整理丁", "text", "已整理丁 的正文。", "h-ready", "这是一条已经整理好的内容。",
             "ready", now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
        )
        item_id = int(cur.lastrowid)
        # 两道题：一道今天到期（答错过），一道待人工判断
        q1 = conn.execute(
            """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
               VALUES (?,?,?,?,?,?)""",
            (item_id, "short", "normal",
             '{"question": "间隔重复为什么有效？", "answer": "因为每次回忆都在加固路径"}',
             "fp-due", now.isoformat(timespec="seconds")),
        ).lastrowid
        conn.execute(
            """INSERT INTO quiz_attempt
               (question_id, user_answer, is_correct, feedback, duration_ms, created_at)
               VALUES (?,?,?,?,?,?)""",
            (q1, "忘了", 0, "答错了", 1000, now.isoformat(timespec="seconds")),
        )
        conn.execute(
            """INSERT INTO review_item
               (question_id, due_at, interval_days, lapses, last_result, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (q1, (now - timedelta(hours=1)).astimezone(timezone.utc).isoformat(timespec="seconds"),
             1, 1, 0, now.isoformat(timespec="seconds")),
        )
        q2 = conn.execute(
            """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
               VALUES (?,?,?,?,?,?)""",
            (item_id, "short", "normal",
             '{"question": "费曼技巧的第一步是什么？", "answer": "用大白话复述"}',
             "fp-pending", now.isoformat(timespec="seconds")),
        ).lastrowid
        conn.execute(
            """INSERT INTO quiz_attempt
               (question_id, user_answer, is_correct, feedback, duration_ms, created_at)
               VALUES (?,?,?,?,?,?)""",
            (q2, "复述", None, "模型超时", 1000, now.isoformat(timespec="seconds")),
        )
        conn.commit()
        print(f"  种子：4 条内容（3 待整理 + 1 已整理）· 1 题到期 · 1 题待判")
    finally:
        conn.close()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            with urllib.request.urlopen(base + "api/health", timeout=1):
                return server, base
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("服务没起来")


def wait(page, fn, timeout=6000):
    """等一个条件成立（异步动作刚返回时别急着断言）。"""
    step = 100
    spent = 0
    while spent < timeout:
        try:
            if fn():
                return True
        except Exception:
            pass
        page.wait_for_timeout(step)
        spent += step
    return False


def main() -> int:
    if not (DIST / "index.html").exists():
        print("× 先 cd frontend && npm run build")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("× 没装 playwright")
        return 2

    seed()
    port = free_port()
    server, base = start_server(port)
    install_calls: list[str] = []

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge")
            except Exception:
                browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script("try{localStorage.setItem('cairn.setup.dismissed','1')}catch(e){}")
            page = ctx.new_page()
            page.on("request", lambda r: install_calls.append(r.url) if "/components/" in r.url
                    and r.method == "POST" else None)
            errors: list[str] = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            # ── 1/2 今日条：点「待整理」落到已筛选的列表 ──
            page.goto(base, wait_until="networkidle")
            btn = page.locator('button[aria-label^="待整理"]').first
            check(btn.count() > 0, "今日条有独立的「待整理」按钮")
            if btn.count():
                btn.click()
                ok = wait(page, lambda: page.locator(".status-filter .row.on").count() > 0)
                check(ok, "点「待整理」后状态筛选真的落在「待整理」上",
                      page.locator(".status-filter .row.on").inner_text() if ok else "没落上")
                rows = page.locator(".list-body .item-row, .list-body li").count()
                check(rows == 3, f"列表只剩 3 条待整理（实得 {rows}）")
                check("/?status=pending" not in page.url, "用完把 query 清掉（地址栏不留旧条件）", page.url)

            # ── 3 仪表盘卡 ──
            page.goto(base + "#/dashboard", wait_until="networkidle")
            page.locator(".card.link").first.click()
            page.wait_for_timeout(600)
            on = page.locator(".status-filter .row.on").count()
            check(on >= 1, "仪表盘「今日待整理」卡带了筛选条件")

            # ── 4 复习页：出处可点，回知识库并选中 ──
            page.goto(base + "#/review", wait_until="networkidle")
            wait(page, lambda: page.locator(".row-link").count() > 0)
            link = page.locator(".row-link").first
            check(link.count() > 0, "复习行上的出处是按钮")
            if link.count():
                check("已整理丁" in link.inner_text(), "出处写着来源标题", link.inner_text())
                link.click()
                ok = wait(page, lambda: page.locator(".detail .title-input, .detail h1").count() > 0)
                title = page.locator(".detail .title-input, .detail h1").first.input_value() \
                    if page.locator(".detail .title-input").count() else \
                    page.locator(".detail h1").first.inner_text()
                check(ok and "已整理丁" in title, "点出处回知识库并选中了那条内容", f"{page.url} · {title}")

            # ── 5 待人工判断页签 ──
            page.goto(base + "#/review", wait_until="networkidle")
            wait(page, lambda: page.locator(".tab", has_text="待人工判断").count() > 0)
            tab = page.locator(".tab", has_text="待人工判断")
            check(tab.count() > 0, "有待判题时出现「待人工判断」页签")
            if tab.count():
                tab.first.click()
                ok = wait(page, lambda: page.locator("button", has_text="算我对").count() > 0)
                check(ok, "待判行上有「算我对」可点")

            # ── 6 引导页「稍后再说」 ──
            install_calls.clear()
            page.goto(base + "#/setup", wait_until="networkidle")
            later = page.locator("button", has_text="稍后再说").first
            check(later.count() > 0, "引导页有「稍后再说」")
            if later.count():
                later.click()
                got = wait(page, lambda: page.locator(".toast").count() > 0)
                text = page.locator(".toast").first.inner_text() if got else ""
                check("还差一步" in text, "「稍后再说」指向真实存在的入口", text)
                page.wait_for_timeout(1200)
                check(not install_calls, "「稍后再说」不再顺手触发下载",
                      "、".join(install_calls) or "无安装请求")
                check(page.url.rstrip("/").endswith(":") is False and "setup" not in page.url,
                      "退出引导页回到知识库", page.url)

            check(not errors, "console 没有错误", " | ".join(errors[:3]))
            browser.close()
    except Exception:
        traceback.print_exc()
        check(False, "脚本自身没崩", traceback.format_exc().splitlines()[-1])
    finally:
        server.should_exit = True

    print()
    for ok, name, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    bad = sum(1 for ok, _, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - bad}/{len(RESULTS)} PASS")
    print(f"临时数据目录：{TMP}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
