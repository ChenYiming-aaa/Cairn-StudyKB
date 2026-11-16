"""一次性冒烟：把本轮改动的交互真点一遍（不提交、不联网、不调模型）。

覆盖（批 1–8 里凡是「脚本能看出来」的）：
  M1  今日条「待整理」落到已筛选列表；同一路由只改 query 也会重载
  M1  仪表盘「今日待整理」卡带同样条件
  M4  复习行上的出处可点，点了回知识库并选中那条内容
  M3  引导页「稍后再说」：指向「还差一步」，且**不再**触发组件下载
  H2  库 >50 条时出现「仅显示前 50 条，共 M 条」，小结果集不出现
  M2  没装向量组件时，进检索页**搜索前**就有降级提示
  H3  后台刷新不清屏：笔记改动、草稿、页签都不丢；F5 后草稿回来并能放弃
  H4  批量移入：一条成功一条失败时给出汇总句，失败项仍留在勾选里
  L4  整理中且还没摘要 → 说「正在生成摘要…」，不说「下面是上一版」
  L1  练习页没有可出题内容 → 空态带「去知识库」按钮
  H5  待判题「算我错」→ 行变 ✗、待判列表清空（GET /review/pending total=0）

没覆盖的（脚本看不出，只能真机看）：H4 的按钮禁用态与「移到中 3/20」文字（请求在本地
几毫秒就回，抓不到中间态）、H3 的 PDF 页位（要真 PDF 与一屏高度）、L2 的越界引用（要模型
真吐出 [9]）、H1 的重读（要识别组件与长文档）。
"""
from __future__ import annotations

import json
import os
import re
import socket
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
# 开发机上本机装了 sentence_transformers，`components.resolve()` 会如实报 local（真能用），
# 于是「没装组件」这个场景根本造不出来。用组件服务自带的验收开关模拟一台干净机器。
os.environ["CAIRN_COMPONENT_MODE"] = "none"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, str(BACKEND))

from app.db.conn import get_conn          # noqa: E402
from app.db.migrate import init_db        # noqa: E402
from app.main import app                  # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []

# 种子里那几条要按 id 认的东西（列表按 id DESC，新插的排前面，所以测试里一律靠搜索定位）
SEED: dict[str, int] = {}
RESERVE = 120          # 让「第 51 条之后」这个问题真实存在


def check(ok: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))


