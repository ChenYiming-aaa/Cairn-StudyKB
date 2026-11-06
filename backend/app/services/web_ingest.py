"""网页入库流水线（T2.3 / T2.4）：抓取 → 查重 → 落库 → 切块。

路由只建任务立刻返回；下载与解析都跑在 `services/tasks` 的线程池里（M2 §1.2）。
进度按数据契约："抓取按阶段固定值 10 / 50 / 90"。

查重的两条线（数据契约 §4）：
- 同 URL → 路由层直接回 existing_item_id，不派任务；这里只兜并发竞争
- 同内容不同 URL → content_hash 撞库，`duplicated: true` + 已有条目 id，**不新建**
"""
from __future__ import annotations

import logging
import sqlite3

from app.db.conn import get_conn
from app.db.repo import items as repo
from app.services import tasks as task_queue
from app.services.fetcher import FetchedPage, get_fetcher, normalize_url

log = logging.getLogger(__name__)

STAGE_FETCH = "fetching"
STAGE_SAVE = "saving"
P_FETCH_START, P_FETCH_DONE, P_SAVED = 10, 50, 90


def run(payload: dict, task_id: str) -> dict:
    """任务入口。签名 (payload, task_id) 由 tasks.submit(pass_task_id=True) 调用。"""
    url = normalize_url(str(payload.get("url") or ""))
    force = bool(payload.get("force"))

    task_queue.update_progress(task_id, P_FETCH_START, STAGE_FETCH)
    page = get_fetcher().fetch(url)            # 失败抛 FetchError，code 落 agent_task
    task_queue.update_progress(task_id, P_FETCH_DONE, STAGE_FETCH)

    output = _save(page, force)
    task_queue.update_progress(task_id, P_SAVED, STAGE_SAVE)
    log.info(
        "网页入库完成 url=%s item=%s duplicated=%s replaced=%s",
        page.url, output["item_id"], output.get("duplicated"), output.get("replaced"),
    )
    return output


def _save(page: FetchedPage, force: bool) -> dict:
    conn = get_conn()
    try:
        with conn:
            existing = repo.find_by_url(conn, page.url)
            if existing is not None and not force:
                # 派任务到真正执行之间被别人抢先入库：不重复建，如实回报
                return {"item_id": existing["id"], "duplicated": False,
                        "existing_item_id": existing["id"], "skipped": True}
            if existing is not None:
                return _replace(conn, existing["id"], page)
            return _create(conn, page)
    finally:
        conn.close()


def _replace(conn: sqlite3.Connection, item_id: int, page: FetchedPage) -> dict:
    """force 重抓：**只换正文**（2026-11-06 裁决）。

    标题、分类、标签、摘要、structured_note、note_edited 一律不动 ——
    那些可能已被用户手改过，重抓不该把人工成果冲掉。
    """
    repo.replace_raw_content(conn, item_id, page.text)
    chunk_count = repo.rebuild_chunks(conn, item_id, page.text, "raw")
    return {"item_id": item_id, "duplicated": False, "replaced": True,
            "existing_item_id": None, "chunk_count": chunk_count}


def _create(conn: sqlite3.Connection, page: FetchedPage) -> dict:
    try:
        row, duplicated = repo.create_item(
            conn, title=page.title, raw_content=page.text,
            source_type="web", source_url=page.url,
        )
    except sqlite3.IntegrityError:
        # 唯一索引 idx_item_url 撞车（同 URL 并发）：退回到"已存在"
        row = repo.find_by_url(conn, page.url)
        if row is None:
            raise
        duplicated = True

    if duplicated:
        chunk_count = repo.count_chunks(conn, row["id"])
    else:
        chunk_count = repo.rebuild_chunks(conn, row["id"], page.text, "raw")
    return {"item_id": row["id"], "duplicated": duplicated,
            "existing_item_id": row["id"] if duplicated else None,
            "chunk_count": chunk_count}
