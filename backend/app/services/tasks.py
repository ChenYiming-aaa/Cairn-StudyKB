"""任务队列：ThreadPoolExecutor(max_workers=2)，异常一律落到 agent_task。"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from app.db.conn import get_conn
from app.db.repo import tasks as repo
from app.services import embedder

log = logging.getLogger(__name__)

# 跑完这些任务后要补向量（M3 §6.2「入库时异步补向量，不卡采集流程」）。
# 放在这里而不是各个 run() 里：入队点有 6 处，改一处即可，且**一定在提交之后**，
# 不会读到未提交的 chunk。
EMBED_AFTER = {"organize", "fetch_url", "transcribe_video"}

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


def submit(
    type: str,
    fn: Callable[..., dict | None],
    input: dict | None = None,
    *,
    pass_task_id: bool = False,
) -> str:
    """登记任务并立即返回 uuid；fn 抛出的异常捕获后写入 error_code/error_msg。

    `pass_task_id=True` 时以 `fn(input, task_id)` 调用 —— 需要回报进度的长任务
    （抓取 10/50/90、转录按音频时长）必须拿到自己的 id，见 M2 §6.4。
    """
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
            output = fn(input, task_id) if pass_task_id else fn(input)
            conn = get_conn()
            try:
                with conn:
                    repo.update_task(conn, task_id, status="done", progress=100,
                                     output_json=output)
            finally:
                conn.close()
            _schedule_embed(type, output)
        except Exception as exc:
            # 红线 8：任何异步失败都必须落到 agent_task，不许静默死亡
            # 红线 7：只记类型 + 摘要，不打印原始异常栈（httpx 异常可能带请求头）
            # 注意：submit 的参数名 type 会遮蔽内置 type()，必须用 exc.__class__
            exc_name = exc.__class__.__name__
            code = getattr(exc, "code", "TASK_FAILED")
            # 只有业务异常（带 message）才能把话给人看；未预料的异常原文是给开发者看的，
            # 落库会让任务中心出现 "name 'X' is not defined" 这类内部细节（T2.9 实测发现）。
            # 摘要仍进日志，排查不受影响。
            message = getattr(exc, "message", None) or "任务失败：内部错误，请重试或查看后端日志"
            log.error("任务 %s (%s) 失败：%s / %s / %s",
                      task_id, type, exc_name, code, str(exc)[:200])
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


def _schedule_embed(task_type: str, output: dict | None) -> None:
    """任务成功落库后补向量。任何异常都不许影响任务本身的成功状态。"""
    if task_type not in EMBED_AFTER or not isinstance(output, dict):
        return
    item_id = output.get("item_id") or output.get("existing_item_id")
    if not item_id:
        return
    try:
        embedder.schedule(int(item_id))
    except Exception as exc:
        log.warning("补向量任务派发失败（%s），条目 %s", type(exc).__name__, item_id)


def update_progress(task_id: str, progress: int, stage: str | None = None) -> None:
    """长任务回调用的轻量进度更新（M2 §6.4）。

    转录回调每涨 2% 才调一次，不要每个 segment 都写库（几百次写库会锁表）。
    进度是尽力而为：写失败只记 warning，不中断正在跑的任务——
    真正的失败会由 saving 阶段落 agent_task，不会因此静默。
    """
    conn = get_conn()
    try:
        with conn:
            repo.update_progress(
                conn, task_id,
                progress=max(0, min(100, int(progress))), stage=stage,
            )
    except Exception as exc:
        log.warning("任务 %s 进度更新失败（%s）", task_id, type(exc).__name__)
    finally:
        conn.close()


def shutdown() -> None:
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
