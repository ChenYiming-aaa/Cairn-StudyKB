"""M7 验收脚本（T7.7）：布局 + 文案一次过完。

用法：
    cd frontend && npm run build          # 必须：本脚本测的是后端吐的 dist
    cd backend && uv run python scripts/verify_m7.py
    cd backend && uv run python scripts/verify_m7.py --shots ../docs/images
        --shots 顺带重拍 README 的 10 张界面图（覆盖同名文件）

退出码：0 全绿 / 1 有用例失败 / 2 环境不满足（缺 dist、缺浏览器）

覆盖（M7 §4 T7.7 的六条，加上一页两处文案细节）：
  1. 左栏默认只显示 8 个标签 chip
  2. 点「显示全部」后 chip 数 = 接口返回的标签总数
  3. Ctrl+B 折叠后左栏 ≤ 48px，刷新后仍 ≤ 48px
  4. 拖拽手柄改宽后刷新仍保持
  5. 条目列表收起后详情区域变宽
  6. 逐页 innerText 不出现 `docs/dev/文案规范.md` §6 的禁止词
  7. 两个搜索框的 placeholder / aria-label 可区分（S-12）
  8. 设置窗口四个 tab 的可见文案同样过禁止词
  9. 选中分类后状态计数收窄到该类（分类树仍是全库）、点「全部条目」回到全库
 10. 分类手风琴：展开第二个分类时第一个自动收起
 11. 导图请求带主题 id 与明暗，不同主题产出不同配色
 12. 徽标文字与背景的实测对比度 ≥ 4.5（AA 小字）
 13. 学习页预览有深色外框（白底是刻意的「一张纸」）

**不联网、不调模型**：起一个临时数据目录 + 种子库（13 分类 / 59 个不同标签 / 34 条），
所有请求都打在 127.0.0.1 的本进程上。
"""
from __future__ import annotations

import json
import os
import re
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
from urllib.parse import quote

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DIST = ROOT / "frontend" / "dist"
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m7-"))
# 给一个假的 Key：只看「配好了」的界面（顶栏不该挂黄条），绝不发起模型调用
(TMP / ".env").write_text("LLM_API_KEY=sk-verify-m7-not-a-real-key\n", encoding="utf-8")
os.environ["DATA_DIR"] = str(TMP)          # 必须早于 import app
os.environ["VECTOR_ENABLED"] = "0"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.pop("LLM_API_KEY", None)

sys.path.insert(0, str(BACKEND))

from app.db.conn import get_conn            # noqa: E402
from app.db.migrate import init_db          # noqa: E402
from app.main import app                    # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []

# 文案规范 §6：逐页 innerText 扫描。只放「不可能出现在用户内容里」的词，
# 免得把左侧分类树里的真实标签误判成违规。
FORBIDDEN = [
    "暂无数据", "内容项", "资料库", "刷题", "背题",
    "结构化", "处理中", "AI 生成", "大模型", "LLM",
    "pending", "ready", "推理强度", "reasoning",
    "已派发", "内容已存在", "可以随时从顶栏的「环境」",
]

# ── 种子数据 ──────────────────────────────────────────────────

PLAN = [
    ("学习方法", ["间隔重复", "费曼技巧", "主动回忆", "刻意练习", "复盘", "框架思维", "输出倒逼", "类比"],
     ["费曼技巧：用输出倒逼输入", "间隔重复的复习节奏", "主动回忆为什么比重读有效", "刻意练习的四个条件"]),
    ("时间管理", ["番茄工作法", "时间块", "优先级", "任务拆解", "缓冲时间", "记录耗时"],
     ["番茄工作法的正确用法", "时间块：把一天切成可执行单元", "优先级不是排序，是取舍"]),
    ("写作方法", ["结构", "初稿", "修改", "读者视角", "标题", "案例"],
     ["先搭骨架再填内容", "初稿不要一边写一边改", "读者视角检查清单"]),
    ("记忆方法", ["遗忘曲线", "艾宾浩斯", "记忆宫殿", "间隔", "检索练习", "线索"],
     ["遗忘曲线说了什么", "记忆宫殿怎么搭", "间隔重复的三个误区"]),
    ("前端工程化", ["构建", "依赖管理", "Lint", "模块化", "缓存", "打包体积"],
     ["构建工具到底解决什么问题", "依赖管理的三条纪律", "Lint 不是风格警察"]),
    ("持续集成", ["流水线", "灰度", "回滚", "缓存", "并行"],
     ["流水线的最小可用形态", "灰度发布与回滚"]),
    ("科技人物", ["传记", "访谈", "决策", "方法论"],
     ["从传记里读决策", "访谈里的方法论"]),
    ("测试方法", ["评测集", "回归", "幻觉", "边界条件", "抽样"],
     ["评测集怎么建", "回归测试的边界", "幻觉检查清单"]),
    ("阅读方法", ["主题阅读", "速读", "精读", "摘录"],
     ["主题阅读：一次读五本", "速读的前提是熟悉领域"]),
    ("笔记系统", ["双链", "标签体系", "日记", "索引"],
     ["双链笔记的适用边界", "标签体系别超过三层"]),
    ("效率工具", ["快捷键", "自动化", "模板", "批量处理"],
     ["快捷键是肌肉记忆", "自动化的边际收益"]),
    ("数据分析", ["指标口径", "可视化", "样本", "趋势"],
     ["指标口径先对齐", "可视化不是装饰"]),
    ("语言学习", ["影子跟读", "单词卡", "语法", "输出", "听力"],
     ["影子跟读法怎么练", "单词卡的正确用法", "输出先于语法"]),
]

