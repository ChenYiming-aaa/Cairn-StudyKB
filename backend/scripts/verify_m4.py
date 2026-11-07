"""T4.8 验收脚本：一次跑完 M4 §5 DoD 的机器可验部分。

用法：cd backend && uv run python scripts/verify_m4.py [--keep]
退出码：0 全绿 / 1 有用例失败

覆盖五组：
  1. 增量扫描（T4.2）：题干含 `{}` 不错位、被截断的对象留在 leftover
  2. 出题流（T4.1/T4.2/T4.3）：逐题 emit、坏 JSON/非法答案/无解析只跳该题、补生成、撞指纹复用
  3. 判分（T4.4）：多选乱序、少选、字符串形状、单选大小写、判断布尔、空答案、简答反馈、
     批改失败落 NULL（不是 0）
  4. 复习（T4.6）：答错明天回来、时间旅行、1→2→4→7→15、答错重置、NULL 不排期、错题本
  5. 参数校验与错误码

全程临时 DATA_DIR，不碰 data/data.db。**不真调模型**：出题把 `quizzer.stream` 换成脚本化假流，
批改把 `llm.chat` 换掉——验的是编排与判分口径，不是模型质量（同 verify_m3 的做法）。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m4-"))
os.environ["DATA_DIR"] = str(TMP)  # 必须早于 import app：get_settings() 首次调用即缓存
os.environ["VECTOR_ENABLED"] = "0"
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

from app.db.conn import get_conn  # noqa: E402
from app.db.repo import questions as qrepo  # noqa: E402
from app.db.repo import review as rrepo  # noqa: E402
from app.main import app  # noqa: E402
from app.services import llm  # noqa: E402
from app.services.agents import quizzer  # noqa: E402

DB = TMP / "data.db"
RESULTS: list[tuple[bool, str]] = []

BODY = (
    "番茄工作法的核心是把注意力留在当前这一轮，计时器给的是边界而不是压力。"
    "铃响之后必须停下来，哪怕正写着顺手；把 25 分钟当硬指标是最常见的误用。"
) * 4


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


# ── 脚本化假流（不花一次调用）──────────────────────────────
SCRIPT: list[str] = []
CALLS: list[int] = []


def set_script(*texts: str) -> None:
    SCRIPT.clear()
    SCRIPT.extend(texts)
    CALLS.clear()


def fake_stream(_messages):
    """每次调用取下一段脚本，按 11 字切块模拟增量 delta。"""
    CALLS.append(1)
    text = SCRIPT.pop(0) if SCRIPT else ""
    for i in range(0, len(text), 11):
        yield text[i:i + 11]


def events_of(client: TestClient, payload: dict) -> list[dict]:
    out = []
    with client.stream("POST", "/api/quiz/generate", json=payload) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def make_item(client: TestClient, title: str, body: str = BODY) -> int:
    return client.post("/api/knowledge", json={"title": title, "raw_content": body}).json()["id"]


def q_obj(qtype="single", question="番茄工作法的核心是什么？",
          options=("A. 注意力留在当前这一轮", "B. 计时器是硬指标"),
          answer="A",
          explanation="材料第一句：核心是把注意力留在当前这一轮。") -> dict:
    item = {"type": qtype, "question": question, "answer": answer, "explanation": explanation,
            "difficulty": "understand"}
    if options is not None:
        item["options"] = list(options)
    return item


def as_array(*objects) -> str:
    """dict 按 JSON 序列化；已经是字符串的原样拼进去（用来注入坏 JSON）。"""
    return "[" + ",".join(
        obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
        for obj in objects
    ) + "]"


def add_question(item_id: int, **kwargs) -> int:
    """直接入库一道题（判分/复习用例要精确控制答案，不必绕出题流）。"""
    data = {**q_obj(**kwargs), "difficulty": kwargs.get("difficulty", "understand")}
    conn = get_conn()
    try:
        with conn:
            qid, _ = qrepo.upsert_question(
                conn, item_id=item_id, qtype=data["type"], difficulty=data["difficulty"],
                payload={k: data[k] for k in ("question", "options", "answer", "explanation")
                         if k in data},
                fp=qrepo.fingerprint(item_id, data["type"], data["question"]),
            )
        return qid
    finally:
        conn.close()


# ── 1. 增量扫描 ───────────────────────────────────────────
def step_scan() -> None:
    step("1. 增量括号扫描（T4.2 §6.2）")
    found, rest = quizzer.scan_objects('{"question":"写代码 { x } 会怎样"}')
    check("题干里有 {} 时不错位", len(found) == 1 and "x" in found[0], str(found))
    check("无剩余（完整对象全部消费）", rest == "", repr(rest))

    found, rest = quizzer.scan_objects('{"a":1}{"b":')
    check("被截断的对象留在 leftover 等下一个 delta",
          len(found) == 1 and rest == '{"b":', repr(rest))

    scanner = quizzer.Scanner()
    pieces = ['{"type":"single","quest', 'ion":"半截"}']
    check("Scanner 跨 delta 拼回对象",
          scanner.feed(pieces[0]) == [] and len(scanner.feed(pieces[1])) == 1)


# ── 2. 出题流 ─────────────────────────────────────────────
def step_generate(client: TestClient, item_id: int) -> None:
    step("2. 出题流（T4.1–T4.3）")
    original = quizzer.stream
    quizzer.stream = fake_stream
    try:
        # 2.1 六段输出：2 好、1 坏 JSON、1 越界答案、1 缺解析、1 重复
        bad_json = '{"type":"single","question":"坏收尾","answer":"A",}'
        out_of_range = q_obj(answer="E", options=["A. 甲", "B. 乙", "C. 丙"],
                            question="答案越界的题")
        no_expl = q_obj(question="没有解析的题", explanation="")
        dup = q_obj()
        set_script(as_array(
            q_obj(), bad_json, out_of_range, no_expl,
            q_obj(question="计时器的作用是什么？", answer="B",
                  options=["A. 加压", "B. 给边界", "C. 计分"]),
            dup,
        ))
        events = events_of(client, {"item_id": item_id, "types": ["single"],
                                    "difficulty": "understand", "count": 3})
        kinds = [e["type"] for e in events]
        questions = [e["question"] for e in events if e["type"] == "question"]
        skips = [e["reason"] for e in events if e["type"] == "skip"]
        done = events[-1]

        check("逐题 emit，最后一定是 done",
              kinds.count("question") == 2 and kinds[-1] == "done", str(kinds))
        check("坏 JSON 只跳该题", "json_parse_failed" in skips, str(skips))
        check("答案越界 → bad_answer", "bad_answer" in skips, str(skips))
        check("缺解析 → missing_explanation", "missing_explanation" in skips, str(skips))
        check("重复题干 → duplicate", "duplicate" in skips, str(skips))
        check("done 报 count/skipped/requested",
              done["count"] == 2 and done["skipped"] == 4 and done["requested"] == 3, str(done))
        check("题目事件带答案、解析、来源",
              all(q.get("answer") and q.get("explanation") and q.get("source_title")
                  for q in questions))
        check("入库行数与 emit 一致",
              sql("SELECT COUNT(*) FROM question WHERE item_id=?", (item_id,))[0][0] == 2)

        # 2.2 补生成：首轮只给 1 题，要 3 题 → 逐题补
        set_script(
            as_array(q_obj(question="补生成第一题？", options=["A. 甲", "B. 乙"])),
            as_array(q_obj(question="补生成第二题？", options=["A. 甲", "B. 乙"])),
            as_array(q_obj(question="补生成第三题？", options=["A. 甲", "B. 乙"])),
        )
        events = events_of(client, {"item_id": item_id, "types": ["single"], "count": 3})
        done = events[-1]
        check("首轮不足时逐题补生成到 3 题",
              done["count"] == 3 and done["requested"] == 3 and len(CALLS) == 3,
              f'{done} calls={len(CALLS)}')

        # 2.3 撞指纹：同一题再出一次不再插新行
        before = sql("SELECT COUNT(*) FROM question WHERE item_id=?", (item_id,))[0][0]
        set_script(as_array(q_obj(question="补生成第一题？", options=["A. 甲", "B. 乙"])))
        events = events_of(client, {"item_id": item_id, "types": ["single"], "count": 1})
        first = [e for e in events if e["type"] == "question"]
        after = sql("SELECT COUNT(*) FROM question WHERE item_id=?", (item_id,))[0][0]
        check("重复出题复用旧 id 且标 duplicate",
              first and first[0]["question"]["duplicate"] is True, str(first[:1]))
        check("重复出题不增加题目行", before == after, f"{before} → {after}")
    finally:
        quizzer.stream = original


# ── 3. 判分 ───────────────────────────────────────────────
def step_judge(client: TestClient, item_id: int) -> dict:
    step("3. 判分（T4.4）")
    multiple = add_question(item_id, qtype="multiple", question="番茄工作法的说法哪些对？",
                            options=["A. 注意力留在本轮", "B. 计时器是硬指标",
                                     "C. 铃响要停", "D. 越久越好"],
                            answer=["A", "C"])
    single = add_question(item_id, qtype="single", question="答案是 B 的单选？",
                          options=["A. 甲", "B. 乙", "C. 丙"], answer="B")
    boolean = add_question(item_id, qtype="boolean", question="25 分钟是硬指标。", answer=True)
    short = add_question(item_id, qtype="short", question="说说番茄工作法的核心。",
                         answer="把注意力留在当前这一轮，铃响就停")

    def submit(*answers) -> dict:
        resp = client.post("/api/quiz/submit", json={"answers": [
            {"question_id": qid, "user_answer": ua} for qid, ua in answers]})
        return resp.json()

    data = submit((multiple, ["C", "A"]))
    check("多选乱序仍判对", data["items"][0]["is_correct"] is True, str(data["items"][0]))
    check("多选乱序 accuracy=1.0", data["accuracy"] == 1.0, str(data["accuracy"]))

    data = submit((multiple, ["C"]))
    check("多选少选判错", data["items"][0]["is_correct"] is False)
    check("判错时回显正确答案", data["items"][0]["correct_answer"] == ["A", "C"],
          str(data["items"][0]["correct_answer"]))

    data = submit((multiple, "A,C"))
    check("多选给字符串 \"A,C\" 也判对", data["items"][0]["is_correct"] is True)

    data = submit((single, " b "))
    check("单选大小写与空白归一", data["items"][0]["is_correct"] is True)

    data = submit((boolean, "对"), (boolean, False))
    check("判断 \"对\" 判对", data["items"][0]["is_correct"] is True)
    check("判断 false 判错", data["items"][1]["is_correct"] is False)

    data = submit((single, ""))
    check("空答案判错并回显参考答案",
          data["items"][0]["is_correct"] is False
          and data["items"][0]["correct_answer"] == "B", str(data["items"][0]))

    # 简答：批改成功
    original_chat = llm.chat
    llm.chat = lambda *a, **k: json.dumps(
        {"score": 0.8, "correct": True, "feedback": "你提到了「留在本轮」，但漏掉了「铃响就停」",
         "missing": ["铃响就停"]}, ensure_ascii=False)
    try:
        data = submit((short, "要把注意力留在当前这一轮"))
        check("简答批改给出具体反馈（指出漏了什么）",
              data["items"][0]["is_correct"] is True
              and "漏掉" in (data["items"][0]["feedback"] or ""), str(data["items"][0]))

        # 简答：批改失败 → NULL
        def boom(*_a, **_k):
            raise llm.LLMError("LLM_TIMEOUT", "批改超时")

        llm.chat = boom
        data = submit((short, "随便写点什么"))
        item = data["items"][0]
        check("批改失败 → is_correct null（不是 False）", item["is_correct"] is None, str(item))
        check("批改失败给「待人工判断」提示",
              "待人工判断" in (item["feedback"] or ""), str(item["feedback"]))
        check("NULL 落库仍是 NULL（不是 0）",
              sql("SELECT is_correct FROM quiz_attempt WHERE question_id=? "
                  "ORDER BY id DESC LIMIT 1", (short,))[0][0] is None)
        check("NULL 不计入 correct_count 也不漏出 total",
              data["correct_count"] == 0 and data["total"] == 1, str(data))
    finally:
        llm.chat = original_chat

    return {"multiple": multiple, "single": single, "boolean": boolean, "short": short}


# ── 4. 复习与错题本 ───────────────────────────────────────
def step_review(client: TestClient, qids: dict, item_id: int) -> None:
    step("4. 复习队列与错题本（T4.6）")
    multiple = qids["multiple"]

    # 先把它打成「刚刚答错」，后面的断言才不依赖上一组用例的收尾状态
    client.post("/api/quiz/submit", json={"answers": [
        {"question_id": multiple, "user_answer": ["C"]}]})

    row = sql("SELECT due_at, interval_days, lapses FROM review_item WHERE question_id=?",
              (multiple,))[0]
    due = rrepo.to_aware(row[0])
    gap = (due - datetime.now(timezone.utc)).total_seconds() / 86400
    check("答错 → interval=1、lapses>=1", row[1] == 1 and row[2] >= 1, str(row))
    check("答错的题 due 是明天（UTC 存储）", 0.9 < gap < 1.1, f"{gap:.2f} 天")
    check("due_at 带 +00:00 时区", row[0].endswith("+00:00"), row[0])

    payload = client.get("/api/review/due").json()
    check("今天待复习为空（due 是明天）", payload["total"] == 0, str(payload["total"]))
    check("队列里已有这题（tracked > 0）", payload["tracked"] > 0, str(payload["tracked"]))

    # 时间旅行：把 due 挪到 1 分钟前，等价于「明天再打开」
    sql("UPDATE review_item SET due_at=? WHERE question_id=?",
        ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"),
         multiple))
    payload = client.get("/api/review/due").json()
    hit = [i for i in payload["items"] if i["question_id"] == multiple]
    check("到期后出现在待复习里", payload["total"] == 1 and hit, str(payload["total"]))
    check("待复习的题自带 options/answer 可直接作答",
          hit and hit[0]["options"] and hit[0]["answer"], str(hit[:1]))

    # 间隔推进：1→2→4→7→15（直接打仓库，端点不暴露时间旅行）
    conn = get_conn()
    try:
        moment = datetime.now(timezone.utc)
        chain = []
        for _ in range(4):
            scheduled = rrepo.apply(conn, multiple, True, now=moment)
            chain.append(scheduled["interval_days"])
        check("连续答对间隔 1→2→4→7", chain[:3] == [2, 4, 7], str(chain))
        check("间隔到顶后跳到 15", chain[3] == 15, str(chain))
        reset = rrepo.apply(conn, multiple, False, now=moment)
        check("答错重置为 1 天且 lapses+1",
              reset["interval_days"] == 1 and reset["lapses"] >= 2, str(reset))
        check("待人工判断不排期（None 原样返回）", rrepo.apply(conn, multiple, None) is None)
        conn.commit()

        # 从没答错过的题：答对不新建、待判也不新建
        fresh = add_question(item_id, qtype="single", question="从没答错过的题？",
                            options=["A. 甲", "B. 乙"], answer="A")
        rows_before = sql("SELECT COUNT(*) FROM review_item")[0][0]
        check("答对但从未答错 → 不进队列", rrepo.apply(conn, fresh, True) is None)
        check("待人工判断也不建队列行", rrepo.apply(conn, fresh, None) is None)
        conn.commit()
        check("两次都没有新增队列行",
              sql("SELECT COUNT(*) FROM review_item")[0][0] == rows_before)
    finally:
        conn.close()

    # 错题本
    wrong = client.get("/api/quiz/wrong").json()
    ids = [i["question_id"] for i in wrong["items"]]
    check("错题本收最近答错的题", multiple in ids, str(ids))
    check("错题本带错次数与来源标题",
          all(i["wrong_count"] >= 1 and i["source_title"] for i in wrong["items"]))

    client.post("/api/quiz/submit", json={"answers": [
        {"question_id": multiple, "user_answer": ["A", "C"]}]})
    wrong = client.get("/api/quiz/wrong").json()
    check("答对后从错题本消失",
          multiple not in [i["question_id"] for i in wrong["items"]],
          str([i["question_id"] for i in wrong["items"]]))

    # 单独上报结果（人工裁定待判题用）
    resp = client.post(f"/api/review/{multiple}/result", json={"correct": True})
    check("POST /review/{id}/result 推进间隔",
          resp.status_code == 200 and resp.json()["scheduled"] is True, resp.text[:120])
    resp = client.post(f"/api/review/{fresh}/result", json={"correct": True})
    check("未在队列里的题报「答对」→ scheduled=false（不算错误）",
          resp.status_code == 200 and resp.json()["scheduled"] is False, resp.text[:120])
    resp = client.post("/api/review/99999/result", json={"correct": True})
    check("上报不存在的题 → 404 QUESTION_NOT_FOUND",
          resp.status_code == 404 and resp.json()["error"]["code"] == "QUESTION_NOT_FOUND")


# ── 5. 参数校验 ───────────────────────────────────────────
def step_validate(client: TestClient, item_id: int) -> None:
    step("5. 参数校验与错误码")
    short_item = make_item(client, "太短的条目", "太短了。")

    cases = [
        ("count=25 → 422", {"item_id": item_id, "count": 25}, 422, None),
        ("types 非法 → 422 QUIZ_BAD_TYPES",
         {"item_id": item_id, "types": ["essay"]}, 422, "QUIZ_BAD_TYPES"),
        ("difficulty 非法 → 422 QUIZ_BAD_DIFFICULTY",
         {"item_id": item_id, "difficulty": "hard"}, 422, "QUIZ_BAD_DIFFICULTY"),
        ("条目不存在 → 404 ITEM_NOT_FOUND",
         {"item_id": 99999}, 404, "ITEM_NOT_FOUND"),
        ("材料过短 → 400 QUIZ_MATERIAL_TOO_SHORT",
         {"item_id": short_item}, 400, "QUIZ_MATERIAL_TOO_SHORT"),
    ]
    for name, payload, status, code in cases:
        resp = client.post("/api/quiz/generate", json=payload)
        body = resp.json()
        got = body.get("error", {}).get("code") if isinstance(body, dict) else None
        check(name, resp.status_code == status and (code is None or got == code),
              f"{resp.status_code} {got}")

    resp = client.post("/api/quiz/submit", json={"answers": [{"question_id": 99999,
                                                             "user_answer": "A"}]})
    check("提交不存在的题 → 404 QUESTION_NOT_FOUND",
          resp.status_code == 404 and resp.json()["error"]["code"] == "QUESTION_NOT_FOUND")
    resp = client.post("/api/quiz/submit", json={"answers": []})
    check("空答案数组 → 422", resp.status_code == 422, str(resp.status_code))


def cleanup(keep: bool) -> None:
    if keep:
        print(f"\n临时数据目录保留在：{TMP}")
        return
    shutil.rmtree(TMP, ignore_errors=True)


def main() -> int:
    keep = "--keep" in sys.argv[1:]
    print("=" * 62)
    print("  Cairn · M4 验收（T4.8）")
    print("=" * 62)
    print(f"临时数据目录：{TMP}")
    print("向量：关闭（VECTOR_ENABLED=0）　模型：全部假实现（不产生真实调用）")

    aborted = ""
    try:
        with TestClient(app) as client:
            item_id = make_item(client, "番茄工作法")
            step_scan()
            step_generate(client, item_id)
            qids = step_judge(client, item_id)
            step_review(client, qids, item_id)
            step_validate(client, item_id)
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
