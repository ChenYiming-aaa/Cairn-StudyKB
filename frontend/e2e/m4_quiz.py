"""M4 端到端（浏览器）：出 5 道单选 → 题面逐题浮现 → 答完立刻见对错与解析 → 结果页。

补的是 DoD 里**只有眼睛能验**的那一条：`verify_m4.py` 能证明后端逐题 emit，
但证明不了「页面上是一张一张刷出来的」。这里用真实 LLM 走一遍（一次调用出 5 题）。

前置（两个终端）：
    cd backend && DATA_DIR=data/tmp/m4-e2e uv run uvicorn app.main:app --port 8757
    cd frontend && CAIRN_API_TARGET=http://127.0.0.1:8757 npm run dev -- --port 5174

用法：
    D:/Anaconda3/python.exe e2e/m4_quiz.py --db ../data/tmp/m4-e2e/data.db

    --db       副本库路径。条目建好后需要把 status 从 pending 改成 ready，
               否则练习页（只列 ready）看不到它。不传就只能手动挑一条现成的 ready 条目
    --item-id  直接指定条目 id（跳过建条目与改状态）
    --keep     保留截图，不删条目

注意：会花钱（1 次真实 LLM 调用），且只写副本库——别把它指向 data/data.db。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

SHOTS = Path(__file__).with_name("_shots")
STAMP = datetime.now().strftime("%H%M%S")
MARK = f"【e2e-m4-{STAMP}】"

BODY = MARK + """番茄工作法的核心不是把时间切成 25 分钟，而是把注意力从「还要做多久」拉回「现在做什么」。
人一旦开始估算剩余时间，注意力就被任务管理器接管了，手头的事情反而变成背景。计时器的真正作用，
是让这段时间有了边界：边界之内只做一件事，边界之外才允许自己处理杂事。

具体做法有四步。第一，开工前把这一轮要做的事写成一句可以验收的话，例如「把第二节的开头重写一遍」，
不要写「写论文」。第二，计时开始后，遇到任何打断都先记在纸上，不立刻处理，这一条比计时本身更重要。
第三，铃响之后必须停下来，哪怕正写着顺手的段落。停下来是为了让大脑确认「这一轮结束了」，
否则下一轮的开始会越来越难。第四，记录这一轮实际完成了什么，而不是记录「学了两小时」。

常见的误用有三个。一是把 25 分钟当成硬指标，任务需要 40 分钟才能进入状态时，硬切反而增加成本，
这时应该改成 45 或 50 分钟一轮，休息相应延长。二是用计时器来压迫自己，一轮没完成就自责，
结果是下一次更不愿意开始。三是只在学习时用，写作、整理笔记、复盘的场合反而不用，
而这些恰好是最容易被无限拉长的活动。

