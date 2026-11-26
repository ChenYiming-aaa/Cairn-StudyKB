"""「已有题池」验收（优化方案 v0.4 §3.2）。

用法：
    cd backend && uv run python scripts/verify_pool.py

退出码：0 全绿 / 1 有用例失败。

覆盖分组：
  §count  `GET /api/knowledge/{id}/questions` 的计数：没有题回空、出 5 题回 5、再出 5 题回 10，
          且**老题的 id 一个都没变**（用户要能重做同一批，不是换一批新的）
  §order  排序：导入题按题号数值序在前、模型题按入库顺序在后；`origin='imported'` 但题号被摘掉的
          残留题**不出现**（那是「删了又冒出来」）
  §shape  与按卷练同形：payload 是 dict、question/options/answer/explanation 都在、
          `options` 已剥掉自带的 A. 前缀
  §edge   不存在的 id → 404 `ITEM_NOT_FOUND`；题池与按卷练口径的差异（同一份试卷上两者题数不同，
          这是设计而不是缺陷）

**不联网、不调 LLM**：题直接写 `question` 表（出题端点要调模型，验的不是它）。
判据在脚本里独立重算，不 import 被测函数的判定。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-pool-"))
(TMP / ".env").write_text("LLM_API_KEY=sk-verify-pool-not-a-real-key\n", encoding="utf-8")
os.environ["DATA_DIR"] = str(TMP)            # 必须早于 import app
os.environ["CAIRN_NO_AUTO_ORGANIZE"] = "1"
os.environ["VECTOR_ENABLED"] = "0"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")

sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient      # noqa: E402

from app.db.conn import get_conn               # noqa: E402
from app.db.migrate import init_db             # noqa: E402
from app.main import app                       # noqa: E402

RESULTS: list[tuple[bool, str]] = []
_seq = iter(range(1, 10_000))


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((bool(ok), name))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   → {detail}" if detail else ""))
    return bool(ok)


def make_item(title: str, *, kind: str = "material") -> int:
    """造一条内容（不需要原件：题池只看 question 表）。"""
    tag = next(_seq)
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO knowledge_item (title, raw_content, content_hash, source_type,
                                               status, created_at, updated_at, kind)
                   VALUES (?, '正文', ?, 'text', 'ready', '2026-11-26T00:00:00',
                           '2026-11-26T00:00:00', ?)""",
                (title, f"verify-pool-{tag}", kind),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def seed(item_id: int, stem: str, *, origin: str = "ai", number: str | None = None,
         options: list[str] | None = None) -> int:
    """直接写一条题（出题端点要调模型，这里验的是读取）。"""
    stamp = next(_seq)
    payload = {
        "question": stem,
        "options": options if options is not None else ["甲", "乙", "丙", "丁"],
        "answer": "A",
        "explanation": "因为甲",
    }
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO question (item_id, type, difficulty, payload, fingerprint,
                                         origin, number, created_at)
                   VALUES (?, 'single', 'understand', ?, ?, ?, ?, '2026-11-26T00:00:00')""",
                (item_id, json.dumps(payload, ensure_ascii=False),
                 f"verify-pool-{item_id}-{stamp}", origin, number),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def pool(client: TestClient, item_id: int) -> dict:
    resp = client.get(f"/api/knowledge/{item_id}/questions")
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
    return resp.json()


# ── §count ─────────────────────────────────────────────────
def group_count() -> None:
    client = TestClient(app)
    item = make_item("题池计数用")

    body = pool(client, item)
    check("没出过题的内容：200 且 total=0", body.get("total") == 0, str(body.get("total")))
    check("没出过题的内容：questions 是空数组", body.get("questions") == [], str(body.get("questions")))
    check("回带 title 与 kind（前端要显示「从哪条做」）",
          body.get("title") == "题池计数用" and body.get("kind") == "material",
          f"{body.get('title')} / {body.get('kind')}")

    first = [seed(item, f"第一次出的第 {i} 题") for i in range(1, 6)]
    body = pool(client, item)
    check("出 5 题后 total=5", body.get("total") == 5, str(body.get("total")))
    check("5 道题的 id 与入库顺序一致（重做的是同一批）",
          [q["id"] for q in body["questions"]] == first,
          str([q["id"] for q in body["questions"]]))

    more = [seed(item, f"第二次出的第 {i} 题") for i in range(1, 6)]
    body = pool(client, item)
    check("再出 5 题后 total=10", body.get("total") == 10, str(body.get("total")))
    check("老题的 id 一个都没变（不是换了一批新的）",
          [q["id"] for q in body["questions"]][:5] == first,
          str([q["id"] for q in body["questions"]][:5]))
    check("新题接在后面（按入库顺序）",
          [q["id"] for q in body["questions"]][5:] == more,
          str([q["id"] for q in body["questions"]][5:]))


# ── §order ─────────────────────────────────────────────────
def group_order() -> None:
    client = TestClient(app)
    item = make_item("题池排序用", kind="exam")

    # 故意乱序插入：题号 10 必须在 2 后面（TEXT 直排会排成 1,10,2）
    seed(item, "导入第 10 题", origin="imported", number="10")
    seed(item, "导入第 2 题", origin="imported", number="2")
    seed(item, "模型补的第 1 题", origin="ai")
    seed(item, "导入第 1 题", origin="imported", number="1")
    seed(item, "模型补的第 2 题", origin="ai")

    body = pool(client, item)
    got = [q["question"] for q in body["questions"]]
    check("导入题在前、按题号数值序（1, 2, 10）",
          got[:3] == ["导入第 1 题", "导入第 2 题", "导入第 10 题"], str(got))
    check("模型题在后、按入库顺序",
          got[3:] == ["模型补的第 1 题", "模型补的第 2 题"], str(got[3:]))

    # 被 _drop_unused 摘掉题号的导入题：删了就不该在题池里复活
    ghost = seed(item, "用户删掉的题", origin="imported", number=None)
    body = pool(client, item)
    check("origin=imported 但题号被摘掉的残留题不出现",
          ghost not in [q["id"] for q in body["questions"]],
          str([q["id"] for q in body["questions"]]))
    check("摘掉题号后 total 仍是 5", body.get("total") == 5, str(body.get("total")))


# ── §shape ─────────────────────────────────────────────────
def group_shape() -> None:
    client = TestClient(app)
    item = make_item("题池形状用")
    seed(item, "形状检查题", options=["A. 甲", "B. 乙", "C. 丙", "D. 丁"])

    body = pool(client, item)
    q = body["questions"][0]
    check("带题干", q.get("question") == "形状检查题", str(q.get("question")))
    check("带题型", q.get("type") == "single", str(q.get("type")))
    check("带答案", q.get("answer") == "A", str(q.get("answer")))
    check("带解析（空也要是空串，不是 None）", q.get("explanation") == "因为甲", str(q.get("explanation")))
    check("payload 是 dict（与按卷练同一形状）", isinstance(q.get("payload"), dict), str(type(q.get("payload"))))
    check("options 已剥掉自带的 A. 前缀（字母只由界面给）",
          q.get("options") == ["甲", "乙", "丙", "丁"], str(q.get("options")))


# ── §edge ──────────────────────────────────────────────────
def group_edge() -> None:
    client = TestClient(app)

    resp = client.get("/api/knowledge/999999/questions")
    check("不存在的内容 → 404", resp.status_code == 404, str(resp.status_code))
    check("404 的 code 是 ITEM_NOT_FOUND",
          (resp.json().get("error") or {}).get("code") == "ITEM_NOT_FOUND",
          json.dumps(resp.json(), ensure_ascii=False)[:120])

    # 同一份试卷上：按卷练只取 imported+题号；题池连模型补的题一起取
    item = make_item("口径差异用", kind="exam")
    for number in ("1", "2", "3"):
        seed(item, f"导入第 {number} 题", origin="imported", number=number)
    seed(item, "模型补的题", origin="ai", number="99")

    paper = client.get(f"/api/quiz/paper/{item}").json()
    body = pool(client, item)
    check("按卷练仍只取导入题（3 道）", len(paper["questions"]) == 3, str(len(paper["questions"])))
    check("题池取这条内容上全部现存题（导入 3 + 模型 1）", body.get("total") == 4, str(body.get("total")))
    check("按卷练的题是题池的前 3 道（同一批，顺序一致）",
          [q["id"] for q in paper["questions"]] == [q["id"] for q in body["questions"]][:3],
          f"{[q['id'] for q in paper['questions']]} vs {[q['id'] for q in body['questions']]}")


GROUPS = [("count", group_count), ("order", group_order),
          ("shape", group_shape), ("edge", group_edge)]


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    init_db()
    print(f"Cairn 题池验收 · 临时数据目录 {TMP}")
    for name, fn in GROUPS:
        if only and only != name:
            continue
        print(f"§{name}")
        try:
            fn()
        except Exception:
            traceback.print_exc()
            check(f"§{name} 跑完", False, "异常中断，见上面的栈")

    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} PASS")
    if passed != total:
        print("失败项：")
        for ok, name in RESULTS:
            if not ok:
                print(f"  - {name}")
        return 1
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
