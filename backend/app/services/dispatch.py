"""任务类型 → 执行函数的分发表。

放独立模块是为了打断循环依赖：`web_ingest` / `video_ingest` 都要 import `tasks`，
所以注册表不能放 `tasks.py`；路由只依赖本模块，重试时也不必知道每种类型的细节。
"""
from __future__ import annotations

import logging
import os

from app.db.conn import get_conn
from app.db.repo import items as item_repo
from app.db.repo import tasks as repo
from app.db.repo.items import loads
from app.services import tasks as task_queue
from app.services import component_install, embedder, ingest_file, video_ingest, web_ingest
from app.services import llm_route
from app.services.agents import organizer

log = logging.getLogger(__name__)

TASK_ORGANIZE = "organize"
TASK_FETCH_URL = "fetch_url"
TASK_TRANSCRIBE_VIDEO = "transcribe_video"
TASK_INDEX_EMBED = "index_embed"
TASK_COMPONENT_INSTALL = component_install.TASK_TYPE
TASK_OCR_PAGES = ingest_file.TASK_TYPE
TASK_EXTRACT_TEXT = ingest_file.TASK_EXTRACT

# 这些任务跑完就把内容直接排上整理（2026-11-17）。范围是**单个来源**：
#   单条链接 / 单个文件（识别或直读）—— 用户「丢进来一条」的预期就是它自己能整理好。
# 刻意不含：
#   · `transcribe_video` —— 转录本身已经跑了几分钟，再自动接一次模型调用，
#     用户看不到中间态，只会觉得「卡住了」；
#   · 文件夹批量导入（走 `/api/import/run`，不经过这里的 submit）—— 一次几十个文件
#     就是几十次模型调用，费用与并发都不可控，那批仍由「开始整理 N 条」统一触发。
AUTO_ORGANIZE_AFTER = {TASK_FETCH_URL, TASK_OCR_PAGES, TASK_EXTRACT_TEXT}

# type → (执行函数, 是否需要 task_id)
RUNNERS = {
    # 整理：失败率最高的一类（超时 / 额度 / 模型回了不是 JSON），没有它任务中心的
    # 「重试」对最常见的失败反而是 400（2026-11-15 补）
    TASK_ORGANIZE: (organizer.run, False),
    TASK_FETCH_URL: (web_ingest.run, True),
    TASK_TRANSCRIBE_VIDEO: (video_ingest.run, True),
    # 补向量（M3 §6.2）：不需要进度回调，run(task_input) 就够
    TASK_INDEX_EMBED: (embedder.run, False),
    # 装组件（M8 T8.3）：登记在这里只为让任务中心能「重试」失败的下载；
    # 正常入口是 POST /api/components/{id}/install（走 component_install.start）
    TASK_COMPONENT_INSTALL: (component_install.run, True),
    # 逐页识别（T9.6）：要按页上报进度，所以必须拿到自己的 task_id
    TASK_OCR_PAGES: (ingest_file.run, True),
    # 整份抽取（T9.7）：docx / pptx / xlsx / txt 直读，不碰识别组件。
    # 与识别分开登记，是为了任务中心能如实显示"读取"而不是"识别"，
    # 也让组件没装时这批任务照样能重试
    TASK_EXTRACT_TEXT: (ingest_file.run_extract, True),
}


def supported_types() -> list[str]:
    return sorted(RUNNERS)


class NotRetryable(Exception):
    """任务状态不允许重试（只有 failed 可以）。"""

    def __init__(self, status: str):
        self.status = status
        super().__init__(f"任务状态为 {status}，只有 failed 可以重试")


