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

TOP_CATEGORIES = 8


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
