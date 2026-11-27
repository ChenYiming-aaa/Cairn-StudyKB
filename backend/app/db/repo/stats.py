"""仪表盘统计（T5.4）。口径写死在 M5 §6.6，这里只是它的可执行版本。

   今日待整理   knowledge_item.status='pending' 且 created_at 的本地日期 = 今天
   今日待复习   review_item 里 due_at <= now 的条数（不限今天新增）
   连续学习天数 从今天往前推，每天至少有一次「学习动作」（见 `_study_days`）
   正确率       is_correct=1 / is_correct IS NOT NULL（NULL 不进分母）
   分类分布     GROUP BY category 取前 8

**2026-11-17 番茄钟下线**：原来「本周专注」与「连续天数」都按 `study_session` 算，
计时器没了之后这两项会永远是 0。本周专注整块删掉（仪表盘的条形图一并下线）；
连续天数换了口径 —— 有作答、或当天有内容被整理成 ready，都算学过一天。
`study_session` 表与历史数据保留不删，删除内容时的清理逻辑照旧（`repo/items.py:211`）。

两处口径是我补的、M5 §6.6 没写死的（已回写接口契约 §3 与里程碑文档）：

1. **连续天数**：今天还没学**不算断**，从昨天起算；昨天也没有才算 0。
   否则每天零点一过仪表盘就归零，没法用。
2. **「今天」指本地日期**：`date(col,'localtime')` 就是本地日期，跨时区/夏令时不在范围内。

「今日待复习」直接调 `review.due()`，**不在 SQL 里重写一遍** due_at 比较：
那条 UTC/本地混比的坑（数据契约 §3）已经踩过一次，只留一处实现。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from app.db.repo import review as review_repo
from app.db.repo.review import to_aware

TOP_CATEGORIES = 8

# 热力图默认一年（GitHub 那张图的宽度），最少一周、最多一年零一天
HEATMAP_DAYS = 364
HEATMAP_MIN_DAYS = 7
HEATMAP_MAX_DAYS = 366


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now().astimezone()


def _study_days(conn: sqlite3.Connection) -> set[date]:
    """「学过」的那些本地日期：有作答，或当天有内容被整理成 ready。

    两个信号都不完美，选它们是权衡后的结果：
    - 只有作答 → 只看笔记、不出题的日子会被判成没学；
    - 加上 ready 的 `updated_at` → 改个标题也算一天。宁可宽一点，
      也不要把「明明打开了、整理了一篇」的日子算成断掉。
    """
    rows = conn.execute(
        """SELECT DISTINCT date(created_at,'localtime') AS day FROM quiz_attempt
            UNION
           SELECT DISTINCT date(updated_at,'localtime')
             FROM knowledge_item WHERE status='ready'"""
    ).fetchall()
    days: set[date] = set()
    for row in rows:
        try:
            days.add(date.fromisoformat(row[0]))
        except (TypeError, ValueError):     # 脏数据不该让整个仪表盘 500
            continue
    return days


def streak_days(days: set[date], today: date) -> int:
    """连续学习天数：今天没学不算断，从昨天起算（见模块注释）。"""
    cursor = today if today in days else today - timedelta(days=1)
    count = 0
    while cursor in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def _accuracy(conn: sqlite3.Connection, day: str | None = None) -> tuple[float | None, int]:
    """(正确率, 参与判定的作答数)。`day` 为 None 时统计全部历史。"""
    where = "WHERE is_correct IS NOT NULL"
    params: tuple = ()
    if day is not None:
        where += " AND date(created_at,'localtime')=?"
        params = (day,)
    row = conn.execute(
        f"""SELECT COALESCE(SUM(is_correct=1),0), COUNT(*) FROM quiz_attempt {where}""",
        params,
    ).fetchone()
    correct, total = int(row[0]), int(row[1])
    return (round(correct / total, 4) if total else None), total


def _categories(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT COALESCE(NULLIF(TRIM(category),''),'未分类') AS name, COUNT(*) AS count
             FROM knowledge_item GROUP BY name
            ORDER BY count DESC, name LIMIT ?""",
        (TOP_CATEGORIES,),
    ).fetchall()
    return [{"name": row["name"], "count": int(row["count"])} for row in rows]


