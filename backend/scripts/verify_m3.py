"""T3.11 验收脚本：一次跑完 M3 §5 DoD 的机器可验部分。

用法：cd backend && uv run python scripts/verify_m3.py [--keep]
退出码：0 全绿 / 1 有用例失败

覆盖四组：
  1. 思维导图（T3.7）：层级、退化、折叠、转义、主题、404、与笔记同步、不落库
  2. 学习页（T3.8/T3.9）：落库、内联样式、SVG 内嵌、净化和 XSS、断网自包含、下载、错误码
  3. 检索（T3.1/T3.4）：短词走 LIKE、长词走 FTS、空库空态
  4. 问答（T3.5/T3.12）：空检索短路（不调模型）、SSE 三事件顺序、历史落库

全程临时 DATA_DIR，不碰 data/data.db；`VECTOR_ENABLED=0` 是刻意的——
向量那一路要下 100MB 模型，验收不该依赖网络，且它已在 M3 会话里单独验过。
LLM 也不真调：把 `asker.stream` 换成假实现，验的是编排（顺序、落库、短路），不是模型质量。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path
from xml.etree import ElementTree as ET

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m3-"))
os.environ["DATA_DIR"] = str(TMP)  # 必须早于 import app：get_settings() 首次调用即缓存
os.environ["VECTOR_ENABLED"] = "0"
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import mindmap, renderer  # noqa: E402
from app.services.agents import asker  # noqa: E402

DB = TMP / "data.db"
RESULTS: list[tuple[bool, str]] = []
SVG_NS = "{http://www.w3.org/2000/svg}"

NOTE = """# 番茄工作法

## 核心原理
- 把注意力留在当前这一轮
- 计时器给的是边界，不是压力

## 具体做法
### 开工前
- 把当前这一轮写成一句可验收的话
### 铃响后
- 必须停下来，哪怕正写着顺手

## 常见误用
- 把 25 分钟当成硬指标

