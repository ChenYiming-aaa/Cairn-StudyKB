"""任务类型 → 执行函数的分发表。

放独立模块是为了打断循环依赖：`web_ingest` / `video_ingest` 都要 import `tasks`，
所以注册表不能放 `tasks.py`；路由只依赖本模块，重试时也不必知道每种类型的细节。
"""
from __future__ import annotations

import logging

from app.db.conn import get_conn
from app.db.repo import tasks as repo
from app.db.repo.items import loads
from app.services import tasks as task_queue
from app.services import component_install, embedder, ingest_file, video_ingest, web_ingest

log = logging.getLogger(__name__)

TASK_FETCH_URL = "fetch_url"
TASK_TRANSCRIBE_VIDEO = "transcribe_video"
TASK_INDEX_EMBED = "index_embed"
TASK_COMPONENT_INSTALL = component_install.TASK_TYPE
TASK_OCR_PAGES = ingest_file.TASK_TYPE

# type → (执行函数, 是否需要 task_id)
RUNNERS = {
    TASK_FETCH_URL: (web_ingest.run, True),
    TASK_TRANSCRIBE_VIDEO: (video_ingest.run, True),
    # 补向量（M3 §6.2）：不需要进度回调，run(task_input) 就够
    TASK_INDEX_EMBED: (embedder.run, False),
    # 装组件（M8 T8.3）：登记在这里只为让任务中心能「重试」失败的下载；
    # 正常入口是 POST /api/components/{id}/install（走 component_install.start）
    TASK_COMPONENT_INSTALL: (component_install.run, True),
    # 逐页识别（T9.6）：要按页上报进度，所以必须拿到自己的 task_id
    TASK_OCR_PAGES: (ingest_file.run, True),
}


def supported_types() -> list[str]:
    return sorted(RUNNERS)


class NotRetryable(Exception):
    """任务状态不允许重试（只有 failed 可以）。"""

    def __init__(self, status: str):
        self.status = status
        super().__init__(f"任务状态为 {status}，只有 failed 可以重试")


def submit(task_type: str, payload: dict | None = None) -> str:
    """按类型派任务，返回 task_id。类型未登记时抛 KeyError，由调用方转 400。"""
    fn, pass_task_id = RUNNERS[task_type]
    return task_queue.submit(task_type, fn, payload or {}, pass_task_id=pass_task_id)


def retry(task_id: str) -> str | None:
    """用原任务的 type + input 重新派一次，返回新 task_id。

    只允许重试 failed：done 的再跑一遍没有语义，running/queued 则可能并发出双份。
    返回 None 表示任务不存在；不支持的状态由调用方判（这里是纯查询）。
    """
    conn = get_conn()
    try:
        row = repo.get_task(conn, task_id)
        if row is None:
            return None
        if row["status"] != "failed":
            raise NotRetryable(row["status"])
        if row["type"] not in RUNNERS:
            raise KeyError(row["type"])
        payload = loads(row["input_json"]) if row["input_json"] else {}
    finally:
        conn.close()

    new_id = submit(row["type"], payload if isinstance(payload, dict) else {})
    log.info("任务 %s 重试 → %s（type=%s）", task_id, new_id, row["type"])
    return new_id