def submit(task_type: str, payload: dict | None = None, *,
           auto_organize: bool = True) -> str:
    """按类型派任务，返回 task_id。类型未登记时抛 KeyError，由调用方转 400。

    `auto_organize=False` 用来关掉「跑完自动排整理」：文件夹批量导入走这条路，
    一次几十个文件就是几十次模型调用，那批仍由「开始整理 N 条」统一触发。
    """
    fn, pass_task_id = RUNNERS[task_type]
    attach = auto_organize and task_type in AUTO_ORGANIZE_AFTER
    return task_queue.submit(
        task_type, fn, payload or {}, pass_task_id=pass_task_id,
        on_done=_after_ingest if attach else None,
    )


def _auto_organize_on() -> bool:
    """自动整理总开关（默认开）。

    `CAIRN_NO_AUTO_ORGANIZE=1` 只给**验收脚本**用：`verify_m1` 验的是「手工整理」
    这条老流程（创建 → 手动点整理 → organize-pending 批量），自动整理一开，
    那条流程的中间态就不存在了。它不是用户可见的配置项，所以读环境变量而不是进 Settings。
    读在调用时而不是导入时，脚本才能在同一进程里两头都验。
    """
    value = os.environ.get("CAIRN_NO_AUTO_ORGANIZE", "").strip().lower()
    return value not in ("1", "true", "yes", "on")


def organize_if_pending(item_id: int) -> str | None:
    """这条内容还没整理过就排一条整理任务，返回 task_id；不该排就返回 None。

    「该不该排」的判据都在这里，调用方不用重复判：

    - 开关关了（验收脚本）→ 不排。
    - 没配模型 Key → 不排。否则每次采集都会在任务中心堆一条注定失败的 `organize`
      （`require_key` 会在任务里抛 400），用户看到一片红却什么都没做错。
    - 已经不是 `pending` → 不排。正在整理、或整理完的都不该再排一遍。
    - `kind='exam'` → 不排。试卷的「卷面概览」要等题目导进来才有意义，
      在读字完成这一刻排整理，写出来的概览题数是 0。
    - **笔记被手改过（`note_edited`）→ 不排**。这是自动整理唯一会造成损失的情况：
      重新抓取会重置状态、排上整理，而整理会直接覆盖手改过的笔记——
      界面上的「重新整理」为这件事弹一次确认，自动整理没有那个确认框，
      所以它必须自己让开，把决定权留给人。
    - 状态用**条件 UPDATE** 抢占（`WHERE status='pending'`）：抓取与识别可能同时
      对同一条收口，两个任务都看到 `pending` 时只有一个能抢到，不会排两条。

    抢占成功后由调用方拿到 task_id；这一步失败（比如并发）返回 None，不报错。
    """
    if not _auto_organize_on() or not llm_route.has_key("organizer"):
        return None
    conn = get_conn()
    try:
        row = item_repo.get_item(conn, item_id)
        if row is None:
            return None
        if row["status"] != "pending":
            return None
        if (row["kind"] or "material") == "exam":
            return None
        if row["note_edited"]:
            return None
        with conn:
            cur = conn.execute(
                "UPDATE knowledge_item SET status='organizing', updated_at=?"
                " WHERE id=? AND status='pending'",
                (item_repo.now_iso(), item_id),
            )
        if cur.rowcount != 1:
            return None
    finally:
        conn.close()
    return submit(TASK_ORGANIZE, {"item_id": item_id})


def _after_ingest(output: dict | None) -> None:
    """采集类任务成功后的串接：内容齐了就直接排整理（见 `AUTO_ORGANIZE_AFTER`）。

    只认 `status == 'done'`（缺这个键的 `fetch_url` 视为完成）：
    `partial` / `failed` 的正文还是占位或半份，排上去只会被 409 挡回来，
    或者更糟——拿半份内容写出一份看起来很完整的笔记。
    """
    if not isinstance(output, dict):
        return
    status = output.get("status")
    if status is not None and status != "done":
        return
    item_id = output.get("item_id")
    if not item_id:
        return
    task_id = organize_if_pending(int(item_id))
    if task_id:
        log.info("内容 %s 采集完成，已自动排队整理（%s）", item_id, task_id)


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
