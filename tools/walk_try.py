"""试用页走查：拿真 Key 在浏览器里把三步跑完（会真的花 token）。

**为什么单独一条**：`tools/walk_demo.py` 验的是静态演示（预置数据、不发请求），
而「自带 Key 直连」这条路只有真发一次请求才知道通不通 —— CORS 头、预检、
`response_format` 不被支持、流式与非流式的差别，全都写在服务端行为里，
离线夹具一条都验不出来。2026-11-14 就是这么发现智谱不给网页直连的。

它花的钱：4 次调用、约 3.3k token（整理 1 + 问答 1 + 出题 1 + 连通性测试 1）。
所以默认不跑在 CI 里，改过 `demo/llm.js`、`demo/useTry.js`、提示词或路由时手动跑一次。

用法：
    cd frontend && VITE_DEMO=1 npx vite build --base=./ --outDir dist-demo
    python tools/walk_try.py                    # Key 从项目根 .env 的 LLM_API_KEY 读
    python tools/walk_try.py --key sk-xxx       # 或直接给
    python tools/walk_try.py --url https://chenyiming-aaa.github.io/Cairn-StudyKB/
    python tools/walk_try.py --headful          # 看着它点

退出码：0 全绿 / 1 有 FAIL / 2 环境不满足（缺 Key / 缺 dist-demo / 缺 Playwright）
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from walk_demo import DIST, ROOT, SHOTS, Report, serve

BASE_PATH = "#/try"
KEY_INPUT = "input[placeholder='sk-…']"


def read_key() -> str:
    env = ROOT / ".env"
    if not env.is_file():
        return ""
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("LLM_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def until(page, cond, limit: int = 90, step: float = 1.0) -> bool:
    """等到 cond() 为真；条件里带上「这步没成功」之类的失败文案由调用方判断。"""
    for _ in range(limit):
        if cond():
            return True
        page.wait_for_timeout(int(step * 1000))
    return False


def body_of(page) -> str:
    return page.inner_text("body")


def run(base: str, key: str, headful: bool) -> Report:
    rep = Report()
    with sync_playwright_ctx() as pw:
        browser = launch(pw, headful)
        page = browser.new_context(viewport={"width": 1440, "height": 1100}).new_page()
        logs: list[str] = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: logs.append(f"reqfail: {r.url[:110]} {r.failure}"))

        page.goto(base + BASE_PATH, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        rep.check("试用页打得开", page.locator("input.q, " + KEY_INPUT).count() > 0 or "试用" in body_of(page))

        # ① 连接：预设已经填好 base / model，只差 Key
        page.fill(KEY_INPUT, key)
        page.wait_for_timeout(200)
        t0 = time.time()
        page.get_by_role("button", name="试试能不能连上").click()
        page.wait_for_timeout(1000)
        until(page, lambda: any(s in body_of(page) for s in ("通了", "没成功", "Key 不对", "额度")), limit=60)
        # 连上后第 1 步会自动收起，绿色 pill 才是成功标志（提示语一起被藏了）
        pill_ok = page.locator(".pill.ok").count() > 0
        used = "1 次调用" in body_of(page)
        rep.check("① 连得上（浏览器直连）", pill_ok or used,
                  f"pill={'有' if pill_ok else '无'} 已调用={'是' if used else '否'} · {time.time() - t0:.0f} s")
        page.screenshot(path=str(SHOTS / "t1-conn.png"))
        if not (pill_ok or used):
            page.screenshot(path=str(SHOTS / "t1-conn-fail.png"))
            browser.close()
            rep.errors = logs
            return rep

        # ② 示例材料 → 整理
        page.get_by_role("button", name="用示例材料").click()
        page.wait_for_timeout(600)
        t0 = time.time()
        page.get_by_role("button", name="整理成笔记").click()
        page.wait_for_timeout(1500)
        until(page, lambda: page.locator(".note").count() > 0 or any(
            s in body_of(page) for s in ("这步没成功", "再点一次")))
        page.screenshot(path=str(SHOTS / "t2-note.png"))
        rep.check("② 整理出了结果卡", page.locator(".note").count() > 0, f"{time.time() - t0:.0f} s")
        if page.locator(".note").count():
            title = page.locator(".note .title").first.inner_text()
            # 模型偶尔自带「标题：」前缀，长度放宽到 24 字仍能挡住「把整段塞进标题」
            rep.check("② 标题是人写的（非空、≤24 字）", 0 < len(title) <= 24, repr(title))
            rep.check("② 有笔记正文", page.locator(".note .body").count() > 0)
            print("   标题:", title)
            print("   摘要:", page.locator(".note .summary").first.inner_text()[:80])

        # ③ 追问。
        # 模型偶尔会按 ask.md 规则 2 回「知识库中没有找到相关内容」—— 那是产品有意的防线，
        # 不是这条链断了（2026-11-14 对照实测约 17%，与材料段带不带标题无关）。
        # 像真人一样再问一遍，两次都回退才算真有问题。
        FALLBACK = "知识库中没有找到相关内容"

        def ask_once() -> str:
            page.fill("input.q", "切片左闭右开是什么意思？举例说明")
            page.get_by_role("button", name="问一句").click()
            page.wait_for_timeout(2000)
            until(page, lambda: page.locator(".answer").count() > 0 or "这步没成功" in body_of(page))
            got = page.locator(".answer .body")
            return got.first.inner_text() if got.count() else ""

        t0 = time.time()
        answer = ask_once()
        retried = FALLBACK in answer and not page.locator(".answer .body .cite").count()
        if retried:
            answer = ask_once()
        page.screenshot(path=str(SHOTS / "t3-answer.png"))
        rep.check("③ 问答出了回答", bool(answer.strip()),
                  f"{time.time() - t0:.0f} s" + ("（第一次回退，问了第二遍）" if retried else ""))
        # 角标是 `<button class="cite">2</button>`，方括号由模板拆掉，所以不能拿 innerText 里
        # 「有没有 [」当判据 —— 回答里出现 `s[1:4]` 这类代码就把断言骗过去了（第一版就这么错的）
        n_cite = page.locator(".answer .body .cite").count()
        rep.check("③ 回答里挂着可点的引用角标", n_cite > 0, f"{n_cite} 个")
        if not n_cite and FALLBACK in answer:
            rep.check("③ 不是两次都回退（模型侧偶发，链路无关）", False, "换个问法再跑")
        if answer:
            print("   回答前 100 字:", answer[:100].replace("\n", " "))
            if n_cite:
                page.locator(".answer .body .cite").first.click()
                page.wait_for_timeout(600)
                rep.check("③ 点角标能摊出那段材料", page.locator(".answer .source").count() > 0)
                page.screenshot(path=str(SHOTS / "t4-cite.png"))

        # ④ 出题
        t0 = time.time()
        page.get_by_role("button", name="出 3 道题并自测").click()
        page.wait_for_timeout(2000)
        until(page, lambda: page.locator(".quiz .q").count() > 0 or "这步没成功" in body_of(page))
        page.screenshot(path=str(SHOTS / "t5-quiz.png"))
        n_q = page.locator(".quiz .q").count()
        rep.check("④ 出了题", n_q > 0, f"{n_q} 道 · {time.time() - t0:.0f} s")
        if n_q:
            page.locator(".quiz .q").first.locator(".opt").first.click()
            page.wait_for_timeout(700)
            rep.check("④ 选项能作答并判分", page.locator(".verdict").count() > 0)
            page.screenshot(path=str(SHOTS / "t6-quiz-answered.png"))

        # ⑤ 用量：证明「每次点都是真调用」不是句空话
        m = re.search(r"(\d+) 次调用 · 输入 (\d+) / 输出 (\d+) token", body_of(page))
        rep.check("⑤ 累计用量有显示", bool(m), m.group(0) if m else "")
        browser.close()

    for line in logs:
        low = line.lower()
        # favicon 404 与浏览器扩展噪音不算问题
        if "favicon" in low:
            continue
        if line.startswith("pageerror") or line.startswith("reqfail") or low.startswith("error"):
            rep.errors.append(line)
    return rep


def sync_playwright_ctx():
    from playwright.sync_api import sync_playwright

    return sync_playwright()


def launch(pw, headful: bool):
    kwargs = {"headless": not headful}
    if not headful:
        try:
            return pw.chromium.launch(channel="msedge", **kwargs)
        except Exception:
            pass
    return pw.chromium.launch(**kwargs)


def main() -> int:
    ap = argparse.ArgumentParser(description="试用页真 Key 走查（会花 token）")
    ap.add_argument("--url", default="", help="跑线上地址；不给就起本地服务")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--key", default="", help="不给就读项目根 .env 的 LLM_API_KEY")
    ap.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    args = ap.parse_args()

    key = args.key or read_key()
    if not key:
        print("× 没有 Key：项目根 .env 里没 LLM_API_KEY，也没给 --key")
        return 2
    print(f"用 Key（前 6 位 {key[:6]}…），这次会真花约 3.3k token")

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

    rep = run(base, key, args.headful)
    print(f"\n截图：{SHOTS}")
    if rep.errors:
        print(f"页面错误 {len(rep.errors)} 条：")
        for line in rep.errors[:10]:
            print("   ", line[:170])
    else:
        print("页面没有错误")
    if rep.fail:
        print(f"\n{len(rep.fail)} 条 FAIL：", rep.fail)
        return 1
    print("\n全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