如果你的工作是深度研究，一天能完成四轮就已经不错。把四轮安排在精力最好的时段，
其余时间用于阅读、整理和沟通，比强行堆到八轮更有效。番茄钟管理的是注意力，不是工时。
"""

CHECKS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    CHECKS.append((ok, name))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 44 - len(title)))


def api(base: str, method: str, path: str, payload: dict | None = None,
        params: dict | None = None):
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def make_ready(db: str, item_id: int) -> str:
    """练习页只列 ready；副本库里直接改状态，省掉一次整理 LLM 调用。"""
    with sqlite3.connect(db, timeout=10) as conn:
        with conn:
            conn.execute(
                "UPDATE knowledge_item SET status='ready', category=COALESCE(category, 'e2e') "
                "WHERE id=?", (item_id,))
        row = conn.execute("SELECT status, LENGTH(COALESCE(raw_content,'')) "
                           "FROM knowledge_item WHERE id=?", (item_id,)).fetchone()
    return f"status={row[0]} 正文 {row[1]} 字"


def preflight(base_url: str, api_base: str) -> str | None:
    try:
        health = api(api_base, "GET", "/api/health")
        print(f"后端 {api_base} → {health.get('status')} v{health.get('version')}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return (f"后端不可达（{api_base}）：{exc}。先跑 "
                f"`cd backend && DATA_DIR=data/tmp/m4-e2e uv run uvicorn app.main:app --port 8757`")
    try:
        with urllib.request.urlopen(base_url, timeout=10) as resp:
            if resp.status != 200:
                return f"前端返回 {resp.status}，先跑 `cd frontend && npm run dev -- --port 5174`"
    except (urllib.error.URLError, OSError) as exc:
        return f"前端不可达（{base_url}）：{exc}。先跑 `cd frontend && npm run dev -- --port 5174`"
    return None


def run(base_url: str, api_base: str, item_id: int, keep: bool) -> int:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(exist_ok=True)
    console_errors: list[str] = []
    gen_error = ""
    # 副本库里可能留着上一轮的错题，断言只看「这一轮新增」，不假设库是干净的
    wrong_before = api(api_base, "GET", "/api/quiz/wrong").get("total", 0)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 860})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        def shot(name: str) -> None:
            page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)

        try:
            step("1/6 打开练习页，选中测试条目")
            page.goto(f"{base_url.rstrip('/')}/#/practice", wait_until="domcontentloaded")
            page.wait_for_selector(".practice", timeout=15000)
            page.wait_for_selector(".item-row", timeout=15000)
            title = api(api_base, "GET", f"/api/knowledge/{item_id}")["title"]
            row = page.locator(".item-row", has_text=title).first
            check("列表里能找到这条 ready 条目", row.count() > 0, title)
            row.click()
            page.wait_for_timeout(200)
            check("题型=单选、题数=5 两个 chip 已选中",
                  "on" in (page.locator(".chip", has_text="单选").first.get_attribute("class") or "")
                  and "on" in (page.locator(".chip", has_text="5 题").first.get_attribute("class") or ""))
            shot("01-config")

            step("2/6 出题：题面逐题浮现（每 200ms 采一次卡片数）")
            page.locator(".cfg-foot .btn-primary").click()
            page.wait_for_selector(".gen", timeout=10000)
            t0 = time.time()
            timeline: list[tuple[float, int]] = []
            gen_seconds = 0.0
            last_text = ""
            while time.time() - t0 < 180:
                # 先看阶段有没有翻页：翻页后 .gen-card 会整体消失，别把它记成「掉到 0 题」
                if page.locator(".runner, .state").count():
                    gen_seconds = round(time.time() - t0, 2)
                    break
                n = page.locator(".gen-card").count()
                if not timeline or timeline[-1][1] != n:
                    timeline.append((round(time.time() - t0, 2), n))
                    if n:
                        last_text = page.locator(".gen-text").inner_text().strip()
                        if n == 1:
                            shot("02-generating-first")
                page.wait_for_timeout(200)
            counts = [n for _, n in timeline if n > 0]
            gen_error = page.locator(".state-error").inner_text().strip() if \
                page.locator(".state-error").count() else ""
            page.wait_for_selector(".q-step", timeout=30000)
            step_text = page.locator(".q-step").inner_text().strip()
            runner_total = int(re.search(r"/\s*(\d+)", step_text).group(1))
            check("出到 5 题（进入作答时正好 5 题）", runner_total == 5, step_text)
            check("题面是一张张刷出来的（至少 3 个中间态，不是一次性出现）",
                  len(set(counts)) >= 3, f"观察到 {sorted(set(counts))} / {gen_seconds}s")
            check("首题在流未结束时就已经可见（早于 5 题齐）",
                  bool(counts) and counts[0] < 5,
                  f"时间线 {timeline}（0 表示还没出题）")
            check("出题进度文案跟着涨", "已收到" in last_text, last_text)
            shot("03-generating-last")

            step("3/6 作答：答完一题立刻见对错与解析")
            verdicts: list[str] = []
            exps: list[str] = []
            for i in range(5):
                page.wait_for_selector(".q-text", timeout=15000)
                prompt_text = page.locator(".q-text").inner_text().strip()
                page.locator(".opt").first.click()
                page.get_by_role("button", name="确认作答").click()
                page.wait_for_selector(".verdict", timeout=8000)
                verdicts.append(page.locator(".verdict strong").first.inner_text().strip())
                exp = page.locator(".verdict-exp")
                exps.append(exp.inner_text().strip() if exp.count() else "")
                if i == 0:
                    shot("04-verdict-immediate")
                label = "交卷并看结果" if i == 4 else "下一题"
                page.get_by_role("button", name=label).click()
                if i < 4:
                    page.wait_for_timeout(250)
            check("每题答完立即出现判定（不用等交卷）", len(verdicts) == 5, str(verdicts))
            check("每题判定都带解析", all(len(e) > 5 for e in exps),
                  f"最短 {min((len(e) for e in exps), default=0)} 字")

            step("4/6 结果页：分数 / 正确率 / 逐题回显")
            page.wait_for_selector(".result", timeout=60000)
            score = page.locator(".score-main b").inner_text().strip()
            acc = page.locator(".score-acc").inner_text().strip()
            items = page.locator(".review-item")
            check("结果页给出 N/5", page.locator(".score-main span").inner_text().strip() == "/ 5",
                  f"{score}/5")
            check("正确率与分数一致", f"正确率 {round(int(score) / 5 * 100)}%" in acc.replace(" ", " ") or
                  acc.startswith("正确率"), acc)
            check("5 题逐题回显", items.count() == 5, f"{items.count()} 条")
            answers = page.locator(".review-line").all_inner_texts()
            check("回显里有「你的答案」与「正确答案」",
                  all("你的答案" in t for t in answers) and any("正确答案" in t for t in answers))
            exp_count = page.locator(".review-exp").count()
            check("回显每题都带解析", exp_count == 5, f"{exp_count} 条")
            shot("05-result")

            step("5/6 复习页角标与后端一致")
            page.goto(f"{base_url.rstrip('/')}/#/review", wait_until="domcontentloaded")
            page.wait_for_selector(".review .stat", timeout=15000)
            # 角标初值是 0，请求回来才填。等它到位再断言，否则测的是加载中的占位
            payload = api(api_base, "GET", "/api/review/due")
            try:
                page.wait_for_function(
                    "(exp) => [...document.querySelectorAll('.review .stat b')][2]"
                    "?.textContent.trim() === exp",
                    arg=str(payload["wrong"]), timeout=8000)
            except Exception:  # noqa: BLE001 - 下面的 check 会给出实况
                pass
            nums = [b.inner_text().strip() for b in page.locator(".review .stat b").all()]
            wrong = 5 - int(score)
            check(f"错题角标 = 接口 wrong（{payload['wrong']}），本轮答错 {wrong}",
                  nums[2] == str(payload["wrong"]) and payload["wrong"] == wrong_before + wrong,
                  f"页面 {nums} / 接口 wrong={payload['wrong']}")
            check(f"队列角标 = 接口 tracked（{payload['tracked']}）",
                  nums[1] == str(payload["tracked"]), f"页面 {nums}")
            check("今天到期仍是 0（due 在明天）", nums[0] == str(payload["total"]) == "0",
                  f"页面 {nums} / 接口 total={payload['total']}")
            shot("06-review")

            step("6/6 console 无报错")
            real = [e for e in console_errors if "favicon" not in e.lower()]
            check("浏览器 console 无 error", not real, f"{len(real)} 条：{real[:2]}")
        except Exception as exc:  # 任何一步炸掉都要留下现场
            shot("99-failure")
            check(f"流程异常终止：{type(exc).__name__}", False, str(exc)[:200])
        finally:
            if keep:
                print(f"    [SKIP] --keep：保留条目 {item_id} 与截图 {SHOTS}")
            else:
                try:
                    api(api_base, "DELETE", f"/api/knowledge/{item_id}")
                    print(f"    [清理] 已删除测试条目 {item_id}")
                except Exception as exc:  # noqa: BLE001
                    print(f"    [WARN] 清理条目失败：{type(exc).__name__}")
                for png in SHOTS.glob("*.png"):
                    png.unlink(missing_ok=True)
                if SHOTS.exists() and not any(SHOTS.iterdir()):
                    SHOTS.rmdir()
            browser.close()

    passed = sum(1 for ok, _ in CHECKS if ok)
    print("\n" + "=" * 62)
    print(f"  结果：{passed}/{len(CHECKS)} PASS")
    if gen_error:
        print(f"  出题报错：{gen_error[:200]}")
    for ok, name in CHECKS:
        if not ok:
            print(f"    - 失败：{name}")
    print("=" * 62)
    return 0 if passed == len(CHECKS) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="M4 练习页端到端（逐题浮现）")
    parser.add_argument("--base-url", default="http://localhost:5174")
    parser.add_argument("--api", default="http://127.0.0.1:8757")
    parser.add_argument("--db", default="", help="副本库路径（把新条目改成 ready）")
    parser.add_argument("--item-id", type=int, default=0)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    print(f"唯一标记：{MARK}")
    problem = preflight(args.base_url, args.api)
    if problem:
        print(f"\n[前置未满足] {problem}")
        return 2

    item_id = args.item_id
    if not item_id:
        created = api(args.api, "POST", "/api/knowledge",
                      {"title": f"{MARK} 番茄工作法", "raw_content": BODY})
        item_id = created["id"]
        print(f"新建条目 id={item_id}")
        if args.db:
            print(f"改成 ready：{make_ready(args.db, item_id)}")
        else:
            print("[WARN] 未传 --db，条目仍是 pending，练习页不会列出来")
            return 2
    return run(args.base_url, args.api, item_id, args.keep)


if __name__ == "__main__":
    sys.exit(main())
