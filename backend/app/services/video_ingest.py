"""视频入库流水线（T2.7）：转录 → 查重 → 落库 → 切块。

与 `web_ingest` 同构，差别只在「正文从哪来」：那里是网页抽正文，这里是转录文本。
查重规则完全沿用数据契约 §4：同 URL 撞唯一索引、同内容撞 content_hash。

进度落库按 M2 §6.4：每涨 2% 才写一次 `agent_task`，几百次写库会锁表。
"""
from __future__ import annotations

import logging
import sqlite3

from app.db.conn import get_conn
from app.db.repo import items as repo
from app.services import tasks as task_queue
from app.services import video_sites
from app.services.fetcher import normalize_url
from app.services.transcriber import (
    P_TRANSCRIBE_DONE, BaseTranscriber, Transcript, YtDlpWhisperTranscriber, get_transcriber,
)

log = logging.getLogger(__name__)

STAGE_SAVE = "saving"
P_SAVE_START, P_SAVED = 95, 100
P_TASK_START = 5               # tasks.submit 起手就把 progress 置 5（M1 行为，不能倒退）
STEP = 2                       # 进度每涨 2% 才写一次库


def _pick_transcriber(model: str, language: str) -> BaseTranscriber:
    """带 model/language 时**新建一个实例**，不改单例。

    线程池有 2 个 worker，两个视频任务并发时若都去 setattr 同一个单例，
    后者会把前者的模型改掉（静默用错模型，比报错更难查）。
    注入的假实现不是这个类，原样返回，verify_m2 的注入不受影响。
    """
    shared = get_transcriber()
    if not isinstance(shared, YtDlpWhisperTranscriber) or not (model or language):
        return shared
    return YtDlpWhisperTranscriber(
        model=model or shared.model_size,
        language=language or shared.language,
    )


def run(payload: dict, task_id: str) -> dict:
    """任务入口。签名 (payload, task_id) 由 tasks.submit(pass_task_id=True) 调用。"""
    # 归一化：抖音聚合页（jingxuan?modal_id=…）改写成单条视频地址，
    # 顺带去掉 `?t=`、`spm_id_from=` 这类追踪参数，同一视频不会重复入库
    url = video_sites.canonicalize(normalize_url(str(payload.get("url") or "")))
    force = bool(payload.get("force"))
    model = str(payload.get("model") or "")
    language = str(payload.get("language") or "")

    transcriber = _pick_transcriber(model, language)

    last = [P_TASK_START]
    last_stage = [""]

    def on_progress(progress: int, stage: str) -> None:
        """① 进度不倒退（submit 已置 5，而 transcriber 的 metadata 从 0 起）
        ② 阶段一变就写：否则 metadata（0–5 区间）永远过不了 2% 的门槛，
           前端四阶段里第一个就永远看不到（T2.10 实测发现）。
        """
        value = max(last[0], progress)
        if (stage != last_stage[0] or value - last[0] >= STEP
                or value >= P_TRANSCRIBE_DONE):
            last[0] = value
            last_stage[0] = stage
            task_queue.update_progress(task_id, value, stage)

    transcript = transcriber.transcribe(url, on_progress)   # 失败抛 FetchError(TRANSCRIBE_*)
    task_queue.update_progress(task_id, P_SAVE_START, STAGE_SAVE)

    output = _save(transcript, force)
    task_queue.update_progress(task_id, P_SAVED, STAGE_SAVE)
    log.info(
        "视频入库完成 url=%s item=%s 时长=%.0fs 段数=%s 来源=%s duplicated=%s",
        transcript.url, output["item_id"], transcript.duration,
        transcript.segment_count, transcript.source, output.get("duplicated"),
    )
    return output


def _save(transcript: Transcript, force: bool) -> dict:
    conn = get_conn()
    try:
        with conn:
            existing = repo.find_by_url(conn, transcript.url)
            if existing is not None and not force:
                return {"item_id": existing["id"], "duplicated": False,
                        "existing_item_id": existing["id"], "skipped": True}
            if existing is not None:
                return _replace(conn, existing["id"], transcript)
            return _create(conn, transcript)
    finally:
        conn.close()


def _replace(conn: sqlite3.Connection, item_id: int, t: Transcript) -> dict:
    """force 重转：**只换正文**，与网页 `force` 同一条裁决（2026-11-06）。

    标题、分类、标签、笔记都不动 —— 可能是用户手改过的。
    """
    repo.replace_raw_content(conn, item_id, t.text)
    chunk_count = repo.rebuild_chunks(conn, item_id, t.text, "raw")
    return {"item_id": item_id, "duplicated": False, "replaced": True,
            "existing_item_id": None, "chunk_count": chunk_count,
            "language": t.language, "source": t.source}


def _create(conn: sqlite3.Connection, t: Transcript) -> dict:
    try:
        row, duplicated = repo.create_item(
            conn, title=t.title, raw_content=t.text,
            source_type="video", source_url=t.url,
        )
    except sqlite3.IntegrityError:
        row = repo.find_by_url(conn, t.url)
        if row is None:
            raise
        duplicated = True

    if duplicated:
        chunk_count = repo.count_chunks(conn, row["id"])
    else:
        chunk_count = repo.rebuild_chunks(conn, row["id"], t.text, "raw")
    return {"item_id": row["id"], "duplicated": duplicated,
            "existing_item_id": row["id"] if duplicated else None,
            "chunk_count": chunk_count,
            "duration": round(t.duration), "segment_count": t.segment_count,
            "language": t.language, "source": t.source}
