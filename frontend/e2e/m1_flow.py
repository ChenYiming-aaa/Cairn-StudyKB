"""M1 端到端回归（浏览器）：粘贴 → 整理 → 改笔记 → 刷新 → 分类筛选。

这是仓库里唯一的 UI 回归，验的是「人真的能走通」，不是接口健壮性——
接口那层由 `backend/scripts/verify_m1.py` 覆盖，两者不重复。

前置（两个终端，缺一个脚本会直接退 2 并说明）：
    cd backend  && uv run uvicorn app.main:app --port 8756
    cd frontend && npm run dev

用法：
    npm run e2e                     # 等价于下面这行
    D:/Anaconda3/python.exe ../frontend/e2e/m1_flow.py

    --keep          保留截图，且不删除脚本建的条目（排障用）
    --base-url      前端地址，默认 http://localhost:5173
    --api           后端地址，默认 http://127.0.0.1:8756
    --timeout       等待整理完成的上限秒数，默认 180

环境要求：本机 Playwright 装在 Anaconda Python 下（`D:/Anaconda3/python.exe`），
backend 的 .venv 里没有它，别用 `uv run` 跑本文件。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

SHOTS = Path(__file__).with_name("_shots")
STAMP = datetime.now().strftime("%H%M%S")
MARK = f"【e2e-{STAMP}】"

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
        # 分类名是中文，必须编码，否则 urllib 直接抛 UnicodeEncodeError
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def preflight(base_url: str, api_base: str) -> str | None:
    try:
        health = api(api_base, "GET", "/api/health")
        print(f"后端 {api_base} → {health.get('status')} v{health.get('version')}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"后端不可达（{api_base}）：{exc}。先跑 `cd backend && uv run uvicorn app.main:app --port 8756`"
    try:
        with urllib.request.urlopen(base_url, timeout=10) as resp:
            if resp.status != 200:
                return f"前端返回 {resp.status}，先跑 `cd frontend && npm run dev`"
    except (urllib.error.URLError, OSError) as exc:
        return f"前端不可达（{base_url}）：{exc}。先跑 `cd frontend && npm run dev`"
    return None


def run(base_url: str, api_base: str, timeout: int, keep: bool) -> int:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(exist_ok=True)
    item_id: int | None = None
    console_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 820})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        def shot(name: str) -> None:
            page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)

        try:
            step("1/7 首屏与后端连接")
            page.goto(base_url, wait_until="domcontentloaded")
            page.wait_for_selector(".shell", timeout=15000)
            page.wait_for_selector(".conn.ok", timeout=15000)
            check("首屏渲染且顶栏显示「已连接」", page.locator(".conn").inner_text().strip() == "已连接")
            shot("01-empty")

            step("2/7 粘贴 800 字 → 列表出现待整理")
            page.locator(".topbar button.btn-primary").click()
            page.wait_for_selector(".dialog textarea", timeout=8000)
            page.locator(".dialog textarea").fill(BODY)
            page.get_by_role("button", name="加入知识库").click()
            page.wait_for_selector(".dialog", state="detached", timeout=15000)
            page.wait_for_selector(".rows li", timeout=15000)

            latest = api(api_base, "GET", "/api/knowledge", params={"page_size": 1})["items"][0]
            item_id = latest["id"]
            check("库中新建了条目且状态 pending", latest["status"] == "pending", f"id={item_id}")
            check("列表首行就是刚粘贴的条目", page.locator(".rows li").first.inner_text().find(latest["title"]) >= 0)
            first_badge = page.locator(".rows li").first.locator(".badge").inner_text().strip()
            check("列表徽标显示「待整理」", first_badge == "待整理", first_badge)
            shot("02-pending")

            step("3/7 整理（真实 LLM）→ 就绪")
            page.locator(".rows li").first.locator(".row").click()
            page.wait_for_selector(".detail-head", timeout=10000)
            page.get_by_role("button", name="开始整理").click()
            deadline = time.time() + timeout
            status = ""
            while time.time() < deadline:
                badge = page.locator(".meta .badge")
                status = badge.inner_text().strip() if badge.count() else ""
                if status in ("就绪", "失败"):
                    break
                page.wait_for_timeout(1000)
            check(f"整理在 {timeout}s 内结束且状态为就绪", status == "就绪", status or "超时")

            detail = api(api_base, "GET", f"/api/knowledge/{item_id}")
            for field in ("title", "category", "summary", "key_points", "structured_note"):
                value = detail.get(field)
                check(f"字段 {field} 非空", bool(value), f"{len(value)} 字" if isinstance(value, str) else str(value))
            check("标题是 AI 生成的短标题（≤20 字）", 0 < len(detail["title"]) <= 20, detail["title"])
            check("AI 标题已覆盖占位标题", MARK not in detail["title"], detail["title"])
            check("摘要面板渲染出内容", len(page.locator(".summary").inner_text()) > 20)
            check("关键点至少 3 条", page.locator(".points li").count() >= 3, f"{page.locator('.points li').count()} 条")
            shot("03-ready")

            step("4/7 分类树出现该分类，点击后列表被过滤")
            category = detail["category"]
            page.wait_for_selector(".tree .group", timeout=10000)
            node = page.locator(".tree .node", has_text=category).first
            check("左侧出现新分类", node.count() > 0, category)
            node.click()
            page.wait_for_timeout(1200)
            expected = api(api_base, "GET", "/api/knowledge",
                           params={"category": category, "page_size": 1})["total"]
            rows = page.locator(".rows li").count()
            check("列表只剩该分类条目", rows == expected, f"页面 {rows} / 接口 {expected}")
            check("顶栏条目总数来自后端聚合", page.locator(".tree .node.root .count").inner_text().strip()
                  == str(api(api_base, "GET", "/api/knowledge/categories")["counts"]["total"]))
            shot("04-filtered")

            step("5/7 编辑结构化笔记并保存")
            page.locator(".tree .node.root").click()
            page.wait_for_timeout(800)
            page.locator(".rows li").first.locator(".row").click()
            page.wait_for_selector(".detail-head", timeout=10000)
            page.get_by_role("button", name="结构化笔记").click()
            editor = page.locator(".pane-note textarea")
            editor.wait_for(timeout=8000)
            before = editor.input_value()
            check("笔记编辑器带出了 AI 生成的笔记", len(before) > 50, f"{len(before)} 字")
            editor.fill(before + f"\n\n- e2e 追加标记 {STAMP}")
            page.get_by_role("button", name="保存笔记").click()
            page.wait_for_selector(".toast", timeout=15000)
            check("保存后出现提示", "已保存" in page.locator(".toast").first.inner_text())
            shot("05-note-saved")

            page.reload(wait_until="domcontentloaded")
            page.wait_for_selector(".rows li", timeout=15000)
            page.locator(".rows li").first.locator(".row").click()
            page.wait_for_selector(".detail-head", timeout=10000)
            page.get_by_role("button", name="结构化笔记").click()
            page.wait_for_timeout(600)
            after = page.locator(".pane-note textarea").input_value()
            check("刷新后笔记内容仍在", f"e2e 追加标记 {STAMP}" in after)
            check("详情出现「笔记已手改」标记", page.locator(".chip-edit").count() > 0)
            note_rows = api(api_base, "GET", f"/api/knowledge/{item_id}")["chunks"]
            check("笔记已进 chunk（可被检索）",
                  any(c["source"] == "note" for c in note_rows), f"{len(note_rows)} 块")
            shot("06-after-reload")

            step("6/7 console 无报错")
            real_errors = [e for e in console_errors if "favicon" not in e.lower()]
            check("浏览器 console 无 error", not real_errors, f"{len(real_errors)} 条：{real_errors[:2]}")

            step("7/7 清理")
            if keep:
                print(f"    [SKIP] --keep：保留条目 {item_id} 与截图 {SHOTS}")
            else:
                api(api_base, "DELETE", f"/api/knowledge/{item_id}")
                gone = api(api_base, "GET", "/api/knowledge", params={"page_size": 1})["items"]
                check("测试条目已删除", all(i["id"] != item_id for i in gone))
                item_id = None  # 已删，finally 不再重复
        except Exception as exc:  # 任何一步炸掉都要留下现场，否则排障只能靠猜
            shot("99-failure")
            check(f"流程异常终止：{type(exc).__name__}", False, str(exc)[:200])
        finally:
            # 中途失败也要清掉自己造的条目，否则知识库里会慢慢堆测试垃圾
            if item_id and not keep:
                try:
                    api(api_base, "DELETE", f"/api/knowledge/{item_id}")
                    print(f"    [清理] 已删除中途失败的测试条目 {item_id}")
                except Exception as exc:
                    print(f"    [WARN] 清理条目 {item_id} 失败：{type(exc).__name__}")
            if keep:
                print(f"截图：{SHOTS}")
            else:
                for png in SHOTS.glob("*.png"):
                    png.unlink(missing_ok=True)
                SHOTS.rmdir() if SHOTS.exists() and not any(SHOTS.iterdir()) else None
            browser.close()

    passed = sum(1 for ok, _ in CHECKS if ok)
    print("\n" + "=" * 62)
    print(f"  结果：{passed}/{len(CHECKS)} PASS")
    print("=" * 62)
    return 0 if passed == len(CHECKS) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 端到端回归")
    parser.add_argument("--base-url", default="http://localhost:5173")
    parser.add_argument("--api", default="http://127.0.0.1:8756")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    print(f"唯一标记：{MARK}")
    problem = preflight(args.base_url, args.api)
    if problem:
        print(f"\n[前置未满足] {problem}")
        return 2
    return run(args.base_url, args.api, args.timeout, args.keep)


if __name__ == "__main__":
    sys.exit(main())