```python
for round in range(4):
    work(25)
```
"""


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((ok, name))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


def sql(query: str, args: tuple = ()) -> list:
    with sqlite3.connect(DB, timeout=10) as conn:
        return conn.execute(query, args).fetchall()


def svg_text(svg: str) -> list[str]:
    return [t.text or "" for t in ET.fromstring(svg).iter(f"{SVG_NS}text")]


def make_item(client: TestClient, title: str, body: str, note: str | None = None) -> int:
    resp = client.post("/api/knowledge", json={"title": title, "raw_content": body})
    item_id = resp.json()["id"]
    if note is not None:
        client.patch(f"/api/knowledge/{item_id}", json={"structured_note": note})
    return item_id


# ── 1. 思维导图 ───────────────────────────────────────────
def step_mindmap(client: TestClient) -> int:
    step("1. 思维导图（T3.7）")
    item_id = make_item(client, "番茄工作法", "番茄工作法的核心是把注意力留在当前这一轮。" * 6, NOTE)

    resp = client.get(f"/api/knowledge/{item_id}/mindmap")
    svg = resp.text
    check("有笔记 → 200 + image/svg+xml",
          resp.status_code == 200 and "image/svg+xml" in resp.headers["content-type"],
          resp.headers.get("content-type", ""))
    check("导图不缓存（Cache-Control: no-store）",
          resp.headers.get("cache-control") == "no-store", resp.headers.get("cache-control", ""))

    try:
        ET.fromstring(svg)
        xml_ok = True
    except ET.ParseError as exc:
        xml_ok = False
        detail = str(exc)
    check("输出是合法 XML", xml_ok, "" if xml_ok else detail)

    texts = svg_text(svg)
    tree = mindmap.parse_tree(NOTE, "番茄工作法", [])
    check("根节点是条目标题", tree.text == "番茄工作法", tree.text)
    check("笔记的第一个 # 挂在根下面（不取代根）",
          len(tree.children) == 1 and tree.children[0].text == "番茄工作法",
          str([c.text for c in tree.children]))
    check("树层级与笔记一致",
          [c.text for c in tree.children[0].children][:2] == ["核心原理", "具体做法"],
          str([c.text for c in tree.children[0].children]))
    check("二级标题成为节点", "核心原理" in texts and "常见误用" in texts)
    check("三级标题成为节点", "开工前" in texts)
    check("无 <script> / 无外链",
          "<script" not in svg.lower() and renderer.find_external_refs(svg) == [])
    check("有连线与矩形", svg.count("<path") >= len(texts) - 1 and svg.count("<rect") == len(texts))

    # 空格、引号、< > 都要转义，不能把标签截断
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": "# A < B & \"C\"\n## 子 <script>x</script>"})
    dirty = client.get(f"/api/knowledge/{item_id}/mindmap").text
    check("文字里的 < & 被转义，SVG 仍可解析",
          "&lt;" in dirty and "&amp;" in dirty and ET.fromstring(dirty) is not None)
    check("转义后仍无 <script>", "<script" not in dirty.lower())

    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": NOTE})

    # 深：超过 4 级折叠
    deep = "\n".join(f"{'#' * n} 第{n}级" for n in range(1, 7))
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": deep})
    deep_texts = svg_text(client.get(f"/api/knowledge/{item_id}/mindmap").text)
    check("层级截到 4 级（第 5、6 级不出现）",
          "第5级" not in deep_texts and "第6级" not in deep_texts, str(deep_texts))
    check("第 4 级仍在", "第4级" in deep_texts)

    # 宽：超过 8 个孩子折成一条提示
    wide = "\n".join(f"## 第{i}节" for i in range(1, 13))
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": wide})
    wide_texts = svg_text(client.get(f"/api/knowledge/{item_id}/mindmap").text)
    check("超过 8 个孩子时给出「…另 N 节」", any("另 4 节" in t for t in wide_texts), str(wide_texts[-2:]))

    # 长标题截断
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": "## " + "很长的标题" * 6})
    long_texts = svg_text(client.get(f"/api/knowledge/{item_id}/mindmap").text)
    check("超过 24 字的节点被截断（22 字 + …）",
          any(t.endswith("…") and len(t) == 23 for t in long_texts), str(long_texts[-1:]))

    # 与笔记同步：改完立刻变
    before = client.get(f"/api/knowledge/{item_id}/mindmap").text
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": "# 新标题\n## 新增小节"})
    after = client.get(f"/api/knowledge/{item_id}/mindmap").text
    check("改了笔记导图立刻跟着变", before != after and "新增小节" in svg_text(after), "")

    # 退化：无结构笔记 → 单节点；key_points → 一级子节点
    plain_id = make_item(client, "只有标题的条目", "一段没有任何标题的正文。" * 5)
    plain = client.get(f"/api/knowledge/{plain_id}/mindmap")
    check("structured_note 为空 → 单节点 SVG，不报 500",
          plain.status_code == 200 and len(svg_text(plain.text)) == 1,
          f"{plain.status_code} / {svg_text(plain.text)}")

    with sqlite3.connect(DB) as conn:
        conn.execute(
            "UPDATE knowledge_item SET key_points=? WHERE id=?",
            (json.dumps(["要点一", "要点二", "要点三"], ensure_ascii=False), plain_id),
        )
    kp_texts = svg_text(client.get(f"/api/knowledge/{plain_id}/mindmap").text)
    check("无标题时用 key_points 退化",
          set(kp_texts) == {"只有标题的条目", "要点一", "要点二", "要点三"}, str(kp_texts))

    # 主题：2026-11-10 起配色按主题派生，这里改成「跟 palette() 对齐且两档不同」，
    # 不再钉死具体十六进制（配色该由 tools/check_contrast.py 与 palette() 负责）
    dark = client.get(f"/api/knowledge/{item_id}/mindmap?theme=dark").text
    light = client.get(f"/api/knowledge/{item_id}/mindmap?theme=light").text
    dark_root = mindmap.palette("paper", "dark")[0][0]
    light_root = mindmap.palette("paper", "light")[0][0]
    check("dark 主题换配色",
          dark != light and dark_root in dark and light_root in light and light_root not in dark)

    check("条目不存在 → 404 ITEM_NOT_FOUND",
          client.get("/api/knowledge/999999/mindmap").status_code == 404)
    check("导图不落库（ADR-019）",
          sql("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%mindmap%'") == [])
    return item_id


# ── 2. 学习页 ────────────────────────────────────────────
def step_html(client: TestClient, item_id: int) -> int:
    step("2. 学习页（T3.8 / T3.9）")
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": NOTE})
    second = make_item(client, "第二篇", "第二篇的正文。" * 8, "# 第二节\n## 要点\n- 一条")

    resp = client.post("/api/html/generate", json={"item_ids": [item_id, second], "title": "番茄专题"})
    body = resp.json()
    check("生成 → 201 + {id,title,size_bytes}",
          resp.status_code == 201 and body.get("title") == "番茄专题" and body.get("size_bytes", 0) > 1000,
          str(body))
    artifact_id = body["id"]

    page = client.get(f"/api/html/{artifact_id}")
    check("预览返回 HTML 文本", page.status_code == 200 and page.text.startswith("<!DOCTYPE html>"))
    check("内联 <style> 存在（不依赖外链 CSS）", "<style>" in page.text and "</style>" in page.text)
    check("每节内嵌 <svg> 导图", page.text.count("<div class=\"mindmap\"><svg") == 2)
    check("有目录与两个条目小节",
          page.text.count('<section class="item"') == 2 and page.text.count('class="toc"') == 1)
    check("断网自包含：无任何外部引用", renderer.find_external_refs(page.text) == [],
          str(renderer.find_external_refs(page.text)[:3]))
    check("没有 <script>", "<script" not in page.text.lower())
    # noclasses 的标志：Pygments 产出 `<span style="color: ...">`，而不是 `<span class="k">`
    check("代码高亮用行内 style（noclasses，不产生 class 依赖）",
          page.text.count("<span style=") >= 3
          and not re.search(r'<span class="[a-z]{1,2}">', page.text),
          f"span-style={page.text.count('<span style=')}")
    check("CSP 头收紧到只允许内联样式",
          "default-src 'none'" in (page.headers.get("content-security-policy") or ""))

    # XSS：笔记里的标签必须是可见文本，不是标签
    evil_id = make_item(
        client, "危险条目",
        "正文里带一段 <script>alert(1)</script> 和一张图 <img src=x onerror=alert(2)>。",
        "# 危险\n<script>alert(1)</script>\n\n<img src=x onerror=alert(2)>\n\n正常一行",
    )
    evil = client.post("/api/html/generate", json={"item_ids": [evil_id]}).json()
    evil_page = client.get(f"/api/html/{evil['id']}").text
    check("笔记里的 <script> 被转义成文本", "&lt;script&gt;alert(1)&lt;/script&gt;" in evil_page)
    check("产物里没有可执行的 <script>", "<script" not in evil_page.lower())
    tags = re.findall(r"<[^>]+>", evil_page)
    check("产物里没有带 on* 事件属性的标签",
          not any(re.search(r"\son\w+\s*=", tag, re.I) for tag in tags),
          str([t for t in tags if re.search(r"\son\w+\s*=", t, re.I)][:2]))
    check("危险内容只以文本形式存在（没有 img 标签）", "<img" not in evil_page.lower())
    check("默认标题取首个条目标题", evil["title"] == "危险条目", evil["title"])
    check("单条目页面仍然自包含", renderer.find_external_refs(evil_page) == [])

    # 下载
    dl = client.get(f"/api/html/{artifact_id}/download")
    check("下载带 attachment 且文件名 URL 编码",
          dl.status_code == 200 and "attachment;" in dl.headers["content-disposition"]
          and "%E7%95%AA%E8%8C%84" in dl.headers["content-disposition"],
          dl.headers.get("content-disposition", "")[:70])
    check("下载内容与预览一致", dl.text == page.text)

    # 列表
    listing = client.get("/api/html").json()
    entry = next((i for i in listing["items"] if i["id"] == artifact_id), None)
    check("列表含条目数、大小，且不下发全文",
          entry and entry["item_count"] == 2 and entry["size_bytes"] > 1000 and "html_content" not in entry,
          str(entry))
    check("列表总数与实际一致", listing["total"] == sql("SELECT COUNT(*) FROM html_artifact")[0][0])

    # 落库但不跟条目级联（契约 §5）
    client.delete(f"/api/knowledge/{second}")
    check("条目被删后已生成的页面仍可打开",
          client.get(f"/api/html/{artifact_id}").status_code == 200)

    # 错误码
    check("item_ids 含不存在的条目 → 404",
          client.post("/api/html/generate", json={"item_ids": [item_id, 999999]}).status_code == 404)
    check("item_ids 为空 → 422", client.post("/api/html/generate", json={"item_ids": []}).status_code == 422)
    check("页面不存在 → 404", client.get("/api/html/999999").status_code == 404)
    check("删除页面 → 200，再取 → 404",
          client.delete(f"/api/html/{artifact_id}").status_code == 200
          and client.get(f"/api/html/{artifact_id}").status_code == 404)
    return evil_id


# ── 3. 检索 ──────────────────────────────────────────────
def step_search(client: TestClient, item_id: int) -> None:
    step("3. 检索（T3.1 / T3.4）")
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": NOTE})
    fts = client.get("/api/search", params={"q": "番茄工作法"}).json()
    check("≥3 字查询走 fts", fts["match_type"] == "fts" and fts["total"] > 0,
          f"{fts['match_type']} / {fts['total']}")
    like = client.get("/api/search", params={"q": "番茄"}).json()
    check("2 字查询走 like", like["match_type"] == "like" and like["total"] > 0,
          f"{like['match_type']} / {like['total']}")
    check("命中带片段与正文（前端定位要用）",
          like["items"] and like["items"][0].get("snippet") and like["items"][0].get("content"))
    empty = client.get("/api/search", params={"q": ""}).json()
    check("空查询返回空结果而不是 422", empty["total"] == 0 and empty["match_type"] == "none")
    check("降级标记为 vector_disabled（本脚本关了向量）",
          client.get("/api/search", params={"q": "番茄工作法"}).json()["fallback"] == "vector_disabled")


# ── 4. 问答 ──────────────────────────────────────────────
def step_ask(client: TestClient, item_id: int) -> None:
    step("4. 问答（T3.5 / T3.12）")
    client.patch(f"/api/knowledge/{item_id}", json={"structured_note": NOTE})

    def events_of(payload: dict) -> list[dict]:
        out = []
        with client.stream("POST", "/api/ask", json=payload) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    out.append(json.loads(line[6:]))
        return out

    # 库外问题：必须短路，不调模型
    before_calls = sql("SELECT COUNT(*) FROM llm_call_log")[0][0]
    before_asks = sql("SELECT COUNT(*) FROM ask_log")[0][0]
    out = events_of({"question": "量子纠缠的贝尔不等式实验细节"})
    check("库外问题 → no_result 且只有 2 个事件",
          [e["type"] for e in out] == ["no_result", "done"], str([e["type"] for e in out]))
    check("库外问题不调模型（llm_call_log 未新增）",
          sql("SELECT COUNT(*) FROM llm_call_log")[0][0] == before_calls)
    check("库外问题仍记历史（no_result=1，prompt_tokens 为空）",
          sql("SELECT COUNT(*) FROM ask_log")[0][0] == before_asks + 1
          and sql("SELECT no_result, prompt_tokens FROM ask_log ORDER BY id DESC LIMIT 1")[0] == (1, None))

    # 有命中：注入假 LLM，验编排而不是模型
    original = asker.stream

    def fake_stream(question, sources, items, usage):
        usage["prompt_tokens"] = 100
        usage["completion_tokens"] = 5
        for piece in ("答案第一句[1]。", "答案第二句。"):
            yield piece

    asker.stream = fake_stream
    try:
        out = events_of({"question": "番茄工作法的核心原理是什么"})
    finally:
        asker.stream = original

    kinds = [e["type"] for e in out]
    check("SSE 顺序：sources → delta… → done",
          kinds[0] == "sources" and kinds[-1] == "done" and kinds.count("delta") == 2, str(kinds))
    check("sources 带来源与降级标记",
          out[0].get("sources") and out[0].get("fallback") == "vector_disabled",
          str(out[0].get("fallback")))
    check("答案按片段流式抵达",
          "".join(e.get("text", "") for e in out if e["type"] == "delta")
          == "答案第一句[1]。答案第二句。")
    check("done 带 usage", out[-1].get("usage", {}).get("prompt_tokens") == 100)

    row = sql("SELECT answer, no_result, prompt_tokens FROM ask_log ORDER BY id DESC LIMIT 1")[0]
    check("有命中时历史记下完整答案与 tokens",
          row[0] == "答案第一句[1]。答案第二句。" and row[1] == 0 and row[2] == 100, str(row))

    hist = client.get("/api/ask/history").json()
    check("历史列表不含完整答案", hist["items"] and "answer" not in hist["items"][0])
    detail = client.get(f"/api/ask/history/{hist['items'][0]['id']}").json()
    check("历史详情带答案与来源快照", detail.get("answer") and "sources" in detail)


def cleanup(keep: bool) -> None:
    if keep:
        print(f"\n临时数据目录保留在：{TMP}")
        return
    shutil.rmtree(TMP, ignore_errors=True)


def main() -> int:
    keep = "--keep" in sys.argv[1:]
    print("=" * 62)
    print("  Cairn · M3 验收（T3.11）")
    print("=" * 62)
    print(f"临时数据目录：{TMP}")
    print("向量：关闭（VECTOR_ENABLED=0）　LLM：假实现（不产生真实调用）")

    aborted = ""
    try:
        with TestClient(app) as client:
            item_id = step_mindmap(client)
            step_html(client, item_id)
            step_search(client, item_id)
            step_ask(client, item_id)
    except Exception as exc:  # 任何未捕获异常都算验收失败
        aborted = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        cleanup(keep)

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = [name for ok, name in RESULTS if not ok]
    print("\n" + "=" * 62)
    print(f"  结果：{passed}/{len(RESULTS)} PASS")
    if aborted:
        print(f"  中断：{aborted}")
    for name in failed:
        print(f"    - 失败：{name}")
    print("=" * 62)
    return 0 if not aborted and RESULTS and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
