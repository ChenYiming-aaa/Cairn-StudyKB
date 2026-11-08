"""T5.4 收尾的 M5 验收脚本：计时生命周期 + 统计口径。

用法：cd backend && uv run python scripts/verify_m5.py [--keep]
退出码：0 全绿 / 1 有用例失败

覆盖：
  1. 生命周期  start → 并发 409 → current → heartbeat → pause / resume → finish（含幂等）
  2. 终止态    abandon 不计入专注统计；跨终态 409；不存在的 id 404
  3. 清理      启动时把 >4 小时仍 running 的标 abandoned，时长按计划封顶（模拟重启）
  4. 学习记录  按条目过滤、只列 done/abandoned
  5. 今日统计  6 个数字逐项与**独立写的 SQL 聚合**对账（不调被验的 repo）
  6. 本周统计  7 天、周一为起点、各日合计 = 周合计
  7. 口径边界  「今天之前的 pending 不算今日待整理」、NULL 不计入正确率分母、分类只取前 8、连续天数今天没学不算断

全程临时 DATA_DIR，不碰 data/data.db；不调模型、不联网。
M5 §6.6 的口径是**文档契约**，所以这里的期望值必须用另写一遍的 SQL 算，不能调 `repo.stats`——
自己跟自己比永远绿，等于没测。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m5-"))
os.environ["DATA_DIR"] = str(TMP)          # 必须早于 import app：get_settings() 首次调用即缓存
os.environ["VECTOR_ENABLED"] = "0"
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

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
    """种一条 ready 条目（给「学习记录」当 target）——不用真实库，也不调模型。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO knowledge_item
                       (title, source_type, raw_content, content_hash, category, status,
                        created_at, updated_at)
                   VALUES (?, 'text', ?, ?, '学习方法', 'ready', ?, ?)""",
                ("番茄钟", "番茄工作法的核心是铃响就停。" * 3, "verify-m5-seed", iso(TODAY),
                 iso(TODAY)),
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
            # ── 1. 生命周期 ────────────────────────────────────────
            step("1. 计时生命周期")

            r = client.get("/api/session/current")
            check("current 无计时返回 session:null", r.status_code == 200 and r.json()["session"] is None)

            r = client.post("/api/session/start", json={
                "target_type": "item", "target_id": item_id, "planned_seconds": 1500,
            })
            body = r.json()
            sid = body.get("id")
            check("start 返回 201 + running", r.status_code == 201 and body.get("status") == "running",
                  f"id={sid}")
            check("start 带上了目标条目标题", body.get("target_title") == "番茄钟",
                  str(body.get("target_title")))
            check("新 session 初始时长 0", body.get("duration_seconds") == 0 and body.get("elapsed_seconds") == 0)

            r2 = client.post("/api/session/start", json={"target_type": "free"})
            err = r2.json().get("error", {})
            check("并发第二次 start → 409 SESSION_ALREADY_RUNNING",
                  r2.status_code == 409 and err.get("code") == "SESSION_ALREADY_RUNNING")
            check("409 的 detail 里带现有 id", f"id={sid}" in (err.get("detail") or ""),
                  str(err.get("detail")))

            r3 = client.post("/api/session/start",
                             json={"target_type": "item", "target_id": 999999})
            check("target_id 不存在 → 404 ITEM_NOT_FOUND",
                  r3.status_code == 404 and r3.json()["error"]["code"] == "ITEM_NOT_FOUND")

            r4 = client.post("/api/session/start",
                             json={"target_type": "bogus", "planned_seconds": 1500})
            check("非法 target_type → 422 SESSION_BAD_TARGET",
                  r4.status_code == 422 and r4.json()["error"]["code"] == "SESSION_BAD_TARGET")

            time.sleep(1.2)
            cur = client.get("/api/session/current").json()["session"]
            check("current 能取回 running 且时长在走", cur["id"] == sid and cur["elapsed_seconds"] >= 1,
                  f"elapsed={cur['elapsed_seconds']}")

            hb = client.post(f"/api/session/{sid}/heartbeat").json()
            anchor_before = cur["start_time"]
            check("heartbeat 把已过时间卷进 duration_seconds",
                  hb["duration_seconds"] >= 1 and hb["status"] == "running",
                  f"duration={hb['duration_seconds']} status={hb['status']}")
            check("heartbeat 把锚点挪到当下", hb["start_time"] > anchor_before,
                  f"{anchor_before} → {hb['start_time']}")

            paused = client.post(f"/api/session/{sid}/pause").json()
            frozen = paused["duration_seconds"]
            check("pause → status=paused", paused["status"] == "paused")
            time.sleep(1.2)
            after = client.get("/api/session/current").json()["session"]
            check("暂停期间时长不再增长",
                  after["status"] == "paused" and after["elapsed_seconds"] == frozen,
                  f"{frozen}s → {after['elapsed_seconds']}s")

            r = client.post("/api/session/start", json={"target_type": "free"})
            check("paused 也算占用：再开一轮仍 409", r.status_code == 409)

            resumed = client.post(f"/api/session/{sid}/resume").json()
            check("resume → running 且已结算时长保留",
                  resumed["status"] == "running" and resumed["duration_seconds"] == frozen,
                  f"duration={resumed['duration_seconds']}")
            time.sleep(1.2)

            done = client.post(f"/api/session/{sid}/finish", json={"note": "铃响就停"}).json()
            check("finish → done + 落笔记",
                  done["status"] == "done" and done["note"] == "铃响就停", str(done.get("note")))
            check("finish 记的是真实有效时长（暂停那段不计）",
                  frozen + 1 <= done["duration_seconds"] <= frozen + 3,
                  f"duration={done['duration_seconds']} 冻结时={frozen}")
            check("finish 写入 end_time", bool(done["end_time"]))

            again = client.post(f"/api/session/{sid}/finish").json()
            check("重复 finish 幂等（时长/end_time/note 不变）",
                  again["duration_seconds"] == done["duration_seconds"]
                  and again["end_time"] == done["end_time"] and again["note"] == done["note"],
                  f"{again['duration_seconds']}s / {again['end_time']}")

            check("finish 后 current 为 null", client.get("/api/session/current").json()["session"] is None)

            # ── 2. 终止态 ──────────────────────────────────────────
            step("2. 放弃与错误码")

            r = client.post("/api/session/start", json={"target_type": "free", "planned_seconds": 1500})
            sid2 = r.json()["id"]
            time.sleep(1.1)
            ab = client.post(f"/api/session/{sid2}/abandon").json()
            check("abandon → abandoned + end_time", ab["status"] == "abandoned" and bool(ab["end_time"]))
            abandoned_seconds = ab["duration_seconds"]

            r = client.post(f"/api/session/{sid2}/resume")
            check("终态再 resume → 409 SESSION_STATE",
                  r.status_code == 409 and r.json()["error"]["code"] == "SESSION_STATE")
            r = client.post(f"/api/session/{sid2}/finish")
            check("abandoned 再 finish → 409（跨终态不是幂等）", r.status_code == 409)
            r = client.post("/api/session/999999/pause")
            check("不存在的 id → 404 SESSION_NOT_FOUND",
                  r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND")
            r = client.post(f"/api/session/{sid2}/dance")
            check("非法 action → 404 SESSION_BAD_ACTION",
                  r.status_code == 404 and r.json()["error"]["code"] == "SESSION_BAD_ACTION")
            r = client.post(f"/api/session/{sid2}/heartbeat")
            check("心跳打到终态会话不报错（闭窗竞态）",
                  r.status_code == 200 and r.json()["status"] == "abandoned")

            # ── 3. 启动清理 ─────────────────────────────────────────
            step("3. 启动清理：>4 小时的 active session")

            with conn:
                conn.execute(
                    """INSERT INTO study_session
                           (target_type, start_time, duration_seconds, planned_seconds, status, created_at)
                       VALUES ('free', ?, 0, 1500, 'running', ?)""",
                    (iso(TODAY), iso(TODAY)),
                )
                stale_id = int(sql(conn, "SELECT MAX(id) FROM study_session")[0][0])
                # 会话开始 5 小时前，且锚点也在 5 小时前（心跳没来过）
                old = (NOW - timedelta(hours=5)).isoformat(timespec="seconds")
                conn.execute(
                    "UPDATE study_session SET start_time=?, created_at=? WHERE id=?",
                    (old, old, stale_id),
                )
            check("种下的 stale 会话确实是 running",
                  sql(conn, "SELECT status FROM study_session WHERE id=?", (stale_id,))[0][0] == "running")

            # 再进一次 lifespan = 模拟重启
            with TestClient(app):
                pass
            row = sql(conn, "SELECT status, duration_seconds FROM study_session WHERE id=?",
                      (stale_id,))[0]
            check("重启后 >4h 的 running 被标 abandoned", row[0] == "abandoned", str(row[0]))
            check("清理时按 planned_seconds 封顶（不然会记成 5 小时）",
                  int(row[1]) == 1500, f"duration={row[1]}")

            # ── 4. 学习记录 ─────────────────────────────────────────
            step("4. 学习记录（按条目）")

            data = client.get("/api/session", params={
                "target_type": "item", "target_id": item_id,
            }).json()
            check("按条目过滤只返回这条的计时",
                  data["total"] == 1 and data["items"][0]["id"] == sid, f"total={data['total']}")
            check("学习记录带标题与笔记",
                  data["items"][0]["target_title"] == "番茄钟"
                  and data["items"][0]["note"] == "铃响就停")
            check("只列终态（running/paused 不混进来）",
                  all(i["status"] in ("done", "abandoned") for i in data["items"]))

            # ── 5. 今日统计对账 ─────────────────────────────────────
            step("5. 今日统计：与独立 SQL 对账")

            # 种数据：今天 2 条 pending、昨天 1 条 pending、3 类分类各若干
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

            exp_focus = sql(conn, """SELECT COALESCE(SUM(duration_seconds),0) FROM study_session
                                       WHERE status='done'
                                         AND date(start_time,'localtime')=?""",
                            (TODAY.isoformat(),))[0][0]
            check("今日专注只算 done", stats["focus_seconds"] == exp_focus == done["duration_seconds"],
                  f"接口={stats['focus_seconds']} SQL={exp_focus}")

            exp_sessions = sql(conn, """SELECT COUNT(*) FROM study_session
                                          WHERE status='done' AND date(start_time,'localtime')=?""",
                               (TODAY.isoformat(),))[0][0]
            check("今日 session 数只算 done（放弃那轮不计）",
                  stats["sessions"] == exp_sessions == 1,
                  f"接口={stats['sessions']} SQL={exp_sessions}")
            check("放弃的时长没有混进专注统计", abandoned_seconds > 0 and stats["focus_seconds"] == exp_focus)

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

            # ── 6. 本周统计 ─────────────────────────────────────────
            step("6. 本周统计")

            # 补两天历史：昨天与前天的 done 会话（连续天数与周合计都要用）
            with conn:
                for offset, seconds in ((1, 600), (2, 900)):
                    day = TODAY - timedelta(days=offset)
                    conn.execute(
                        """INSERT INTO study_session
                               (target_type, start_time, end_time, duration_seconds,
                                planned_seconds, status, created_at)
                           VALUES ('free', ?, ?, ?, 1500, 'done', ?)""",
                        (iso(day, 9), iso(day, 9), seconds, iso(day, 9)),
                    )

            week = client.get("/api/stats/week").json()
            monday = TODAY - timedelta(days=TODAY.weekday())
            check("本周 7 天，从周一开始",
                  len(week["days"]) == 7 and week["days"][0]["date"] == monday.isoformat()
                  and week["days"][0]["label"] == "周一",
                  f"{week['start']} → {week['end']}")
            check("is_today 只标今天一天",
                  [d["date"] for d in week["days"] if d["is_today"]] == [TODAY.isoformat()])

            exp_week = sql(conn, """SELECT COALESCE(SUM(duration_seconds),0) FROM study_session
                                     WHERE status='done'
                                       AND date(start_time,'localtime') BETWEEN ? AND ?""",
                           (monday.isoformat(), TODAY.isoformat()))[0][0]
            check("周合计 = 本周各日之和 = SQL",
                  week["focus_seconds"] == sum(d["focus_seconds"] for d in week["days"])
                  and week["focus_seconds"] == exp_week,
                  f"接口={week['focus_seconds']} SQL={exp_week}")
            check("今日那根柱子与 /stats/today 同一口径",
                  week["days"][TODAY.weekday()]["focus_seconds"] == stats["focus_seconds"])

            stats2 = client.get("/api/stats/today").json()
            check("连续学习天数 = 今天 + 昨天 + 前天",
                  stats2["streak_days"] == 3, f"streak={stats2['streak_days']}")

            # ── 7. 口径边界 ─────────────────────────────────────────
            step("7. 口径边界")

            with conn:
                conn.execute("""INSERT INTO knowledge_item
                                    (title, source_type, raw_content, content_hash, category, status,
                                     created_at, updated_at)
                                VALUES ('一周前', 'text', 'x', 'verify-m5-old', '写作方法',
                                        'pending', ?, ?)""",
                             (iso(TODAY - timedelta(days=7)), iso(TODAY - timedelta(days=7))))
            s3 = client.get("/api/stats/today").json()
            check("更早的 pending 不会算成「今日待整理」",
                  s3["pending_items"] == 2 and s3["pending_total"] == 6,
                  f"今日={s3['pending_items']} 全库={s3['pending_total']}")

            with conn:
                for name in ("类A", "类B", "类C", "类D", "类E", "类F"):
                    conn.execute("""INSERT INTO knowledge_item
                                        (title, source_type, raw_content, content_hash, category,
                                         status, created_at, updated_at)
                                    VALUES (?, 'text', ?, ?, ?, 'ready', ?, ?)""",
                                 (name, name, f"verify-m5-{name}", name, iso(TODAY), iso(TODAY)))
            s4 = client.get("/api/stats/today").json()
            check("分类最多 8 条", len(s4["categories"]) == 8, f"{len(s4['categories'])} 条")

            # 今天没有任何 done session → 连续天数从昨天起算，不从 0 开始
            with conn:
                conn.execute("""UPDATE study_session SET status='abandoned'
                                 WHERE status='done' AND date(start_time,'localtime')=?""",
                             (TODAY.isoformat(),))
            s5 = client.get("/api/stats/today").json()
            check("今天没学不算断：连续天数从昨天起算",
                  s5["streak_days"] == 2 and s5["focus_seconds"] == 0,
                  f"streak={s5['streak_days']} 今日专注={s5['focus_seconds']}")
            check("today 的 9 个统计字段齐全",
                  set(("pending_items", "pending_total", "due_reviews", "focus_seconds",
                       "sessions", "accuracy_today", "categories", "streak_days",
                       "week_focus_seconds")) <= set(s5.keys()), str(sorted(s5.keys())))
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
    except Exception:                                  # noqa: BLE001 - 验收脚本要给出完整栈
        traceback.print_exc()
        sys.exit(1)
