"""knowledge_item / chunk 的薄封装：语义化方法，内部是可读 SQL。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime

from app.services.chunker import split as split_chunks

ITEM_COLUMNS = (
    "id", "title", "source_type", "source_url", "raw_content", "content_hash",
    "summary", "key_points", "structured_note", "note_edited", "category",
    "tags", "status", "truncated", "created_at", "updated_at",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


def content_hash(raw_content: str) -> str:
    return hashlib.sha256(raw_content.encode("utf-8")).hexdigest()


def row_to_item(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["key_points"] = loads(item.get("key_points")) or []
    item["tags"] = loads(item.get("tags")) or []
    return item


def find_by_hash(conn: sqlite3.Connection, digest: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM knowledge_item WHERE content_hash=? ORDER BY id LIMIT 1", (digest,)
    ).fetchone()


def find_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    """按 source_url 查已有条目（M2 T2.3 判「该 URL 已入库」用）。

    依赖 schema 里的唯一索引 idx_item_url；粘贴来的条目 source_url 为 NULL，不参与匹配。
    """
    if not url:
        return None
    return conn.execute(
        "SELECT * FROM knowledge_item WHERE source_url=? LIMIT 1", (url,)
    ).fetchone()


def create_item(
    conn: sqlite3.Connection,
    *,
    title: str,
    raw_content: str,
    source_type: str = "text",
    source_url: str | None = None,
) -> tuple[sqlite3.Row, bool]:
    """返回 (条目行, 是否撞哈希)。撞哈希时不新建，返回已有条目。"""
    digest = content_hash(raw_content)
    existing = find_by_hash(conn, digest)
    if existing is not None:
        return existing, True
    stamp = now_iso()
    cur = conn.execute(
        """INSERT INTO knowledge_item
           (title, source_type, source_url, raw_content, content_hash, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (title, source_type, source_url, raw_content, digest, stamp, stamp),
    )
    return conn.execute("SELECT * FROM knowledge_item WHERE id=?", (cur.lastrowid,)).fetchone(), False


def rebuild_chunks(
    conn: sqlite3.Connection, item_id: int, text: str, source: str
) -> int:
    """重建某个 source 的 chunk；chunk_fts 只由触发器维护，代码不直接写它。

    raw_content 与 structured_note 共用同一个 chunker，调用方只传 source 标记（M1 §6.10）。
    """
    conn.execute("DELETE FROM chunk WHERE item_id=? AND source=?", (item_id, source))
    pieces = split_chunks(text)
    for position, piece in enumerate(pieces):
        conn.execute(
            "INSERT INTO chunk (item_id, position, content, source) VALUES (?, ?, ?, ?)",
            (item_id, position, piece, source),
        )
    return len(pieces)