def _add_item(conn, title: str, status: str, summary: str | None, now: datetime,
              category: str = "") -> int:
    cur = conn.execute(
        """INSERT INTO knowledge_item
           (title, source_type, raw_content, content_hash, summary, category, status,
            created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (title, "text", f"{title} 的正文。", f"h-{title}", summary, category, status,
         now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
    )
    return int(cur.lastrowid)


def seed() -> None:
    init_db()
    now = datetime.now().astimezone().replace(microsecond=0)
    stamp = now.isoformat(timespec="seconds")
    conn = get_conn()
    try:
        for title in ("待整理甲", "待整理乙", "待整理丙"):
            _add_item(conn, title, "pending", None, now)
        SEED["ready"] = _add_item(conn, "已整理丁", "ready", "这是一条已经整理好的内容。", now)
        # L4 用：正在整理、但这一轮还没产出摘要（第一次整理的常态）
        SEED["organizing"] = _add_item(conn, "整理中戊", "organizing", None, now)
        # H2 用：把库撑过 50 条
        for i in range(1, RESERVE + 1):
            _add_item(conn, f"批量甲{i:03d}", "ready", f"第 {i} 条储备内容的摘要。", now, "储备")

        item_id = SEED["ready"]
        # 两道题：一道今天到期（答错过），一道待人工判断
        q1 = conn.execute(
            """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
               VALUES (?,?,?,?,?,?)""",
            (item_id, "short", "normal",
             '{"question": "间隔重复为什么有效？", "answer": "因为每次回忆都在加固路径"}',
             "fp-due", stamp),
        ).lastrowid
        conn.execute(
            """INSERT INTO quiz_attempt
               (question_id, user_answer, is_correct, feedback, duration_ms, created_at)
               VALUES (?,?,?,?,?,?)""",
            (q1, "忘了", 0, "答错了", 1000, stamp),
        )
        conn.execute(
            """INSERT INTO review_item
               (question_id, due_at, interval_days, lapses, last_result, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (q1, (now - timedelta(hours=1)).astimezone(timezone.utc).isoformat(timespec="seconds"),
             1, 1, 0, stamp),
        )
        q2 = conn.execute(
            """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
               VALUES (?,?,?,?,?,?)""",
            (item_id, "short", "normal",
             '{"question": "费曼技巧的第一步是什么？", "answer": "用大白话复述"}',
             "fp-pending", stamp),
        ).lastrowid
        conn.execute(
            """INSERT INTO quiz_attempt
               (question_id, user_answer, is_correct, feedback, duration_ms, created_at)
               VALUES (?,?,?,?,?,?)""",
            (q2, "复述", None, "模型超时", 1000, stamp),
        )
        SEED["pending_q"] = int(q2)
        conn.commit()
        print(f"  种子：{RESERVE + 5} 条内容（3 待整理 + 1 已整理 + 1 整理中 + 储备）"
              f"· 1 题到期 · 1 题待判")
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


def hold(page, ms, fn) -> tuple[bool, str]:
    """在 ms 时间里持续采样：任何一刻 fn() 为假就算失败。

    「刷新时不许闪骨架屏」这种断言不能只看某一瞬间 —— 骨架屏就是一闪而过的东西，
    事后看一眼永远是「没有」。
    """
    spent = 0
    while spent < ms:
        ok, why = fn()
        if not ok:
            return False, why
        page.wait_for_timeout(200)
        spent += 200
    return True, ""


def search_item(page, title: str) -> None:
    box = page.locator('input[aria-label="搜索标题"]')
    box.fill(title)
    wait(page, lambda: page.locator(".row-title", has_text=title).count() > 0)


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
    # 1-1 之后「启动时把残留的 organizing 一律放回 pending」：种子里那条「整理中戊」
    # 会在服务起来那一刻被回收，于是 L4 拿到的是「还没整理」、待整理列表还多一条。
    # 这行为是对的（重启后不可能有任务在跑），所以素材要等服务起来之后再摆。
    conn = get_conn()
    try:
        with conn:
            conn.execute("update knowledge_item set status='organizing' where id=?",
                         (SEED["organizing"],))
    finally:
        conn.close()
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

            # ── 7 H2：超过 50 条时把「只显示了一部分」说清楚 ──
            page.goto(base, wait_until="networkidle")
            trunc = page.locator(".list-truncated")
            ok = wait(page, lambda: trunc.count() > 0)
            text = trunc.first.inner_text() if ok else ""
            check(ok and bool(re.search(r"仅显示前 50 条，共 \d+ 条", text)),
                  "库 >50 条时说明「前 N / 共 M」", text or "没出现")
            # 小结果集不该出现（不在正常的库上制造焦虑）
            page.locator('button[aria-label^="待整理"]').first.click()
            wait(page, lambda: page.locator(".status-filter .row.on").count() > 0)
            page.wait_for_timeout(500)
            check(page.locator(".list-truncated").count() == 0,
                  "结果只有 3 条时不出现截断说明")

            # ── 8 M2：没装向量组件，搜索**之前**就说清 ──
            page.goto(base + "#/ask", wait_until="networkidle")
            hint = page.locator(".hint-line")
            ok = wait(page, lambda: hint.count() > 0, timeout=8000)
            hint_text = hint.first.inner_text() if ok else ""
            check(ok and "关键词" in hint_text, "进检索页就有降级提示（不必等搜完）", hint_text or "没有提示")
            check(ok and page.locator(".hint-btn").count() > 0,
                  "降级提示旁有「去安装」入口")

            # ── 9 H3：后台刷新不吃草稿 ──
            page.goto(base, wait_until="networkidle")
            search_item(page, "已整理丁")
            page.locator(".row-title", has_text="已整理丁").first.click()
            wait(page, lambda: page.locator(".tab", has_text="整理笔记").count() > 0)
            page.locator(".tab", has_text="整理笔记").first.click()
            ta = page.locator(".pane-note textarea")
            wait(page, lambda: ta.count() > 0)
            marker = "这半页笔记还没保存"
            ta.first.fill(f"原来的一段笔记。\n{marker}")
            ok = wait(page, lambda: page.locator(".dirty").count() > 0)
            check(ok, "改笔记后出现「已修改」标记")

            # 「整理中戊」让整理轮询每 2.5 s 触发一次 refreshAll —— 用户没点，系统自己刷
            def still_there():
                if page.locator(".detail-loading").count() > 0:
                    return False, "详情区闪了骨架屏"
                value = page.locator(".pane-note textarea").first.input_value() \
                    if page.locator(".pane-note textarea").count() else ""
                if marker not in value:
                    return False, "笔记草稿被刷新吃掉了"
                if page.locator(".dirty").count() == 0:
                    return False, "「已修改」标记丢了"
                return True, ""

            survived, why = hold(page, 6000, still_there)
            check(survived, "后台刷新 6 秒内草稿、标记、详情区都保住", why)

            # F5 之后草稿要从会话存储里回来
            page.reload(wait_until="networkidle")
            search_item(page, "已整理丁")
            page.locator(".row-title", has_text="已整理丁").first.click()
            wait(page, lambda: page.locator(".tab", has_text="整理笔记").count() > 0)
            page.locator(".tab", has_text="整理笔记").first.click()
            ok = wait(page, lambda: page.locator(".pane-note textarea").count() > 0)
            value = page.locator(".pane-note textarea").first.input_value() if ok else ""
            restored = page.locator(".restored")
            check(ok and marker in value, "刷新页面后草稿回来了", value[:40])
            check(restored.count() > 0, "草稿回来时明确标「恢复了一份没保存的草稿」")
            if restored.count():
                restored.locator("button", has_text="放弃改动").click()
                gone = wait(page, lambda: marker not in page.locator(".pane-note textarea").first.input_value())
                check(gone and page.locator(".restored").count() == 0,
                      "「放弃改动」把草稿和标记一起清掉")

            # ── 9b H3 的第三处清理：内容被删了，草稿不能留在会话里 ──
            doomed_id = None
            conn = get_conn()
            try:
                row = conn.execute(
                    "SELECT id FROM knowledge_item WHERE title = ?", ("批量甲002",)).fetchone()
                doomed_id = int(row["id"]) if row else None
            finally:
                conn.close()
            if doomed_id:
                page.goto(base, wait_until="networkidle")
                search_item(page, "批量甲002")
                page.locator(".row-title", has_text="批量甲002").first.click()
                wait(page, lambda: page.locator(".tab", has_text="整理笔记").count() > 0)
                page.locator(".tab", has_text="整理笔记").first.click()
                wait(page, lambda: page.locator(".pane-note textarea").count() > 0)
                page.locator(".pane-note textarea").first.fill("这条马上要被删掉，残稿不该留下")
                key = f"cairn.note.draft.{doomed_id}"
                written = wait(page, lambda: page.evaluate(
                    "(k) => Boolean(sessionStorage.getItem(k))", key))
                check(written, "改动先落进了会话存储")

                req = urllib.request.Request(base + f"api/knowledge/{doomed_id}", method="DELETE")
                with urllib.request.urlopen(req, timeout=5):
                    pass
                # 整理轮询每 2.5 s 刷新一次详情 → 那条已经 404 → 顺手清掉草稿与阅读位置
                cleaned = wait(page, lambda: not page.evaluate(
                    "(k) => Boolean(sessionStorage.getItem(k))", key), timeout=10000)
                check(cleaned, "内容被删后，它留下的草稿不再留在会话里")
            else:
                check(False, "没找到用来删的那条内容")

            # ── 10 H4：批量移入，一条成一条败 ──            page.goto(base, wait_until="networkidle")
            search_item(page, "批量甲01")
            picks = page.locator(".pick")
            wait(page, lambda: picks.count() >= 2)
            picks.nth(0).check()
            picks.nth(1).check()
            bar = page.locator(".bulk")
            ok = wait(page, lambda: bar.count() > 0)
            check(ok and "已选 2 条" in bar.inner_text(), "勾两条后出现「已选 2 条」",
                  bar.inner_text() if ok else "没出现")

            injected = {"n": 0}

            def fail_first_patch(route, request):
                # 只拦 PATCH（同一个模式也匹配 GET 列表请求），第一条改工作区的请求人为打回
                if request.method == "PATCH" and injected["n"] == 0:
                    injected["n"] += 1
                    route.fulfill(status=500, content_type="application/json",
                                  body=json.dumps({"error": {"code": "INTERNAL",
                                                             "message": "注入的失败"}}))
                    return
                if request.method == "PATCH":
                    injected["n"] += 1
                route.continue_()

            ctx.route("**/api/knowledge/**", fail_first_patch)
            page.locator(".bulk button", has_text="移到").first.click()
            got = wait(page, lambda: page.locator(".toast").count() > 0, timeout=8000)
            toast_text = page.locator(".toast").first.inner_text() if got else ""
            check(got and re.search(r"成功 1 条，1 条没移成", toast_text),
                  "一条失败时给出「成功 1 条，1 条没移成」", toast_text or "没有提示")
            page.wait_for_timeout(400)
            left = bar.inner_text() if bar.count() else ""
            check("已选 1 条" in left, "没移成的那条仍留在勾选里", left or "勾选被清空了")
            ctx.unroute("**/api/knowledge/**")
            if bar.count():
                bar.locator("button", has_text="取消").click()

            # ── 11 L4：整理中且还没有摘要 ──
            page.goto(base, wait_until="networkidle")
            search_item(page, "整理中戊")
            page.locator(".row-title", has_text="整理中戊").first.click()
            wait(page, lambda: page.locator(".detail h1, .detail .title-input").count() > 0)
            page.wait_for_timeout(400)
            pane = page.locator(".pane")
            pane_text = pane.first.inner_text() if pane.count() else ""
            check("正在生成摘要" in pane_text, "整理中且没摘要时说「正在生成摘要…」", pane_text[:60])
            check("下面是上一版" not in pane_text, "没有上一版时不说「下面是上一版」", pane_text[:60])

            # ── 12 L1：练习页没有可出题的内容 ──
            page.goto(base + "#/practice", wait_until="networkidle")
            kw = page.locator('input[placeholder="搜标题…"]')
            wait(page, lambda: kw.count() > 0)
            kw.fill("没有这种标题zzz")
            kw.press("Enter")
            empty = page.locator(".cfg-empty")
            ok = wait(page, lambda: empty.count() > 0, timeout=8000)
            check(ok, "练习页空态出现了")
            go_kb = empty.locator("button", has_text="去知识库")
            check(go_kb.count() > 0, "练习页空态带「去知识库」按钮")
            if go_kb.count():
                go_kb.click()
                check(wait(page, lambda: "practice" not in page.url), "点「去知识库」真的离开练习页", page.url)

            # ── 13 H5：把「待判」判成错，之后待判列表里就没有它了 ──
            page.goto(base + "#/review", wait_until="networkidle")
            page.locator(".tab", has_text="待人工判断").first.click()
            wrong = page.locator("button", has_text="算我错").first
            ok = wait(page, lambda: wrong.count() > 0)
            if ok:
                wrong.click()
                # 待判列表判完是**整行消失**（不是就地变 ✗ —— 那是交卷结果页的形态）
                gone = wait(page, lambda: page.locator(".row-pending").count() == 0)
                check(gone, "判完那一行从待判列表消失")
                empty_state = page.locator(".state", has_text="没有待人工判断的题")
                check(empty_state.count() > 0, "判空后给「没有待人工判断的题」的空态")
                with urllib.request.urlopen(base + "api/review/pending", timeout=5) as resp:
                    total = json.loads(resp.read().decode("utf-8")).get("total")
                check(total == 0, "判完之后它从待判列表消失（不复活）", f"total={total}")
            else:
                check(False, "待判行上有「算我错」")

            # 两条资源错误都是本脚本自己造的：H4 注入的 500、9b 删掉那条后浏览器去取它的 404。
            # 它们不是「界面报错」，别让它们顶掉真正的 console 检查。
            errors[:] = [e for e in errors
                         if "500 (Internal Server Error)" not in e
                         and "404 (Not Found)" not in e]
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
