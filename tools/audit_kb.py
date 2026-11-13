#!/usr/bin/env python
"""Cairn 实测对账：把「界面上看到的东西」和「库里真实的东西」对一遍。

默认只读，不写任何数据。唯一的写操作是 --make-due（复习时间旅行），
执行前必须**完全退出 Cairn**，否则会和正在运行的进程抢锁。

用法：
    python tools/audit_kb.py                  # 读 %APPDATA%\\Cairn\\data.db
    python tools/audit_kb.py --db <path>      # 指定库（比如备份出来的副本）
    python tools/audit_kb.py --json           # 机器可读，便于存档比对
    python tools/audit_kb.py --make-due 3     # 【写】把复习到期时间整体前移 3 小时

退出码：0 正常；2 发现一致性异常（用来在脚本里卡住流程）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

TABLES = [
    "knowledge_item",
    "chunk",
    "agent_task",
    "html_artifact",
    "question",
    "quiz_attempt",
    "review_item",
    "study_session",
    "llm_call_log",
    "ask_log",
]


def default_db() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("找不到 %APPDATA%，请用 --db 指定 data.db")
    return Path(appdata) / "Cairn" / "data.db"


def open_ro(db: Path) -> sqlite3.Connection:
    """只读打开。WAL 库在应用关闭后可能没有 -shm，只读连接会打不开，
    这时把 data.db / -wal / -shm 拷到临时目录再读（副本，不动原件）。"""
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=3)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        return conn
    except sqlite3.Error:
        tmp = Path(tempfile.mkdtemp(prefix="cairn-audit-"))
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(db) + suffix)
            if src.exists():
                shutil.copy2(src, tmp / (db.name + suffix))
        conn = sqlite3.connect(str(tmp / db.name), timeout=3)
        conn.tmpdir = tmp  # type: ignore[attr-defined]
        return conn


def scalar(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> int:
    row = conn.execute(sql, args).fetchone()
    return int(row[0] or 0) if row else 0


def has_table(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)
        ).fetchone()
        is not None
    )


def try_load_vec(conn: sqlite3.Connection) -> bool:
    """有 sqlite-vec 就加载（否则 chunk_vec 这种 vec0 虚拟表查不了）。装在 backend 的
    uv 环境里就能用：`cd backend && uv run python ../tools/audit_kb.py`。"""
    try:
        import sqlite_vec  # type: ignore
    except Exception:
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def collect(conn: sqlite3.Connection) -> dict:
    now = datetime.now(timezone.utc)
    data: dict = {"generated_at": now.astimezone().isoformat(timespec="seconds")}

    total = scalar(conn, "SELECT COUNT(*) FROM knowledge_item")
    data["items"] = {
        "total": total,
        "by_status": {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT status, COUNT(*) FROM knowledge_item GROUP BY status ORDER BY 2 DESC"
            )
        },
        "by_source": {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT source_type, COUNT(*) FROM knowledge_item GROUP BY source_type ORDER BY 2 DESC"
            )
        },
        "note_edited": scalar(conn, "SELECT COUNT(*) FROM knowledge_item WHERE note_edited=1"),
        "truncated": scalar(conn, "SELECT COUNT(*) FROM knowledge_item WHERE truncated=1"),
        "categories": scalar(
            conn,
            "SELECT COUNT(DISTINCT category) FROM knowledge_item WHERE category IS NOT NULL AND category<>''",
        ),
    }

    # chunk_vec 是 vec0 虚拟表，不加载 sqlite-vec 扩展查询会报 "no such module: vec0"。
    # 这里的目的只是数行数，读不到就记 None，不要因此让整份体检失败。
    try:
        vec_rows = (
            scalar(conn, "SELECT COUNT(*) FROM chunk_vec") if has_table(conn, "chunk_vec") else None
        )
    except sqlite3.Error:
        vec_rows = None

    data["index"] = {
        "chunk_raw": scalar(conn, "SELECT COUNT(*) FROM chunk WHERE source='raw'"),
        "chunk_note": scalar(conn, "SELECT COUNT(*) FROM chunk WHERE source='note'"),
        "fts_rows": scalar(conn, "SELECT COUNT(*) FROM chunk_fts")
        if has_table(conn, "chunk_fts")
        else None,
        "vec_rows": vec_rows,
    }

    data["tasks"] = {
        "by_status": {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT status, COUNT(*) FROM agent_task GROUP BY status ORDER BY 2 DESC"
            )
        },
        "by_type": {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT type, COUNT(*) FROM agent_task GROUP BY type ORDER BY 2 DESC"
            )
        },
        "recent_failed": [
            {
                "type": r[0],
                "error_code": r[1],
                "error_msg": (r[2] or "")[:120],
                "updated_at": r[3],
            }
            for r in conn.execute(
                "SELECT type, error_code, error_msg, updated_at FROM agent_task "
                "WHERE status='failed' ORDER BY updated_at DESC LIMIT 5"
            )
        ],
        "stale_running": [
            {"type": r[0], "updated_at": r[1]}
            for r in conn.execute(
                "SELECT type, updated_at FROM agent_task WHERE status IN ('queued','running')"
            )
            if (parse_dt(r[1]) and (now - parse_dt(r[1])).total_seconds() > 900)
        ],
    }

    data["quiz"] = {
        "questions": scalar(conn, "SELECT COUNT(*) FROM question"),
        "by_type": {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT type, COUNT(*) FROM question GROUP BY type ORDER BY 2 DESC"
            )
        },
        "attempts": scalar(conn, "SELECT COUNT(*) FROM quiz_attempt"),
        "correct": scalar(conn, "SELECT COUNT(*) FROM quiz_attempt WHERE is_correct=1"),
        "wrong": scalar(conn, "SELECT COUNT(*) FROM quiz_attempt WHERE is_correct=0"),
        "ungraded": scalar(conn, "SELECT COUNT(*) FROM quiz_attempt WHERE is_correct IS NULL"),
    }

    review_rows = list(
        conn.execute(
            "SELECT due_at, interval_days, lapses, last_result FROM review_item"
        )
    )
    due_now = 0
    for due_at, _, _, _ in review_rows:
        dt = parse_dt(due_at)
        if dt and dt <= now:
            due_now += 1
    data["review"] = {
        "tracked": len(review_rows),
        "due_now": due_now,
        "intervals": {
            str(k): v
            for k, v in sorted(
                {d: sum(1 for r in review_rows if r[1] == d) for d in {r[1] for r in review_rows}}.items()
            )
        },
        "lapsed": sum(1 for r in review_rows if (r[2] or 0) > 0),
        "last_wrong": sum(1 for r in review_rows if r[3] == 0),
    }

    completed = list(
        conn.execute(
            "SELECT duration_seconds, planned_seconds, status FROM study_session"
        )
    )
    data["focus"] = {
        "sessions": len(completed),
        "by_status": {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT status, COUNT(*) FROM study_session GROUP BY status"
            )
        },
        "completed_minutes": round(
            sum(r[0] for r in completed if r[2] == "done") / 60, 1
        ),
    }

    data["artifacts"] = {
        "html_pages": scalar(conn, "SELECT COUNT(*) FROM html_artifact"),
        "ask_logs": scalar(conn, "SELECT COUNT(*) FROM ask_log")
        if has_table(conn, "ask_log")
        else None,
        "ask_no_result": scalar(conn, "SELECT COUNT(*) FROM ask_log WHERE no_result=1")
        if has_table(conn, "ask_log")
        else None,
        "llm_calls": scalar(conn, "SELECT COUNT(*) FROM llm_call_log"),
        "llm_failed": scalar(conn, "SELECT COUNT(*) FROM llm_call_log WHERE ok=0"),
    }

    warnings = []
    if data["items"]["by_status"].get("failed"):
        warnings.append(f"{data['items']['by_status']['failed']} 条条目状态为 failed")
    ready = data["items"]["by_status"].get("ready", 0)
    if ready and data["index"]["chunk_raw"] == 0:
        warnings.append("有 ready 条目但 chunk 为 0 —— 索引没建起来")
    if ready and data["index"]["vec_rows"] is not None and data["index"]["vec_rows"] == 0:
        warnings.append("有 ready 条目但 chunk_vec 为 0 —— 向量没用上（模型未下载时正常）")
    if data["tasks"]["stale_running"]:
        warnings.append(f"{len(data['tasks']['stale_running'])} 个任务超过 15 分钟未推进")
    if data["tasks"]["recent_failed"]:
        codes = {t["error_code"] for t in data["tasks"]["recent_failed"]}
        warnings.append(f"存在失败任务：{', '.join(sorted(c for c in codes if c)) or '无错误码'}")
    data["warnings"] = warnings
    return data


def print_report(d: dict) -> None:
    it, ix, tk, qz, rv, fo, ar = (
        d["items"],
        d["index"],
        d["tasks"],
        d["quiz"],
        d["review"],
        d["focus"],
        d["artifacts"],
    )
    print(f"数据快照  {d['generated_at']}")
    print(f"\n条目 {it['total']} 条  状态 {it['by_status'] or '空'}  来源 {it['by_source'] or '空'}")
    print(
        f"  分类 {it['categories']} 个 · 手改笔记 {it['note_edited']} · 超长截断 {it['truncated']}"
    )
    print(
        f"\n索引 chunk raw/note = {ix['chunk_raw']}/{ix['chunk_note']} · FTS {ix['fts_rows']} · 向量 {ix['vec_rows']}"
    )
    print(f"\n任务 状态 {tk['by_status'] or '空'}  类型 {tk['by_type'] or '空'}")
    for t in tk["recent_failed"]:
        print(f"  失败 {t['type']} {t['error_code']} {t['error_msg']}")
    print(f"\n题目 {qz['questions']} 道 {qz['by_type'] or '空'}")
    print(
        f"作答 {qz['attempts']} 次：对 {qz['correct']} · 错 {qz['wrong']} · 未判定 {qz['ungraded']}"
    )
    print(
        f"\n复习 队列 {rv['tracked']} · 已到期 {rv['due_now']} · 间隔分布 {rv['intervals'] or '空'} · 忘过 {rv['lapsed']}"
    )
    print(f"\n专注 {fo['sessions']} 轮 {fo['by_status'] or '空'} · 完成 {fo['completed_minutes']} 分钟")
    print(
        f"\n学习页 {ar['html_pages']} 份 · 问答 {ar['ask_logs']} 条（无结果 {ar['ask_no_result']}） · LLM 调用 {ar['llm_calls']} 次（失败 {ar['llm_failed']}）"
    )
    if d["warnings"]:
        print("\n需要留意：")
        for w in d["warnings"]:
            print(f"  ! {w}")
    else:
        print("\n一致性检查：通过（没有发现自相矛盾的状态）")


def make_due(db: Path, hours: float) -> None:
    """把复习到期时间整体前移（默认 3 小时），用来当天验证间隔重复。"""
    conn = sqlite3.connect(str(db), timeout=5)
    try:
        rows = list(conn.execute("SELECT id, due_at FROM review_item"))
        if not rows:
            raise SystemExit("复习队列是空的：先去练习里答错几道题，再来做时间旅行")
        n = 0
        for rid, due_at in rows:
            dt = parse_dt(due_at)
            if not dt:
                continue
            new_due = (dt - timedelta(hours=hours)).isoformat(timespec="seconds")
            conn.execute("UPDATE review_item SET due_at=? WHERE id=?", (new_due, rid))
            n += 1
        conn.commit()
        print(f"已把 {n} 条复习到期时间前移 {hours} 小时。重开 Cairn，去「复习」页看。")
    finally:
        conn.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Cairn 实测对账（默认只读）")
    ap.add_argument("--db", type=Path, default=None, help="data.db 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument(
        "--make-due",
        type=float,
        metavar="小时",
        default=None,
        help="【写】把复习到期时间前移若干小时（先完全退出 Cairn）",
    )
    args = ap.parse_args()

    db = args.db or default_db()
    if not db.exists():
        raise SystemExit(f"找不到数据库：{db}")

    if args.make_due is not None:
        make_due(db, args.make_due)
        return 0

    conn = open_ro(db)
    try:
        try_load_vec(conn)
        data = collect(conn)
    finally:
        conn.close()

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_report(data)
    return 2 if data["warnings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
