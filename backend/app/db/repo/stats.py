"""仪表盘统计（T5.4）。口径写死在 M5 §6.6，这里只是它的可执行版本。

   今日待整理   knowledge_item.status='pending' 且 created_at 的本地日期 = 今天
   今日待复习   review_item 里 due_at <= now 的条数（不限今天新增）
   本周专注     本周一 00:00 起 status='done' 的 duration_seconds 之和
   连续学习天数 从今天往前推，每天至少一条 done session
   正确率       is_correct=1 / is_correct IS NOT NULL（NULL 不进分母）
   分类分布     GROUP BY category 取前 8

两处口径是我补的、M5 §6.6 没写死的（已回写接口契约 §3 与里程碑文档）：

1. **连续天数**：今天还没学**不算断**，从昨天起算；昨天也没有才算 0。
   否则每天零点一过仪表盘就归零，没法用。
2. **「今天」指本地日期**。`study_session.start_time` 带 `+08:00` 偏移，
   按本地日期分组即可；跨时区/夏令时不在本项目范围内。

「今日待复习」直接调 `review.due()`，**不在 SQL 里重写一遍** due_at 比较：
那条 UTC/本地混比的坑（数据契约 §3）已经踩过一次，只留一处实现。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from app.db.repo import review as review_repo
from app.db.repo.sessions import parse

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
TOP_CATEGORIES = 8


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now().astimezone()


def _done_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT id, start_time, duration_seconds, target_type, target_id
             FROM study_session WHERE status='done'"""
    ).fetchall()


def _by_day(rows) -> dict[date, tuple[int, int]]:
    """本地日期 → (session 数, 专注秒数)。"""
    bucket: dict[date, tuple[int, int]] = {}
    for row in rows:
        try:
            day = parse(row["start_time"]).date()
        except ValueError:                     # 脏数据不该让整个仪表盘 500
            continue
        count, seconds = bucket.get(day, (0, 0))
        bucket[day] = (count + 1, seconds + int(row["duration_seconds"] or 0))
    return bucket


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

    done = _done_rows(conn)
    by_day = _by_day(done)
    sessions, focus = by_day.get(day, (0, 0))
    week_start = day - timedelta(days=day.weekday())
    week_focus = sum(
        seconds for d, (_, seconds) in by_day.items() if week_start <= d <= day
    )

    accuracy, attempts = _accuracy(conn, day.isoformat())
    accuracy_all, attempts_all = _accuracy(conn)

    return {
        "date": day.isoformat(),
        "pending_items": int(pending),
        "pending_total": int(pending_total),
        "due_reviews": int(due_reviews),
        "wrong_questions": int(wrong),
        "focus_seconds": int(focus),
        "sessions": int(sessions),
        "week_focus_seconds": int(week_focus),
        "accuracy_today": accuracy,
        "attempts_today": attempts,
        "accuracy_all": accuracy_all,
        "attempts_all": attempts_all,
        "streak_days": streak_days(set(by_day), day),
        "categories": _categories(conn),
    }


def week(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    moment = _now(now)
    day = moment.date()
    monday = day - timedelta(days=day.weekday())
    by_day = _by_day(_done_rows(conn))

    days = []
    for offset in range(7):
        current = monday + timedelta(days=offset)
        sessions, seconds = by_day.get(current, (0, 0))
        days.append({
            "date": current.isoformat(),
            "weekday": offset + 1,
            "label": WEEKDAYS[offset],
            "sessions": int(sessions),
            "focus_seconds": int(seconds),
            "is_today": current == day,
            "is_future": current > day,
        })

    return {
        "start": monday.isoformat(),
        "end": (monday + timedelta(days=6)).isoformat(),
        "today": day.isoformat(),
        "days": days,
        "focus_seconds": sum(item["focus_seconds"] for item in days),
        "sessions": sum(item["sessions"] for item in days),
        "streak_days": streak_days(set(by_day), day),
    }