def count_chunks(conn: sqlite3.Connection, item_id: int, source: str | None = None) -> int:
    if source is None:
        row = conn.execute("SELECT COUNT(*) FROM chunk WHERE item_id=?", (item_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM chunk WHERE item_id=? AND source=?", (item_id, source)
        ).fetchone()
    return row[0]


def list_chunks(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, position, content, source FROM chunk WHERE item_id=? ORDER BY source, position",
        (item_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM knowledge_item WHERE id=?", (item_id,)).fetchone()


def list_items(
    conn: sqlite3.Connection,
    *,
    source_type: str | None = None,
    category: str | None = None,
    status: str | None = None,
    q: str | None = None,
    tag: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[sqlite3.Row], int]:
    where, args = [], []
    for column, value in (("source_type", source_type), ("category", category), ("status", status)):
        if value:
            where.append(f"{column}=?")
            args.append(value)
    if q:
        where.append("title LIKE ?")
        args.append(f"%{q}%")
    if tag:
        # tags 是 JSON 数组字符串（数据契约 §3）；非法 JSON 时退化空数组，不让整条查询报错
        where.append(
            "EXISTS (SELECT 1 FROM json_each("
            "CASE WHEN json_valid(knowledge_item.tags) THEN knowledge_item.tags ELSE '[]' END)"
            " WHERE json_each.value = ?)"
        )
        args.append(tag)
    clause = " WHERE " + " AND ".join(where) if where else ""
    total = conn.execute("SELECT COUNT(*) FROM knowledge_item" + clause, args).fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM knowledge_item" + clause
        + " ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, page_size, (page - 1) * page_size],
    ).fetchall()
    return rows, total


_UPDATABLE = {"title", "category", "tags", "structured_note", "summary", "key_points", "status"}


def update_item(conn: sqlite3.Connection, item_id: int, fields: dict) -> sqlite3.Row | None:
    """只更新传入字段。带 structured_note 时置 note_edited=1，不触发重新整理。"""
    fields = {k: v for k, v in fields.items() if k in _UPDATABLE and v is not None}
    if not fields:
        return get_item(conn, item_id)
    sets, args = [], []
    for key, value in fields.items():
        sets.append(f"{key}=?")
        args.append(dumps(value) if key in ("tags", "key_points") else value)
    if "structured_note" in fields:
        sets.append("note_edited=1")
    sets.append("updated_at=?")
    args.append(now_iso())
    args.append(item_id)
    conn.execute(f"UPDATE knowledge_item SET {', '.join(sets)} WHERE id=?", args)
    return get_item(conn, item_id)


def delete_item(conn: sqlite3.Connection, item_id: int) -> bool:
    """外键 CASCADE 处理 chunk / question；chunk_fts 由触发器同步。"""
    cur = conn.execute("DELETE FROM knowledge_item WHERE id=?", (item_id,))
    return cur.rowcount > 0


def _scope_clause(category: str | None, tag: str | None) -> tuple[str, list]:
    """左栏「当前筛选」→ WHERE 片段（2026-11-10：计数与批量整理共用一套口径）。

    分类名按展示名比（`COALESCE(NULLIF(category,''),'未分类')`），这样和分类树里的
    数字逐条对得上；标签仍走 json_each，非法 JSON 退化空数组。
    """
    where: list[str] = []
    args: list = []
    if category:
        where.append("COALESCE(NULLIF(category,''),'未分类') = ?")
        args.append(category)
    if tag:
        where.append(
            "EXISTS (SELECT 1 FROM json_each("
            "CASE WHEN json_valid(knowledge_item.tags) THEN knowledge_item.tags ELSE '[]' END)"
            " WHERE json_each.value = ?)"
        )
        args.append(tag)
    return (" WHERE " + " AND ".join(where)) if where else "", args


def category_tree(
    conn: sqlite3.Connection, *, category: str | None = None, tag: str | None = None
) -> dict:
    """分类 → 标签两级计数 + 状态计数，供左侧树使用。

    之前前端拿最近 100 条自己聚合，条目破百后计数就偏低（M1 已知限制）。
    这里直接由 SQL 聚合全库，不再有上限，也省掉前端一次全量拉取。

    `category` / `tag` **只收窄 `counts`**，分类树本身始终是全库的：树是导航，
    不该因为选中了某一支就把别的分支藏掉。选中分类后左栏状态行显示该分类下的数量，
    与列表、与「开始整理 N 条」三处口径一致。
    """
    rows = conn.execute(
        """SELECT COALESCE(NULLIF(category,''),'未分类') AS name, COUNT(*) AS cnt
           FROM knowledge_item GROUP BY name ORDER BY cnt DESC, name ASC"""
    ).fetchall()
    tag_rows = conn.execute(
        """SELECT COALESCE(NULLIF(k.category,''),'未分类') AS cat, j.value AS tag, COUNT(*) AS cnt
           FROM knowledge_item k,
                json_each(CASE WHEN json_valid(k.tags) THEN k.tags ELSE '[]' END) j
           GROUP BY cat, tag ORDER BY cnt DESC, tag ASC"""
    ).fetchall()

    buckets: dict[str, dict] = {
        r["name"]: {"name": r["name"], "count": r["cnt"], "tags": []} for r in rows
    }
    for r in tag_rows:
        bucket = buckets.get(r["cat"])
        if bucket is not None:
            bucket["tags"].append({"name": r["tag"], "count": r["cnt"]})

    clause, scoped = _scope_clause(category, tag)
    counts = conn.execute(
        """SELECT COUNT(*) AS total,
                  COALESCE(SUM(status='pending'), 0)    AS pending,
                  COALESCE(SUM(status='organizing'), 0) AS organizing
           FROM knowledge_item""" + clause,
        scoped,
    ).fetchone()
    return {
        "categories": list(buckets.values()),
        "counts": {
            "total": counts["total"],
            "pending": counts["pending"],
            "organizing": counts["organizing"],
        },
    }


def replace_raw_content(conn: sqlite3.Connection, item_id: int, raw_content: str) -> None:
    """只替换正文并同步 content_hash，状态回 pending。

    这是 M2 网页采集 `force=true` 的唯一写入口（2026-11-06 裁决：force 只覆盖正文）。
    刻意不走 update_item：那里 `_UPDATABLE` 不含 raw_content，且会误动 note_edited。
    标题/分类/标签/笔记一律不碰，理由是同一次裁决。
    """
    conn.execute(
        """UPDATE knowledge_item SET raw_content=?, content_hash=?, status='pending', updated_at=?
           WHERE id=?""",
        (raw_content, content_hash(raw_content), now_iso(), item_id),
    )


def set_status(conn: sqlite3.Connection, item_id: int, status: str) -> None:
    conn.execute(
        "UPDATE knowledge_item SET status=?, updated_at=? WHERE id=?",
        (status, now_iso(), item_id),
    )


def list_ids_by_status(
    conn: sqlite3.Connection,
    status: str,
    limit: int = 50,
    *,
    category: str | None = None,
    tag: str | None = None,
) -> list[int]:
    clause, args = _scope_clause(category, tag)
    if clause:
        clause += " AND status=?"
    else:
        clause = " WHERE status=?"
    rows = conn.execute(
        "SELECT id FROM knowledge_item" + clause + " ORDER BY id LIMIT ?",
        [*args, status, limit],
    ).fetchall()
    return [r["id"] for r in rows]


def save_organize_result(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    category: str,
    tags: list[str],
    summary: str,
    key_points: list[str],
    structured_note: str,
    truncated: bool,
    title: str | None = None,
) -> None:
    """落整理结果并置 status='ready'。

    刻意不走 update_item：那里会因 structured_note 把 note_edited 置 1，
    但整理是机器行为，不能冒充「用户手改过」（数据契约 §3）。

    title 由整理 Agent 生成（≤20 字）；传 None 或空串时保留原标题（COALESCE），
    避免模型没给标题时把已有标题清空。
    """
    conn.execute(
        """UPDATE knowledge_item
           SET title=COALESCE(NULLIF(?, ''), title), category=?, tags=?, summary=?,
               key_points=?, structured_note=?, truncated=?, status='ready', updated_at=?
           WHERE id=?""",
        (title or "", category, dumps(tags), summary, dumps(key_points), structured_note,
         1 if truncated else 0, now_iso(), item_id),
    )
