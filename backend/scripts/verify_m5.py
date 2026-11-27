"""M5 验收脚本（统计口径 + 首次引导保存 Key）。

用法：cd backend && uv run python scripts/verify_m5.py [--keep]
退出码：0 全绿 / 1 有用例失败

**2026-11-17 番茄钟下线**（见 `docs/dev/功能价值审计-2026-11-17.md` §九）：
计时生命周期、放弃/清理、学习记录、本周条形图这几组连同 `/api/session/*` 与
`/api/stats/week` 一起移除；「连续学习天数」换了口径（作答或整理好内容都算学过一天）。
所以本脚本现在覆盖：

  1. 今日统计  `pending_items / pending_total / due_reviews / accuracy / categories`
     逐项与**独立写的 SQL 聚合**对账（不调被验的 repo）
  2. 连续天数  作答与「整理成 ready」都算学过；今天没学不算断；没有动作的日期会断
  3. 口径边界  「今天之前的 pending 不算今日待整理」、NULL 不计入正确率分母、分类只取前 8
  4. 学习记录  热力图逐格与独立 SQL 对账；掌握度按「最近一次判定的答对题数 / 全部题数」
  5. 已下线    `/api/session/*` 与 `/api/stats/week` 必须 404（防止有人顺手加回来）
  6. 首次引导  保存 Key 到 .env（T5.7）

全程临时 DATA_DIR，不碰 data/data.db；不调模型、不联网。
M5 §6.6 的口径是**文档契约**，所以这里的期望值必须用另写一遍的 SQL 算，不能调 `repo.stats`——
自己跟自己比永远绿，等于没测。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m5-"))
os.environ["DATA_DIR"] = str(TMP)          # 必须早于 import app：get_settings() 首次调用即缓存
os.environ["CAIRN_NO_AUTO_ORGANIZE"] = "1"   # 2026-11-17：本脚本验具体机制，自动整理会改动中间态（m1 末尾单独验它）
os.environ["VECTOR_ENABLED"] = "0"
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import reload_settings  # noqa: E402
from app.db.conn import get_conn  # noqa: E402
from app.db.migrate import init_db  # noqa: E402
from app.main import app  # noqa: E402

DB = TMP / "data.db"
RESULTS: list[tuple[bool, str]] = []
NOW = datetime.now().astimezone()
TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((ok, name))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


def sql(conn, query: str, args: tuple = ()):
    return conn.execute(query, args).fetchall()


def iso(day, hour: int = 10) -> str:
    return datetime(day.year, day.month, day.day, hour, 0, 0).astimezone().isoformat(
        timespec="seconds"
    )


def seed() -> int:
    """种一条 ready 条目（给题目当 item_id）——不用真实库，也不调模型。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO knowledge_item
                       (title, source_type, raw_content, content_hash, category, status,
                        created_at, updated_at)
                   VALUES (?, 'text', ?, ?, '学习方法', 'ready', ?, ?)""",
                ("间隔重复", "间隔重复的核心是让检索发生在快要忘记的时候。" * 3,
                 "verify-m5-seed", iso(TODAY), iso(TODAY)),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def main() -> int:
    init_db()                       # lifespan 还没跑，先建库再种数据
    item_id = seed()
    conn = get_conn()
    try:
        with TestClient(app) as client:
            # ── 1. 今日统计对账 ────────────────────────────────────
            step("1. 今日统计：与独立 SQL 对账")

            # 种数据：今天 2 条 pending、昨天 3 条 pending、3 类分类各若干
            with conn:
                for title, day, category in [
                    ("今天甲", TODAY, "写作方法"),
                    ("今天乙", TODAY, "写作方法"),
                    ("昨天丙", YESTERDAY, "记忆方法"),
                    ("昨天丁", YESTERDAY, "记忆方法"),
                    ("昨天戊", YESTERDAY, "科技人物"),
                ]:
                    conn.execute(
                        """INSERT INTO knowledge_item
                               (title, source_type, raw_content, content_hash, category, status,
                                created_at, updated_at)
                           VALUES (?, 'text', ?, ?, ?, 'pending', ?, ?)""",
                        (title, title, f"verify-m5-{title}", category, iso(day), iso(day)),
                    )
                # 题目 + 作答：今天 3 次（2 对 1 错）+ 1 次待人工判断（NULL 不进分母）
                cur = conn.execute(
                    """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
                       VALUES (?, 'single', 'basic', '{}', 'verify-m5-q1', ?)""",
                    (item_id, iso(TODAY)),
                )
                qid = int(cur.lastrowid)
                for correct in (1, 1, 0, None):
                    conn.execute(
                        """INSERT INTO quiz_attempt (question_id, user_answer, is_correct, created_at)
                           VALUES (?, '[]', ?, ?)""",
                        (qid, correct, iso(TODAY)),
                    )
                # 复习队列：1 条已到期、1 条未来
                conn.execute(
                    """INSERT INTO review_item (question_id, due_at, interval_days, updated_at)
                       VALUES (?, ?, 1, ?)""",
                    (qid, iso(YESTERDAY), iso(TODAY)),
                )
                cur = conn.execute(
                    """INSERT INTO question (item_id, type, difficulty, payload, fingerprint, created_at)
                       VALUES (?, 'single', 'basic', '{}', 'verify-m5-q2', ?)""",
                    (item_id, iso(TODAY)),
                )
                conn.execute(
                    """INSERT INTO review_item (question_id, due_at, interval_days, updated_at)
                       VALUES (?, ?, 2, ?)""",
                    (int(cur.lastrowid), iso(TODAY + timedelta(days=3)), iso(TODAY)),
                )

            stats = client.get("/api/stats/today").json()

            exp_pending = sql(conn, """SELECT COUNT(*) FROM knowledge_item
                                        WHERE status='pending'
                                          AND date(created_at,'localtime')=?""",
                              (TODAY.isoformat(),))[0][0]
            check("今日待整理 = 只看今天创建的 pending（昨天的不算）",
                  stats["pending_items"] == exp_pending == 2,
                  f"接口={stats['pending_items']} SQL={exp_pending}")
            check("全库待整理单独给出", stats["pending_total"] == 5, str(stats["pending_total"]))

            exp_due = sql(conn, "SELECT COUNT(*) FROM review_item WHERE due_at <= ?",
                          (NOW.isoformat(timespec="seconds"),))[0][0]
            check("今日待复习 = due_at 已过的条数", stats["due_reviews"] == exp_due == 1,
                  f"接口={stats['due_reviews']} SQL={exp_due}")

            check("正确率 = 对/有判定（NULL 不进分母）",
                  stats["accuracy_today"] == round(2 / 3, 4) and stats["attempts_today"] == 3,
                  f"{stats['accuracy_today']} / {stats['attempts_today']} 次")

            cats = stats["categories"]
            exp_cats = sql(conn, """SELECT COUNT(*) FROM knowledge_item
                                     WHERE COALESCE(NULLIF(TRIM(category),''),'未分类')=?""",
                           ("写作方法",))[0][0]
            by_name = {c["name"]: c["count"] for c in cats}
            check("分类分布与 SQL 一致",
                  by_name.get("写作方法") == exp_cats and by_name.get("记忆方法") == 2,
                  str(by_name))
            check("分类按数量倒序", [c["count"] for c in cats] == sorted(
                [c["count"] for c in cats], reverse=True))

            # ── 2. 连续学习天数（作答 + 整理，替代已下线的计时）────────
            step("2. 连续学习天数")

            check("今天有作答 → 连续 1 天", stats["streak_days"] == 1, f"streak={stats['streak_days']}")
            check("今天有作答 → studied_today=true（界面那句提示只看这个字段）",
                  stats["studied_today"] is True, str(stats["studied_today"]))

            # 把今天的作答整体挪到昨天，把那条 ready 内容的 updated_at 挪到前天：
            # 今天一次动作都没有，连续天数应该从昨天起算 = 2，而不是归零
            with conn:
                conn.execute("UPDATE quiz_attempt SET created_at=? WHERE date(created_at,'localtime')=?",
                             (iso(YESTERDAY), TODAY.isoformat()))
                conn.execute("UPDATE knowledge_item SET updated_at=? WHERE id=?",
                             (iso(TODAY - timedelta(days=2)), item_id))
            s2 = client.get("/api/stats/today").json()
            check("今天没学不算断：从昨天起算 = 2（昨天作答 + 前天整理）",
                  s2["streak_days"] == 2, f"streak={s2['streak_days']}")
            # 今天一次动作都没有 → studied_today 必须是 false，否则界面会说「今天已经学过了」
            check("今天没动作 → studied_today=false", s2["studied_today"] is False,
                  str(s2["studied_today"]))

            # 中间空一天就要断：把昨天的作答挪到 5 天前 → 昨天没人学，
            # 前天那次整理接不上（连续要求从昨天往前不断），streak 归 0
            with conn:
                conn.execute("UPDATE quiz_attempt SET created_at=? WHERE date(created_at,'localtime')=?",
                             (iso(TODAY - timedelta(days=5)), YESTERDAY.isoformat()))
            s3 = client.get("/api/stats/today").json()
            check("昨天断档 → 连续归 0（前天那次接不上）",
                  s3["streak_days"] == 0, f"streak={s3['streak_days']}")

            # ── 3. 口径边界 ─────────────────────────────────────────
            step("3. 口径边界")

            with conn:
                conn.execute("""INSERT INTO knowledge_item
                                    (title, source_type, raw_content, content_hash, category, status,
                                     created_at, updated_at)
                                VALUES ('一周前', 'text', 'x', 'verify-m5-old', '写作方法',
                                        'pending', ?, ?)""",
                             (iso(TODAY - timedelta(days=7)), iso(TODAY - timedelta(days=7))))
            s4 = client.get("/api/stats/today").json()
            check("更早的 pending 不会算成「今日待整理」",
                  s4["pending_items"] == 2 and s4["pending_total"] == 6,
                  f"今日={s4['pending_items']} 全库={s4['pending_total']}")

            with conn:
                for name in ("类A", "类B", "类C", "类D", "类E", "类F"):
                    conn.execute("""INSERT INTO knowledge_item
                                        (title, source_type, raw_content, content_hash, category,
                                         status, created_at, updated_at)
                                    VALUES (?, 'text', ?, ?, ?, 'ready', ?, ?)""",
                                 (name, name, f"verify-m5-{name}", name, iso(TODAY), iso(TODAY)))
            s5 = client.get("/api/stats/today").json()
            check("分类最多 8 条", len(s5["categories"]) == 8, f"{len(s5['categories'])} 条")

            check("today 的字段就是这 12 个（计时相关字段已随番茄钟下线）",
                  set(s5) == {
                      "date", "pending_items", "pending_total", "due_reviews", "wrong_questions",
                      "accuracy_today", "attempts_today", "accuracy_all", "attempts_all",
                      "streak_days", "studied_today", "categories",
                  },
                  str(sorted(s5)))

            # ── 4. 学习记录热力图与掌握度 ───────────────────────────
            step("4. 学习记录热力图与掌握度")

            heat = client.get("/api/stats/heatmap").json()
            check("热力图默认一年、返回连续日期",
                  heat["days"] == 364 and len(heat["cells"]) == 364
                  and heat["cells"][-1]["date"] == TODAY.isoformat()
                  and heat["cells"][0]["date"] == (TODAY - timedelta(days=363)).isoformat(),
                  f"{heat['days']} 天 / {len(heat['cells'])} 格 / "
                  f"{heat['cells'][0]['date']} → {heat['cells'][-1]['date']}")

            # 逐格与另写的 SQL 对账：作答按 created_at 的本地日期，ready 按 updated_at
            exp_attempts = {row[0]: int(row[1]) for row in sql(
                conn,
                """SELECT date(created_at,'localtime') AS day, COUNT(*)
                     FROM quiz_attempt WHERE date(created_at,'localtime') >= ?
                    GROUP BY day""",
                (heat["start"],),
            )}
            exp_ready = {row[0]: int(row[1]) for row in sql(
                conn,
                """SELECT date(updated_at,'localtime') AS day, COUNT(*)
                     FROM knowledge_item
                    WHERE status='ready' AND date(updated_at,'localtime') >= ?
                    GROUP BY day""",
                (heat["start"],),
            )}
            mismatched = [
                (cell["date"], cell["count"], exp_attempts.get(cell["date"], 0)
                 + exp_ready.get(cell["date"], 0))
                for cell in heat["cells"]
                if cell["count"] != exp_attempts.get(cell["date"], 0)
                + exp_ready.get(cell["date"], 0)
            ]
            check("每格 = 当天作答数 + 当天整理完成数（独立 SQL 对账）",
                  not mismatched, str(mismatched[:3]))
            check("attempts / organized 分开给（提示框要能说清是哪一种）",
                  all({"attempts", "organized"} <= set(cell) for cell in heat["cells"]))

            today_cell = heat["cells"][-1]
            check("今天的格子 = 6 篇整理，0 次作答",
                  today_cell == {"date": TODAY.isoformat(), "attempts": 0,
                                 "organized": 6, "count": 6},
                  str(today_cell))
            check("汇总与逐格一致",
                  heat["total"] == sum(c["count"] for c in heat["cells"])
                  and heat["active_days"] == sum(1 for c in heat["cells"] if c["count"])
                  and heat["max_count"] == max(c["count"] for c in heat["cells"]),
                  f"total={heat['total']} active={heat['active_days']} max={heat['max_count']}")

            week = client.get("/api/stats/heatmap", params={"days": 7}).json()
            check("days=7 → 只回一周，且仍以今天结尾",
                  week["days"] == 7 and len(week["cells"]) == 7
                  and week["cells"][-1]["date"] == TODAY.isoformat(),
                  f"{week['days']} / {len(week['cells'])}")
            check("days 越界 → 422（不静默截断成别的窗口）",
                  client.get("/api/stats/heatmap", params={"days": 3}).status_code == 422
                  and client.get("/api/stats/heatmap", params={"days": 400}).status_code == 422)

            # 掌握度：q1 的最近一次是 NULL（待人工判断）→ 不算对、也不算错；
            # q2 有题没作答 → 分母仍算它
            mastery = client.get(f"/api/stats/mastery/{item_id}").json()
            check("掌握度分母是全部题（没练过的也算没掌握）",
                  mastery["questions"] == 2 and mastery["practiced"] == 1
                  and mastery["mastery"] == 0,
                  f"{mastery['correct']}/{mastery['questions']} = {mastery['mastery']}%")
            check("最近一次待人工判断 → 不算对、不计入正确率分母、单列 pending",
                  mastery["correct"] == 0 and mastery["graded"] == 0
                  and mastery["accuracy"] is None and mastery["pending"] == 1,
                  f"graded={mastery['graded']} pending={mastery['pending']}")
            check("待复习与 lapses 只算这条内容的题",
                  mastery["due"] == 1 and mastery["lapses"] == 0,
                  f"due={mastery['due']} lapses={mastery['lapses']}")

            with conn:
                conn.execute(
                    """INSERT INTO quiz_attempt (question_id, user_answer, is_correct, created_at)
                       VALUES (?, '[]', 1, ?)""",
                    (qid, iso(TODAY, 12)),
                )
            m2 = client.get(f"/api/stats/mastery/{item_id}").json()
            check("最新一次答对 → 算对（同一道题先对后错就翻回去）",
                  m2["correct"] == 1 and m2["graded"] == 1 and m2["accuracy"] == 1.0
                  and m2["mastery"] == 50 and m2["pending"] == 0,
                  f"{m2['correct']}/{m2['questions']} accuracy={m2['accuracy']}")

            with conn:
                conn.execute(
                    """INSERT INTO quiz_attempt (question_id, user_answer, is_correct, created_at)
                       VALUES (?, '[]', 0, ?)""",
                    (qid, iso(TODAY, 13)),
                )
            m3 = client.get(f"/api/stats/mastery/{item_id}").json()
            check("只看最新一次：先对后错 → 掌握度掉回 0",
                  m3["correct"] == 0 and m3["accuracy"] == 0 and m3["mastery"] == 0,
                  f"correct={m3['correct']} accuracy={m3['accuracy']}")

            # 没有题的内容：mastery 必须是 null，不能拿 0 冒充「一题都不会」
            with conn:
                cur = conn.execute(
                    """INSERT INTO knowledge_item (title, source_type, raw_content, content_hash,
                                                   status, created_at, updated_at)
                       VALUES ('没有题', 'text', 'x', 'verify-m5-noq', 'ready', ?, ?)""",
                    (iso(TODAY), iso(TODAY)),
                )
                noq = int(cur.lastrowid)
            empty = client.get(f"/api/stats/mastery/{noq}").json()
            check("没有题 → mastery/accuracy 都是 null，不是 0",
                  empty["questions"] == 0 and empty["mastery"] is None
                  and empty["accuracy"] is None, str(empty))

            r = client.get("/api/stats/mastery/999999")
            check("内容不存在 → 404 ITEM_NOT_FOUND",
                  r.status_code == 404
                  and r.json()["error"]["code"] == "ITEM_NOT_FOUND",
                  str(r.json().get("error")))

            # ── 5. 已下线的端点 ─────────────────────────────────────
            step("5. 番茄钟下线后的端点")

            for path in ("/api/session", "/api/session/current", "/api/stats/week"):
                r = client.get(path)
                check(f"GET {path} 已下线 → 404", r.status_code == 404, str(r.status_code))
            r = client.post("/api/session/start", json={})
            check("POST /api/session/start 已下线 → 404", r.status_code == 404, str(r.status_code))

            # ── 6. 首次引导：保存 Key（T5.7）────────────────────────
            step("6. 首次引导：保存 Key 到 .env")

            r = client.post("/api/env/key", json={})
            check("空请求 → 400 ENV_NOTHING_TO_SAVE",
                  r.status_code == 400
                  and r.json()["error"]["code"] == "ENV_NOTHING_TO_SAVE",
                  str(r.json().get("error")))

            # 换行会把一行 .env 拆成两行 = 允许写任意环境变量，必须挡住
            r = client.post("/api/env/key", json={"llm_api_key": "sk-x\nDATA_DIR=/tmp/evil"})
            check("Key 带换行 → 400 ENV_INVALID_VALUE",
                  r.status_code == 400
                  and r.json()["error"]["code"] == "ENV_INVALID_VALUE",
                  str(r.json().get("error")))

            env_path = TMP / ".env"
            env_path.write_text("# 手工配置，不许被清掉\nFFMPEG_DIR=\n", encoding="utf-8")
            r = client.post("/api/env/key", json={"llm_api_key": "sk-verify-only-0001"})
            body = r.json()
            text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            check("保存成功且 llm 立刻变绿（不用重启）",
                  r.status_code == 200 and body.get("saved") is True
                  and body["check"]["llm"]["ok"], str(body.get("check", {}).get("llm")))
            check("落盘到当前数据目录的 .env",
                  Path(body.get("env_file", "")) == env_path, str(body.get("env_file")))
            check("Key 真的写进了文件", "LLM_API_KEY" in text)
            check("已有的其它行与注释没被清掉",
                  "手工配置" in text and "FFMPEG_DIR" in text)
            check("响应里不含 Key 明文（红线 7）", "sk-verify-only-0001" not in r.text)

            # 收尾：把假 Key 从进程环境里摘掉，别影响后面的用例
            os.environ.pop("LLM_API_KEY", None)
            env_path.unlink(missing_ok=True)
            reload_settings()
    finally:
        conn.close()

    total = len(RESULTS)
    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\n{'=' * 56}\n  {passed}/{total} 通过")
    if passed != total:
        print("  失败用例：")
        for ok, name in RESULTS:
            if not ok:
                print(f"    - {name}")
    print(f"  临时数据目录：{TMP}" + ("" if "--keep" in sys.argv else "（可删）"))
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                      # noqa: BLE001 - 脚本顶层要把栈打全
        traceback.print_exc()
        sys.exit(2)