FAMOUS = {
    "费曼技巧：用输出倒逼输入": (
        "费曼技巧的核心不是「讲一遍」，而是逼自己找到讲不通的地方。能用平实的语言讲清一件事，"
        "说明结构已经在脑子里了；讲不顺，问题就暴露在那一句上。",
        ["用大白话复述，卡住的地方就是没懂的地方", "回到原文只补那一段，不要整篇重读",
         "换一个完全不懂的听众再讲一次", "留下讲稿，下次复习先看讲稿再看原文"],
        "# 费曼技巧\n\n## 核心动作\n\n### 复述\n用大白话讲一遍，录音更好。\n\n### 找卡点\n"
        "讲不顺的句子就是知识缺口。\n\n## 常见误用\n\n### 背话术\n背下来的解释经不起追问。\n\n"
        "### 只讲一次\n隔一周再讲，才知道有没有留下。\n",
    ),
}

STATUS_CYCLE = ["pending"] * 9 + ["organizing"] * 2 + ["ready"] * 40
TOTAL_ITEMS = sum(len(titles) for _, _, titles in PLAN)


def seed() -> None:
    """13 分类 / 59 个不同标签 / 34 条条目 + 复习队列 + 今日专注。"""
    init_db()
    now = datetime.now().astimezone().replace(microsecond=0)
    statuses = STATUS_CYCLE
    conn = get_conn()
    try:
        idx = 0
        first_id = None
        for cat, tags, titles in PLAN:
            for i, title in enumerate(titles):
                # 第一条（费曼）固定 ready：截图与详情断言要看到摘要与导图
                status = "ready" if idx == 0 else statuses[(idx - 1) % len(statuses)]
                idx += 1
                summary, points, note = FAMOUS.get(title, (None, None, None))
                created = (now - timedelta(minutes=(TOTAL_ITEMS - idx) * 20)).isoformat(timespec="seconds")
                cur = conn.execute(
                    """INSERT INTO knowledge_item
                       (title, source_type, raw_content, content_hash, summary, key_points,
                        structured_note, category, tags, status, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        title, "text",
                        f"{title}。这是验收用的种子正文，长度足够让详情页与导图有内容可显示。"
                        f"分类：{cat}；标签：{'、'.join(tags[:2])}。",
                        f"verify-m7-{cat}-{i}", summary,
                        json.dumps(points, ensure_ascii=False) if points else None,
                        note, cat,
                        json.dumps([tags[i % len(tags)], tags[(i + 3) % len(tags)]], ensure_ascii=False),
                        status, created, created,
                    ),
                )
                item_id = cur.lastrowid
                if first_id is None:
                    first_id = item_id
                conn.execute(
                    "INSERT INTO chunk (item_id, position, content, source) VALUES (?,0,?, 'raw')",
                    (item_id, f"{title} 的正文片段。"),
                )
                if note:
                    conn.execute(
                        "INSERT INTO chunk (item_id, position, content, source) VALUES (?,0,?, 'note')",
                        (item_id, note),
                    )

        # 复习队列：两题到期、一题明天；再留一条答错记录给错题本
        due_utc = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        quiz = [
            ("关于「费曼技巧」，下面哪一句最接近它的核心动作？",
             ["用大白话复述，卡住的地方就是缺口", "把原文抄一遍", "只看目录", "背下所有术语"],
             ["A"], "复述会逼出没懂的地方，抄写不会。"),
            ("间隔重复最需要控制的是什么？",
             ["复习间隔随熟练度拉长", "每天读一遍同样的内容", "一次学满四小时", "只复习最近学的"],
             ["A"], "间隔要随掌握程度变长，堆时间不解决问题。"),
        ]
        for n, (text, options, answer, why) in enumerate(quiz, start=1):
            payload = {"question": text, "options": options, "answer": answer, "explanation": why}
            cur = conn.execute(
                """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (first_id, "single", "basic", json.dumps(payload, ensure_ascii=False),
                 f"verify-m7-q{n}", now.isoformat(timespec="seconds")),
            )
            qid = cur.lastrowid
            conn.execute(
                """INSERT INTO review_item (question_id, due_at, interval_days, lapses, last_result, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (qid, due_utc, 2 + n, 1, 0, now.isoformat(timespec="seconds")),
            )
            conn.execute(
                """INSERT INTO quiz_attempt (question_id, user_answer, is_correct, feedback, duration_ms, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (qid, json.dumps(["B"], ensure_ascii=False), 0, None, 8000,
                 (now - timedelta(days=2)).isoformat(timespec="seconds")),
            )

        # 今日 + 本周专注，让仪表盘的条形图不是空的
        for days_ago, seconds in ((0, 1500), (0, 900), (1, 1500), (3, 1500)):
            start = now - timedelta(days=days_ago, minutes=30)
            conn.execute(
                """INSERT INTO study_session
                   (target_type, target_id, start_time, end_time, duration_seconds,
                    planned_seconds, status, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                ("free", None, start.isoformat(timespec="seconds"),
                 (start + timedelta(seconds=seconds)).isoformat(timespec="seconds"),
                 seconds, 1500, "done", "验收种子", start.isoformat(timespec="seconds")),
            )
        conn.commit()
    finally:
        conn.close()


# ── 起一个真的后端 ────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_server(port: int):
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}/"
    for _ in range(120):
        try:
            with urllib.request.urlopen(base + "api/health", timeout=1):
                return server, base
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("后端没能在 30 秒内起来")


def get_json(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        return json.load(resp)


def get_text(base: str, path: str) -> str:
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        return resp.read().decode("utf-8")


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((bool(ok), name, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def width_of(page, selector: str) -> int:
    return page.evaluate(
        "s => { const el = document.querySelector(s); return el ? Math.round(el.getBoundingClientRect().width) : -1 }",
        selector,
    )


def scan_text(page, where: str) -> list[str]:
    text = page.inner_text("body")
    return [word for word in FORBIDDEN if word in text]


def main() -> int:
    shots = None
    if "--shots" in sys.argv:
        shots = Path(sys.argv[sys.argv.index("--shots") + 1]).resolve()
        shots.mkdir(parents=True, exist_ok=True)

    if not (DIST / "index.html").exists():
        print("× 找不到 frontend/dist/index.html —— 先 cd frontend && npm run build")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("× 没装 playwright —— cd backend && uv add playwright && uv run playwright install chromium")
        return 2

    seed()
    port = free_port()
    server, base = start_server(port)

    tree = get_json(base, "api/knowledge/categories")
    all_tags = {tag["name"] for cat in tree["categories"] for tag in cat["tags"]}
    total_items = tree["counts"]["total"]
    print(f"种子库：{total_items} 条 / {len(tree['categories'])} 分类 / {len(all_tags)} 个标签\n")

    errors: list[str] = []
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge")
            except Exception:
                browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script("try{localStorage.setItem('cairn.setup.dismissed','1')}catch(e){}")
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))

            page.goto(base, wait_until="networkidle")
            page.wait_for_selector(".today-bar")
            page.wait_for_timeout(400)

            # ── 1 / 2 左栏标签云 ─────────────────────────────
            chips = page.locator("aside[aria-label='知识库导航'] .chips .chip")
            count = chips.count()
            check("左栏默认只显示 8 个标签 chip", count == 8, f"{count} 个")
            if shots:
                page.screenshot(path=str(shots / "01-knowledge.png"))

            more = page.locator("aside[aria-label='知识库导航'] .more")
            more.click()
            page.wait_for_timeout(300)
            after = chips.count()
            check("点「显示全部」后 = 接口返回的标签总数", after == len(all_tags),
                  f"{after} / {len(all_tags)}")
            check("按钮变成「收起」", "收起" in more.inner_text(), more.inner_text())
            more.click()
            page.wait_for_timeout(200)
            check("再点一次回到 8 个", chips.count() == 8, str(chips.count()))

            # ── 9 状态计数跟筛选走（2026-11-10）───────────────
            status_total = page.locator("aside[aria-label='知识库导航'] .status-filter .row").first
            total_before = int(status_total.locator(".count").inner_text())
            cats = page.locator("aside[aria-label='知识库导航'] .cat")
            cat_name = cats.nth(0).locator(".node .label").first.inner_text()
            cats.nth(0).locator(".node").first.click()
            page.wait_for_timeout(600)
            total_after = int(
                page.locator("aside[aria-label='知识库导航'] .status-filter .row")
                .first.locator(".count").inner_text()
            )
            scoped = get_json(
                base, f"api/knowledge/categories?category={quote(cat_name)}"
            )
            check("选中分类后状态计数收窄到该类",
                  total_after == scoped["counts"]["total"] and total_after < total_before,
                  f"{total_before} → {total_after}（接口 {scoped['counts']['total']}）")
            check("分类树本身仍是全库", len(scoped["categories"]) == len(tree["categories"]),
                  f"{len(scoped['categories'])} / {len(tree['categories'])}")

            # ── 10 分类手风琴（同时只展开一个）───────────────
            check("点分类会展开它的标签", cats.nth(0).locator(".tags").count() == 1)
            cats.nth(1).locator(".caret-btn").click()
            page.wait_for_timeout(300)
            check("展开第二个分类后第一个自动收起",
                  cats.nth(0).locator(".tags").count() == 0)
            page.locator("aside[aria-label='知识库导航'] .status-filter .row").first.click()
            page.wait_for_timeout(500)
            back = int(
                page.locator("aside[aria-label='知识库导航'] .status-filter .row")
                .first.locator(".count").inner_text()
            )
            check("点「全部条目」后计数回到全库", back == total_before, f"{back} / {total_before}")

            # ── 7 两个搜索框能区分（S-12）────────────────────
            side_box = page.locator("aside[aria-label='知识库导航'] input[type='search']")
            list_box = page.locator("aside[aria-label='条目列表'] input[type='search']")
            side_ph = side_box.get_attribute("placeholder")
            list_ph = list_box.get_attribute("placeholder")
            check("左栏搜索框是「筛选分类或标签」", side_ph == "筛选分类或标签", str(side_ph))
            check("列表搜索框是「搜索条目标题」", list_ph == "搜索条目标题", str(list_ph))
            check("两个 placeholder 不相同", side_ph != list_ph)
            check("列表搜索框 aria-label 不省略",
                  list_box.get_attribute("aria-label") == "搜索条目标题")

            # ── 3 Ctrl+B 折叠 + 刷新保持 ──────────────────────
            page.keyboard.press("Control+b")
            page.wait_for_timeout(400)
            folded = width_of(page, "aside[aria-label='知识库导航']")
            check("Ctrl+B 后左栏 ≤ 48px", 0 < folded <= 48, f"{folded}px")
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(500)
            check("刷新后仍 ≤ 48px", width_of(page, "aside[aria-label='知识库导航']") <= 48,
                  f"{width_of(page, 'aside[aria-label=\"知识库导航\"]')}px")
            check("窄条里有「待整理」入口", page.locator("aside[aria-label='知识库导航'] .rail-btn").count() >= 3)

            # ── 4 拖拽改宽 + 刷新保持 ─────────────────────────
            page.locator(".topbar").get_by_role("button", name="展开左栏").click()
            page.wait_for_timeout(400)
            before = width_of(page, "aside[aria-label='知识库导航']")
            handle = page.locator("aside[aria-label='知识库导航'] .split-handle")
            box = handle.bounding_box()
            page.mouse.move(box["x"] + 4, box["y"] + 260)
            page.mouse.down()
            page.mouse.move(box["x"] + 44, box["y"] + 260, steps=6)
            page.mouse.up()
            page.wait_for_timeout(300)
            dragged = width_of(page, "aside[aria-label='知识库导航']")
            check("拖手柄 +40 左右改宽", 30 <= dragged - before <= 50, f"{before} → {dragged}")
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(400)
            check("宽度刷新后保持", abs(width_of(page, "aside[aria-label='知识库导航']") - dragged) < 2,
                  f"{width_of(page, 'aside[aria-label=\"知识库导航\"]')}px")
            page.locator("aside[aria-label='知识库导航'] .split-handle").dblclick()
            page.wait_for_timeout(300)
            check("双击手柄回到 232", abs(width_of(page, "aside[aria-label='知识库导航']") - 232) < 3,
                  f"{width_of(page, 'aside[aria-label=\"知识库导航\"]')}px")

            # ── 5 列表收起 → 详情变宽 ─────────────────────────
            detail_before = width_of(page, ".detail")
            page.keyboard.press("Control+Shift+b")
            page.wait_for_timeout(400)
            list_w = width_of(page, "aside[aria-label='条目列表']")
            detail_after = width_of(page, ".detail")
            check("Ctrl+Shift+B 把列表收到 0", list_w == 0, f"{list_w}px")
            check("列表收起后详情变宽", detail_after > detail_before + 200,
                  f"{detail_before} → {detail_after}")
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(400)
            check("列表收起态刷新后保持", width_of(page, "aside[aria-label='条目列表']") == 0,
                  f"{width_of(page, 'aside[aria-label=\"条目列表\"]')}px")
            page.locator(".topbar").get_by_role("button", name="展开列表").click()
            page.wait_for_timeout(400)

            # ── 6 逐页禁止词 ─────────────────────────────────
            routes = [
                ("/", "知识库"),
                ("/#/ask", "检索"),
                ("/#/pages", "学习页"),
                ("/#/practice", "练习"),
                ("/#/review", "复习"),
                ("/#/dashboard", "仪表盘"),
                ("/#/tasks", "任务中心"),
                ("/#/setup", "引导页"),
            ]
            for path, label in routes:
                page.goto(base.rstrip("/") + path, wait_until="networkidle")
                page.wait_for_timeout(350)
                hits = scan_text(page, label)
                check(f"{label} 没有禁止词", not hits, " | ".join(hits))

            # 8 设置窗口四个 tab
            page.goto(base, wait_until="networkidle")
            page.get_by_role("button", name="设置").click()
            page.wait_for_selector("[role='dialog']")
            for tab in ("模型", "外观", "下载", "关于"):
                page.get_by_role("tab", name=re.compile(f"^{tab}")).click()
                page.wait_for_timeout(350)
                hits = scan_text(page, f"设置·{tab}")
                check(f"设置·{tab} 没有禁止词", not hits, " | ".join(hits))
                if shots and tab == "外观":
                    page.screenshot(path=str(shots / "09-settings-appearance.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)

            # ── 11 导图配色跟主题（S-20 第 1 条）─────────────
            page.goto(base, wait_until="networkidle")
            page.wait_for_selector(".list-body .row")
            page.locator(".list-body").get_by_text("费曼技巧：用输出倒逼输入").click()
            page.wait_for_timeout(500)
            page.get_by_role("button", name="思维导图").click()
            page.wait_for_timeout(700)
            mm_src = page.locator(".mindmap-img").get_attribute("src") or ""
            check("导图请求带上主题 id 与明暗",
                  "theme=paper" in mm_src and "mode=light" in mm_src, mm_src)

            found = get_json(base, "api/knowledge?page_size=10&q=" + quote("费曼技巧"))
            item_id = found["items"][0]["id"]
            paper_svg = get_text(base, f"api/knowledge/{item_id}/mindmap?theme=paper")
            study_svg = get_text(base, f"api/knowledge/{item_id}/mindmap?theme=study")
            check("不同主题产出不同配色", paper_svg != study_svg)
            check("老契约 theme=dark 仍当成明暗",
                  get_text(base, f"api/knowledge/{item_id}/mindmap?theme=dark") != paper_svg)

            # ── 12 徽标实测对比度（S-15 收口）────────────────
            ratios = page.evaluate(
                """() => {
                  const lum = (c) => {
                    const p = (c.match(/[\\d.]+/g) || []).slice(0, 3).map(Number)
                      .map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) });
                    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2];
                  };
                  const bgOf = (el) => {
                    let n = el;
                    while (n) {
                      const bg = getComputedStyle(n).backgroundColor;
                      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
                      n = n.parentElement;
                    }
                    return 'rgb(255, 255, 255)';
                  };
                  const out = {};
                  for (const cls of ['badge-ready', 'badge-pending', 'badge-failed', 'badge-organizing']) {
                    const el = document.querySelector('.' + cls);
                    if (!el) continue;
                    const a = lum(getComputedStyle(el).color);
                    const b = lum(bgOf(el));
                    out[cls] = Math.round(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)) * 100) / 100;
                  }
                  return out;
                }"""
            )
            check("界面上徽标文字对比度 ≥ 4.5:1",
                  bool(ratios) and all(v >= 4.5 for v in ratios.values()),
                  " · ".join(f"{k} {v}" for k, v in ratios.items()))

            # ── 13 学习页预览外框（S-20 第 3 条）─────────────
            page.goto(base.rstrip("/") + "/#/pages", wait_until="networkidle")
            page.wait_for_selector(".pick-row")
            page.locator(".pick-row").first.click()
            page.get_by_role("button", name=re.compile("生成学习页")).click()
            page.wait_for_selector(".stage-frame-clip iframe", timeout=15000)
            page.wait_for_timeout(600)
            check("学习页预览有「一张纸」外框", page.locator(".stage-frame-clip").count() == 1)
            clip_color = page.evaluate(
                "() => getComputedStyle(document.querySelector('.stage-frame-clip')).backgroundColor"
            )
            check("外框底色不跟 iframe 白底混在一起", clip_color != "rgb(255, 255, 255)", clip_color)
            # 这条只为验收生成的那份别留在库里（后面截图还要生成一份，历史里只该有 1 条）
            for artifact in get_json(base, "api/html")["items"]:
                req = urllib.request.Request(
                    base + f"api/html/{artifact['id']}", method="DELETE"
                )
                urllib.request.urlopen(req, timeout=10)

            # ── 截图（可选）──────────────────────────────────
            if shots:
                page.goto(base, wait_until="networkidle")
                page.wait_for_selector(".list-body .row")
                page.locator(".list-body").get_by_text("费曼技巧：用输出倒逼输入").click()
                page.wait_for_timeout(600)
                page.screenshot(path=str(shots / "02-item-detail.png"))

                page.get_by_role("button", name="思维导图").click()
                page.wait_for_timeout(900)
                page.screenshot(path=str(shots / "03-mindmap.png"))

                for name, path in (
                    ("04-ask.png", "/#/ask"),
                    ("06-review.png", "/#/review"),
                    ("07-dashboard.png", "/#/dashboard"),
                    ("08-practice.png", "/#/practice"),
                ):
                    page.goto(base.rstrip("/") + path, wait_until="networkidle")
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(shots / name))

                # 学习页：真的生成一份，截图里才有「一张纸」的预览，不是空态
                # 用已整理好的那条（有摘要/笔记），生成出来的页面才完整
                page.goto(base.rstrip("/") + "/#/pages", wait_until="networkidle")
                page.wait_for_selector(".pick-row")
                page.locator(".picker-search").fill("费曼")
                page.locator(".picker-search").press("Enter")
                page.wait_for_timeout(700)
                page.locator(".pick-row").first.click()
                page.get_by_role("button", name=re.compile("生成学习页")).click()
                page.wait_for_selector(".stage-frame-clip iframe", timeout=15000)
                page.wait_for_timeout(900)
                # 等「已生成」提示自己消失，截图里别浮着一块 toast
                page.wait_for_timeout(2200)
                page.screenshot(path=str(shots / "05-pages.png"))

                # 深色模式：走真实设置路径（改完即时保存），不是偷偷改 localStorage
                page.goto(base, wait_until="networkidle")
                page.get_by_role("button", name="设置").click()
                page.wait_for_selector("[role='dialog']")
                page.get_by_role("tab", name=re.compile("^外观")).click()
                page.get_by_role("radio", name="深色").click()
                page.wait_for_timeout(400)
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                page.locator(".list-body").get_by_text("费曼技巧：用输出倒逼输入").click()
                page.wait_for_timeout(700)
                page.screenshot(path=str(shots / "10-dark-mode.png"))
                page.get_by_role("button", name="设置").click()
                page.get_by_role("tab", name=re.compile("^外观")).click()
                page.get_by_role("radio", name="浅色").click()
                page.wait_for_timeout(300)
                page.keyboard.press("Escape")

            real = [e for e in errors if "favicon" not in e]
            check("console 没有错误", not real, " | ".join(real[:3]))
            browser.close()
    except Exception:
        traceback.print_exc()
        check("脚本跑完", False, "异常中断，见上面的栈")
    finally:
        server.should_exit = True
        time.sleep(0.5)

    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS")
    print(f"临时数据目录：{TMP}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