def today(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    moment = _now(now)
    day = moment.date()
    pending = conn.execute(
        """SELECT COUNT(*) FROM knowledge_item
            WHERE status='pending' AND date(created_at,'localtime')=?""",
        (day.isoformat(),),
    ).fetchone()[0]
    # 「今日新增待整理」经常是 0（昨天进的还没整理完），单独给一个全库待整理做副标题
    pending_total = conn.execute(
        "SELECT COUNT(*) FROM knowledge_item WHERE status='pending'"
    ).fetchone()[0]

    due_reviews = review_repo.due(conn, now=moment, limit=1)[1]
    wrong = review_repo.wrong_total(conn)

    accuracy, attempts = _accuracy(conn, day.isoformat())
    accuracy_all, attempts_all = _accuracy(conn)

    # 「今天学过」单独给一个布尔：界面那句提示不能靠 `attempts_today > 0` 猜 ——
    # 今天整理了一篇但没答题时，连续天数已经把今天算进去了，提示却会说「今天还没学」，
    # 两个数字当场互相打脸。口径只在这里算一次。
    days = _study_days(conn)

    return {
        "date": day.isoformat(),
        "pending_items": int(pending),
        "pending_total": int(pending_total),
        "due_reviews": int(due_reviews),
        "wrong_questions": int(wrong),
        "accuracy_today": accuracy,
        "attempts_today": attempts,
        "accuracy_all": accuracy_all,
        "attempts_all": attempts_all,
        "streak_days": streak_days(days, day),
        "studied_today": day in days,
        "categories": _categories(conn),
    }


def heatmap(
    conn: sqlite3.Connection, *, days: int = HEATMAP_DAYS, now: datetime | None = None
) -> dict:
    """逐日学习强度（GitHub 贡献图那张表）。

    一格 = 一个本地日期，强度 = **当天作答次数 + 当天整理成 ready 的篇数**。
    和 `_study_days()` 用同一对信号，所以「热力图上有格子」与「连续天数算一天」
    永远是同一件事，不会一个亮着一个说没学。

    已知的不精确：`ready` 内容按 `updated_at` 归日，改一次标题也会点亮今天。
    这和连续天数用的是同一条口径 —— 宁可宽一点，也不要把「打开了、整理了一篇」
    的日子算成断掉；真正的作答数在 `attempts` 里单列，界面提示可以分开说。

    返回连续日期（含没有记录的 0 格），前端只负责排版，不补日期、不算强度。
    """
    moment = _now(now)
    end = moment.date()
    span = max(HEATMAP_MIN_DAYS, min(HEATMAP_MAX_DAYS, int(days)))
    start = end - timedelta(days=span - 1)

    def _by_day(sql: str) -> dict[str, int]:
        rows = conn.execute(sql, (start.isoformat(),)).fetchall()
        return {row[0]: int(row[1]) for row in rows if row[0]}

    attempts = _by_day(
        """SELECT date(created_at,'localtime') AS day, COUNT(*)
             FROM quiz_attempt
            WHERE date(created_at,'localtime') >= ?
            GROUP BY day"""
    )
    organized = _by_day(
        """SELECT date(updated_at,'localtime') AS day, COUNT(*)
             FROM knowledge_item
            WHERE status='ready' AND date(updated_at,'localtime') >= ?
            GROUP BY day"""
    )

    cells = []
    for offset in range(span):
        day = (start + timedelta(days=offset)).isoformat()
        done = attempts.get(day, 0)
        made = organized.get(day, 0)
        cells.append({
            "date": day,
            "attempts": done,
            "organized": made,
            "count": done + made,
        })

    active = [cell["count"] for cell in cells if cell["count"]]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": span,
        "total": sum(active),
        "active_days": len(active),
        "max_count": max(active, default=0),
        "cells": cells,
    }


def mastery(conn: sqlite3.Connection, item_id: int, now: datetime | None = None) -> dict | None:
    """一条内容「现在到底会不会」：按题算，不按次数算。

    口径（一句话）：**最近一次有判定的作答答对的题数 / 该内容全部题数**。

    - 分母是题目总数，不是练过的题数 —— 没练过的题也算「还没掌握」，
      否则只练一道题答对就是 100%。
    - 分子取**每道题最近一次有判定**的结果：同一道题先对后错，算错。
      最近一次是「待人工判断」（`is_correct IS NULL`）时不算对，单列 `pending`，
      不静默当成错、也不当成对。
    - `accuracy` 是另一个问题（练过的题里对了几道），与 `mastery` 分开给，
      界面别拿一个当另一个。

    内容不存在返回 None（路由转 404）；没有题目时 `mastery` 为 None，
    不是 0 —— 「还没出过题」和「一题都不会」是两件事。
    """
    exists = conn.execute("SELECT 1 FROM knowledge_item WHERE id=?", (item_id,)).fetchone()
    if not exists:
        return None

    moment = _now(now)
    rows = conn.execute(
        """SELECT q.id,
                  EXISTS(SELECT 1 FROM quiz_attempt a WHERE a.question_id=q.id) AS attempted,
                  (SELECT a.is_correct FROM quiz_attempt a
                    WHERE a.question_id=q.id ORDER BY a.id DESC LIMIT 1) AS last_correct
             FROM question q
            WHERE q.item_id=?""",
        (item_id,),
    ).fetchall()

    questions = len(rows)
    practiced = sum(1 for row in rows if row["attempted"])
    graded = sum(1 for row in rows if row["attempted"] and row["last_correct"] is not None)
    correct = sum(1 for row in rows if row["last_correct"] == 1)
    pending = sum(1 for row in rows if row["attempted"] and row["last_correct"] is None)

    due = 0
    lapses = 0
    for row in conn.execute(
        """SELECT r.due_at, r.lapses
             FROM review_item r JOIN question q ON q.id = r.question_id
            WHERE q.item_id=?""",
        (item_id,),
    ).fetchall():
        lapses += int(row["lapses"] or 0)
        if to_aware(row["due_at"]) <= moment:
            due += 1

    last = conn.execute(
        """SELECT MAX(a.created_at)
             FROM quiz_attempt a JOIN question q ON q.id = a.question_id
            WHERE q.item_id=?""",
        (item_id,),
    ).fetchone()[0]

    return {
        "item_id": item_id,
        "questions": questions,
        "practiced": practiced,
        "graded": graded,
        "correct": correct,
        "pending": pending,
        "accuracy": round(correct / graded, 4) if graded else None,
        "mastery": round(correct / questions * 100) if questions else None,
        "due": due,
        "lapses": lapses,
        "last_attempt_at": last,
    }
