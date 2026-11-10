"""Embedding 服务（T3.2）+ 向量索引（T3.3）。

设计要点（M3 §6.2 / §6.3、数据契约 §2）：
- 模型懒加载且常驻：首次约 3 秒 + 100MB 下载，绝不能每次请求重建
- **文档向量不加前缀，查询向量加前缀**，这是 bge 的用法约定（M3 §1 约束 3）
- `normalize_embeddings=True` 后余弦相似退化为点积，numpy 降级时直接 `mat @ q`
- 向量写 `chunk_vec`（vec0，可选表）。扩展不可用时**整条链路降级为纯 FTS**，
  不报错、不阻塞问答（DoD：关掉向量问答仍正常返回）
- 入库补向量走 `agent_task` type=`index_embed`，不卡采集流程（M3 §6.2）
- **M8 起推理可能不在本进程**：`components.resolve("embed")` 决定走子进程还是本进程，
  两者都不可用才算降级（见 `components.py` 顶部的三态说明）
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from typing import Iterable

from app.config import get_settings
from app.db.conn import get_conn, table_exists
from app.services import components

log = logging.getLogger(__name__)

DIM = 512
BATCH_SIZE = 32
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_model = None
_model_lock = threading.Lock()

# 扩展可用性只探测一次：sqlite-vec 装上或卸掉都要重启进程才算数，
# 每请求重复 load 既慢又会把告警日志刷满。
_vec_probe: bool | None = None
_vec_lock = threading.Lock()


# ── 可用性 ──────────────────────────────────────────────
def usable() -> bool:
    """这一路能不能算出向量：组件进程 或 本进程内模型，至少有一个在。

    与 `vec_available()`（扩展/表能不能用）是两件事，判断顺序必须是**先有嘴再吃饭**：
    没有推理能力时 `vector_ready()` 要返回 False，否则检索会先报"能"、再在
    `encode_query` 炸掉，问答页就成了 500（M8 §2.2 要的正是"降级而不是崩"）。
    """
    return components.resolve("embed") is not None


# ── 模型 ────────────────────────────────────────────────
def get_model():
    """懒加载常驻模型。首次调用会从 HF_ENDPOINT（镜像）下载。"""
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            cfg = get_settings()
            cache = cfg.models_dir / "embedding"
            cache.mkdir(parents=True, exist_ok=True)
            log.info("加载 embedding 模型 %s（缓存目录 %s）", cfg.embed_model, cache)
            _model = SentenceTransformer(
                cfg.embed_model, cache_folder=str(cache), device="cpu"
            )
        return _model


def _encode_remote(texts: list[str], kind: str) -> list[list[float]]:
    """交给组件进程。前缀由组件加（`kind=query` 时），主程序不掺和。

    `model` / `cache_dir` 必须显式传：组件是独立进程，读不到 `Settings`，
    而且它得跟主程序用**同一个**模型缓存目录 —— 否则"装组件前已经下过模型"
    的用户会被要求再下一次 90 MB（`model_ready()` 也看这个目录，两处不一致时
    检索页会一直说"模型没下"）。
    """
    cfg = get_settings()
    reply = components.call("embed", "encode", {
        "kind": kind,
        "texts": texts,
        "model": cfg.embed_model,
        "cache_dir": str(cfg.models_dir / "embedding"),
    }, timeout=120.0)
    return reply.get("vectors") or []


def encode_docs(texts: Iterable[str]) -> list[list[float]]:
    batch = [t for t in texts if t and t.strip()]
    if not batch:
        return []
    mode = components.resolve("embed")
    if mode == "component":
        return _encode_remote(batch, "doc")
    if mode is None:
        raise components.ComponentError("COMPONENT_MISSING", "向量检索组件还没装")
    vectors = get_model().encode(
        batch, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=False
    )
    return [v.tolist() for v in vectors]


def encode_query(query: str) -> list[float]:
    """查询必须加前缀；文档不加。加反了召回会明显变差（M3 §1 约束 3）。"""
    if components.resolve("embed") == "component":
        vectors = _encode_remote([query], "query")     # 前缀在组件里加
        return vectors[0] if vectors else []
    vectors = encode_docs([QUERY_PREFIX + query])
    return vectors[0] if vectors else []


# ── 扩展与表 ────────────────────────────────────────────
def load_extension(conn: sqlite3.Connection) -> bool:
    """给**当前连接**装载 sqlite-vec；失败返回 False，调用方自行降级。"""
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        conn.execute("SELECT vec_version()").fetchone()
        return True
    except Exception as exc:  # 未安装 / 平台不允许 / 模块名不符
        log.info("sqlite-vec 不可用（%s），向量检索降级", type(exc).__name__)
        return False


def vec_available() -> bool:
    """进程级探测一次。VECTOR_ENABLED=0 时直接判 False，不加载扩展。"""
    global _vec_probe
    if not get_settings().vector_enabled:
        return False
    with _vec_lock:
        if _vec_probe is None:
            conn = get_conn()
            try:
                _vec_probe = load_extension(conn) and table_exists(conn, "chunk_vec")
            finally:
                conn.close()
            if not _vec_probe:
                log.warning("向量加速不可用，已降级为纯全文检索（功能不受影响）")
        return _vec_probe


def connect() -> sqlite3.Connection:
    """取一个已按需装载扩展的连接。调用方负责 close。"""
    conn = get_conn()
    if vec_available():
        load_extension(conn)
    return conn


# ── 向量读写 ────────────────────────────────────────────
def blob(vector: list[float]):
    import numpy as np
    import sqlite_vec

    return sqlite_vec.serialize_float32(np.asarray(vector, dtype=np.float32))


def model_ready() -> bool:
    """模型文件是否已在本地。

    请求路径**绝不允许触发下载**（首搜会卡几十秒甚至失败）。下载只发生在
    `index_embed` 任务与回填脚本里 —— 它们是后台执行，慢一点没关系。
    """
    cache = get_settings().models_dir / "embedding"
    if not cache.exists():
        return False
    return any(cache.rglob("*.safetensors")) or any(cache.rglob("*.bin"))


def _table_ready(conn: sqlite3.Connection) -> bool:
    return vec_available() and table_exists(conn, "chunk_vec")


def upsert(conn: sqlite3.Connection, rows: list[tuple[int, list[float]]]) -> int:
    if not rows or not _table_ready(conn):
        return 0
    for chunk_id, vector in rows:
        conn.execute("DELETE FROM chunk_vec WHERE chunk_id=?", (chunk_id,))
        conn.execute(
            "INSERT INTO chunk_vec(chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, blob(vector)),
        )
    return len(rows)


def delete(conn: sqlite3.Connection, chunk_ids: list[int]) -> None:
    if not chunk_ids or not _table_ready(conn):
        return
    for chunk_id in chunk_ids:
        conn.execute("DELETE FROM chunk_vec WHERE chunk_id=?", (chunk_id,))


def prune_orphans(conn: sqlite3.Connection) -> int:
    """删掉已经没有对应 chunk 的向量。

    chunk 重建（改笔记 / 重新整理）会给新行新 id，旧向量不会指向错误文本
    （AUTOINCREMENT 不复用 id），但会一直堆在表里。这里顺手清掉。
    """
    if not _table_ready(conn):
        return 0
    rows = conn.execute(
        "SELECT v.chunk_id FROM chunk_vec v "
        "LEFT JOIN chunk c ON c.id = v.chunk_id WHERE c.id IS NULL"
    ).fetchall()
    ids = [r[0] for r in rows]
    delete(conn, ids)
    if ids:
        log.info("清理 %s 条失效向量", len(ids))
    return len(ids)


def count_vectors(conn: sqlite3.Connection) -> int:
    if not _table_ready(conn):
        return 0
    return conn.execute("SELECT COUNT(*) FROM chunk_vec").fetchone()[0]


# ── 补索引 ──────────────────────────────────────────────
def index_chunks(conn: sqlite3.Connection, chunk_ids: list[int]) -> int:
    if not chunk_ids or not _table_ready(conn) or not usable():
        return 0
    marks = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"SELECT id, content FROM chunk WHERE id IN ({marks})", chunk_ids
    ).fetchall()
    if not rows:
        return 0
    vectors = encode_docs([r["content"] for r in rows])
    return upsert(conn, [(r["id"], v) for r, v in zip(rows, vectors)])


def _missing_chunk_ids(conn: sqlite3.Connection, limit: int, item_id: int | None) -> list[int]:
    clause = "AND c.item_id=?" if item_id is not None else ""
    sql = (
        "SELECT c.id FROM chunk c LEFT JOIN chunk_vec v ON v.chunk_id = c.id "
        f"WHERE v.chunk_id IS NULL {clause} ORDER BY c.id LIMIT ?"
    )
    args = [item_id, limit] if item_id is not None else [limit]
    return [r[0] for r in conn.execute(sql, args).fetchall()]


def index_item(item_id: int) -> int:
    """把某个条目缺向量的 chunk 补齐，返回写入条数。"""
    conn = connect()
    try:
        if not _table_ready(conn):
            return 0
        ids = _missing_chunk_ids(conn, 10_000, item_id)
        with conn:
            return index_chunks(conn, ids)
    finally:
        conn.close()


def run(task_input: dict | None = None) -> dict:
    """agent_task type=`index_embed` 的执行入口。

    带 item_id 补该条目；不带则全库补（首次升级 / 回填脚本用）。
    """
    item_id = (task_input or {}).get("item_id")
    item_id = int(item_id) if item_id is not None else None
    conn = connect()
    try:
        if not _table_ready(conn):
            # 不是失败：降级本来就是允许的（M3 §6.3）。但要让任务记录说清原因
            return {"indexed": 0, "skipped": "vector_unavailable"}
        if not usable():
            # 表在、扩展在，但算不出向量（没装向量组件）。原因要和上一条分开记，
            # 否则排障时分不清"向量表坏了"和"组件没装"
            return {"indexed": 0, "skipped": "component_missing"}
        ids = _missing_chunk_ids(conn, 20_000, item_id)
        if not ids:
            return {"indexed": 0, "item_id": item_id}
        with conn:
            done = index_chunks(conn, ids)
            prune_orphans(conn)
        log.info("补向量完成：item=%s，写入 %s 条", item_id or "全库", done)
        return {"indexed": done, "item_id": item_id}
    finally:
        conn.close()


def schedule(item_id: int | None = None) -> str | None:
    """派一个 index_embed 任务。向量不可用 / 派发失败都不影响主流程。"""
    if not get_settings().vector_enabled or not usable():
        # 没装向量组件时不必派：任务只会立刻 skip，白占任务中心的版面
        return None
    try:
        from app.services import dispatch  # 延迟 import：dispatch 会反向依赖采集模块

        return dispatch.submit("index_embed", {"item_id": item_id} if item_id else {})
    except Exception as exc:
        log.warning("补向量任务派发失败（%s），不影响主流程", type(exc).__name__)
        return None


def reset_for_tests() -> None:
    """只给脚本用：忘掉已加载的模型与探测结果。"""
    global _model, _vec_probe
    with _model_lock:
        _model = None
    with _vec_lock:
        _vec_probe = None
