"""任务队列：ThreadPoolExecutor(max_workers=2)，异常一律落到 agent_task。"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.db.conn import get_conn
from app.db.repo import tasks as repo

log = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """懒加载：lifespan 退出会 shutdown，重新进入时池必须可重建，否则 submit 永久失效。"""
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cairn-task")
        return _executor


def recover_stale_tasks() -> int:
    """启动时把残留 queued/running 标为 failed（T1.6）。"""
    conn = get_conn()
    try:
        with conn:
            count = repo.mark_stale_running_failed(conn)
        if count:
            log.info("已将 %s 条残留任务标记为 failed", count)
        return count
    finally:
        conn.close()


def submit(type: str, fn: Callable[[dict | None], dict | None], input: dict | None = None) -> str:
    """登记任务并立即返回 uuid；fn 抛出的异常捕获后写入 error_code/error_msg。"""
    conn = get_conn()
    try:
        with conn:
            task_id = repo.create_task(conn, type=type, input_json=input)
    finally:
        conn.close()

    def _run() -> None:
        conn = get_conn()
        try:
            with conn:
                repo.update_task(conn, task_id, status="running", progress=5)
        finally:
            conn.close()
        try:
            output = fn(input)
            conn = get_conn()
            try:
                with conn:
                    repo.update_task(conn, task_id, status="done", progress=100,
                                     output_json=output)
            finally:
                conn.close()
        except Exception as exc:
            # 红线 8：任何异步失败都必须落到 agent_task，不许静默死亡
            # 红线 7：只记类型 + 摘要，不打印原始异常栈（httpx 异常可能带请求头）
            # 注意：submit 的参数名 type 会遮蔽内置 type()，必须用 exc.__class__
            exc_name = exc.__class__.__name__
            code = getattr(exc, "code", "TASK_FAILED")
            message = getattr(exc, "message", None) or str(exc)[:500]
            log.error("任务 %s (%s) 失败：%s / %s", task_id, type, exc_name, code)
            conn = get_conn()
            try:
                with conn:
                    repo.update_task(
                        conn, task_id, status="failed",
                        error_code=code,
                        error_msg=f"{exc_name}: {message}"[:500],
                    )
            finally:
                conn.close()

    _get_executor().submit(_run)
    return task_id


def shutdown() -> None:
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
