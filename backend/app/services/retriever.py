"""检索：全文（T3.1）+ 向量（T3.4 用）+ RRF 融合（T3.4）。

分两段是必须的（M3 §6.1）：FTS5 的 trigram 分词器对 **<3 字符**的查询无效，
中文两字词（"笔记"/"复习"/"AI"）必须走 LIKE 兜底，否则用户会以为库里没东西。

bm25() 越小越相关；余弦相似度越大越相关 —— **绝不能把两种分数直接相加**（M3 §6.4），
所以融合一律用排名（RRF，k=60）。
"""
from __future__ import annotations

import logging
import re
import sqlite3

from app.config import get_settings
from app.services import embedder

log = logging.getLogger(__name__)

FTS_MIN_CHARS = 3     # trigram 的下限；写成 <= 3 会把三字词也打进 LIKE（M3 §7）
CANDIDATES = 20       # 两路各取 20
TOP_K = 8             # 融合后取 8
RRF_K = 60
SNIPPET_PAD = 60
MAX_TERMS = 6

# 断句：连中文标点一起切
_SPLIT = re.compile(r"[\s，。！？；：、,.!?;:…—\-“”‘’（）()《》〈〉【】\[\]{}]+")
# 疑问/口语虚词。**替换成分隔符而不是删除**，否则
# 「番茄钟应该绑定什么」会被拼成「番茄钟绑定」这种谁都不含的长串
_NOISE = re.compile(
    r"怎么|怎样|如何|什么|为什么|哪些|哪个|是否|有没有|能否|可以|应该|需要|"
    r"告诉|请问|帮我|一下|简单|具体|区别|吗|呢|吧|啊|呀|的|了|是|我|你|它"
)

_CHUNK_SQL = (
    "SELECT c.id AS chunk_id, c.item_id, c.content, c.source, "
    "       k.title AS item_title "
    "FROM chunk c JOIN knowledge_item k ON k.id = c.item_id "
)


def keyword_terms(text: str, limit: int = MAX_TERMS) -> list[str]:
    """把整句问题切成检索词。中文没有分词器，只能靠虚词切 + 标点切。

    结果保证：去重、长度 ≥2、最多 limit 个。切不出东西时返回 [].
    """
    terms: list[str] = []
    for piece in _SPLIT.split(text or ""):
        for part in _NOISE.sub("|", piece).split("|"):
            part = part.strip()
            if len(part) >= 2 and part not in terms:
                terms.append(part)
    return terms[:limit]


def fts_expression(query: str, operator: str = "AND") -> str:
    """把用户输入变成安全的 FTS5 表达式。

    `"` `*` `:` `(` `-` 在 MATCH 里都是语法字符，直接拼会抛
    `fts5: syntax error`（M3 §6.1）。逐个词包成短语再用 operator 连接：
    特殊字符全部字面化，多词查询也不会被误当成"必须紧邻"。
    """
    tokens = [t for t in query.replace('"', " ").split() if t]
    return f" {operator} ".join(f'"{t}"' for t in tokens)


def _like(conn: sqlite3.Connection, query: str, limit: int) -> list[dict]:
    rows = conn.execute(
        _CHUNK_SQL + "WHERE c.content LIKE ? ORDER BY c.id LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _like_any(conn: sqlite3.Connection, terms: list[str], limit: int) -> list[dict]:
    clause = " OR ".join("c.content LIKE ?" for _ in terms)
    rows = conn.execute(
        _CHUNK_SQL + f"WHERE {clause} ORDER BY c.id LIMIT ?",
        [f"%{t}%" for t in terms] + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def _fts(conn: sqlite3.Connection, expr: str, limit: int) -> list[dict]:
    if not expr:
        return []
    rows = conn.execute(
        "SELECT c.id AS chunk_id, c.item_id, c.content, c.source, k.title AS item_title, "
        "       bm25(chunk_fts) AS score "
        "FROM chunk_fts JOIN chunk c ON c.id = chunk_fts.rowid "
        "JOIN knowledge_item k ON k.id = c.item_id "
        "WHERE chunk_fts MATCH ? ORDER BY score LIMIT ?",
        (expr, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _guarded(conn: sqlite3.Connection, fn, *args) -> list[dict]:
    """FTS 表达式仍被判定非法时回落，不要 500（M3 §7 排障表第一条）。"""
    try:
        return fn(conn, *args)
    except sqlite3.OperationalError as exc:
        log.warning("FTS 查询失败（%s），本次改用 LIKE", type(exc).__name__)
        return []


def search_fts(query: str, limit: int = CANDIDATES) -> tuple[list[dict], str]:
    """返回 (命中列表, match_type)。词长 <3 走 LIKE，否则 FTS。"""
    text = (query or "").strip()
    if not text:
        return [], "none"
    conn = embedder.connect()
    try:
        if len(text) < FTS_MIN_CHARS:
            return _like(conn, text, limit), "like"
        rows = _guarded(conn, _fts, fts_expression(text), limit)
        if rows:
            return rows, "fts"
        return [], "fts"
    finally:
        conn.close()


def search_terms(terms: list[str], limit: int = CANDIDATES) -> tuple[list[dict], str]:
    """按检索词 OR 召回：整句问题用这个，精确短语查不到时也用它兜底。"""
    if not terms:
        return [], "none"
    long_terms = [t for t in terms if len(t) >= FTS_MIN_CHARS]
    conn = embedder.connect()
    try:
        if long_terms:
            rows = _guarded(conn, _fts, fts_expression(" ".join(long_terms), "OR"), limit)
            if rows:
                return rows, "fts"
            return [], "fts"
        # 全都是两字词（如「笔记」「番茄」）→ LIKE
        return _like_any(conn, terms, limit), "like"
    finally:
        conn.close()


def vector_ready() -> bool:
    """向量这一路到底能不能用：开关 + 有推理能力 + 模型文件 + 扩展/表。

    注意判的是**能力**而不是"这次有没有向量命中"——空库时也可能一个都不命中，
    但降级提示不该因此误报。`embedder.usable()` 是 M8 加的：装了组件、
    或本进程能 import 到模型库，二者都没有就算没能力（否则下一步会抛异常而不是降级）。
    """
    return (
        get_settings().vector_enabled
        and embedder.usable()
        and embedder.model_ready()
        and embedder.vec_available()
    )


def vector_ids(query: str, limit: int = CANDIDATES,
               max_distance: float | None = None) -> list[int]:
    """向量召回的 chunk_id，按相似度降序。任何不可用都返回 []（不抛）。

    `max_distance` 给了就把距离超过它的候选丢掉。normalize_embeddings=True 后
    vec0 的 L2 距离 = 2 - 2·cos，所以「库里根本没有相关内容」时距离会明显偏大，
    没有这道闸门时任何问题都会硬凑出 20 个候选，契约要求的
    「检索为空不调模型」就只在空库才成立（M3 T3.5）。
    """
    if not vector_ready():
        return []
    vector = embedder.encode_query(query)
    if not vector:
        return []
    conn = embedder.connect()
    try:
        try:
            sql = ("SELECT chunk_id, distance FROM chunk_vec "
                   "WHERE embedding MATCH ? AND k = ? ORDER BY distance")
            rows = conn.execute(sql, (embedder.blob(vector), limit)).fetchall()
            if max_distance is None:
                return [int(r[0]) for r in rows]
            return [int(r[0]) for r in rows if float(r[1]) <= max_distance]
        except sqlite3.Error as exc:
            # vec0 用不了就退化成内存矩阵乘法（M3 §6.3），仍失败就放弃向量这一路
            log.warning("vec0 查询失败（%s），改用 numpy 暴力检索", type(exc).__name__)
            return _vector_numpy(conn, vector, limit, max_distance)
    finally:
        conn.close()


def _vector_numpy(conn: sqlite3.Connection, vector: list[float], limit: int,
                  max_distance: float | None = None) -> list[int]:
    try:
        import numpy as np

        rows = conn.execute("SELECT chunk_id, embedding FROM chunk_vec").fetchall()
        if not rows:
            return []
        ids = np.asarray([r[0] for r in rows], dtype=np.int64)
        # embedding 是 sqlite-vec 的 float32 blob，直接按 dtype 解包
        mat = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        sims = mat @ np.asarray(vector, dtype=np.float32)
        order = np.argsort(-sims)
        if max_distance is not None:
            # 距离换算回余弦：d = 2 - 2·cos，两条路径的阈值必须是同一个语义
            floor = 1.0 - max_distance / 2.0
            order = [i for i in order if float(sims[i]) >= floor]
        return [int(ids[i]) for i in order[:limit]]
    except Exception as exc:
        log.warning("numpy 向量检索失败（%s），本次只用全文结果", type(exc).__name__)
        return []


def rrf(ranked_lists: list[list[int]], k: int = RRF_K, top: int = TOP_K) -> list[int]:
    """倒数排名融合。只吃排名不吃分数，所以不需要把 bm25 与余弦拉到同一量纲。"""
    score: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            score[chunk_id] = score.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(score, key=lambda cid: (-score[cid], cid))[:top]


def snippet(content: str, query: str, pad: int = SNIPPET_PAD) -> str:
    """命中位置前后各 pad 字；查不到位置（例如只靠向量命中）就取开头。"""
    text = content or ""
    pos = text.find(query) if query else -1
    if pos < 0:
        for token in (query or "").split():
            pos = text.find(token)
            if pos >= 0:
                break
    if pos < 0:
        head = text[: pad * 2].strip()
        return head + ("…" if len(text) > pad * 2 else "")
    start = max(0, pos - pad)
    end = min(len(text), pos + len(query) + pad)
    body = text[start:end].strip()
    return ("…" if start > 0 else "") + body + ("…" if end < len(text) else "")


def _detail(conn: sqlite3.Connection, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(_CHUNK_SQL + f"WHERE c.id IN ({marks})", ids).fetchall()
    return {r["chunk_id"]: dict(r) for r in rows}


def hybrid(query: str, top: int = TOP_K) -> dict:
    """全文 + 向量两路召回后 RRF 融合。

    全文这一路是两段式：先按**精确短语**（多词 AND）查，查不到再把整句拆成
    检索词用 OR 查。理由：用户直接问一句「ESLint 怎么配置成默认格式化程序」
    时，AND 短语几乎必然零命中，但拆出「ESLint / 配置成 / 默认格式化程序」就能找到。

    返回 {"items": [...], "match_type": "fts|like|none", "fallback": "..."}。
    """
    text = (query or "").strip()
    if not text:
        return {"items": [], "match_type": "none", "fallback": "none"}

    ready = vector_ready()
    fallback = _fallback(text, ready)

    fts_rows, match_type = search_fts(text, CANDIDATES)
    anchor = text
    if not fts_rows:
        terms = keyword_terms(text)
        if len(terms) >= 2:
            fts_rows, match_type = search_terms(terms, CANDIDATES)
            if fts_rows:
                # 片段要围着真正命中的词截，不然"命中位置前后各 60 字"会跑偏
                anchor = max(terms, key=len)

    tag = {row["chunk_id"]: match_type for row in fts_rows}
    # 全文一路零命中时才给向量设门槛：此时没有字面证据，全靠相似度兜底，
    # 距离太远就说明库里真没有。全文有命中则不加闸（「番茄钟」这类库内问题
    # 向量距离 1.169，卡了会误判成没有）。
    limit_distance = None if fts_rows else get_settings().vector_min_distance
    vec_ids = vector_ids(text, CANDIDATES, max_distance=limit_distance) if ready else []
    # `ready` 为假时 vec_ids 必空，但那是"根本没跑向量"而不是"跑了没够着门槛"。
    # 不加这个前提，没装向量组件的用户会拿到 `vector_below_threshold`，
    # 前端对它没有文案 → 一句提示都不显示，用户不知道自己在用纯文字检索（M8 S-1）
    if ready and not vec_ids and limit_distance is not None:
        fallback = "vector_below_threshold"
    for chunk_id in vec_ids:
        tag.setdefault(chunk_id, "vector")

    fused = rrf([[row["chunk_id"] for row in fts_rows], vec_ids], top=top)
    if not fused:
        return {"items": [], "match_type": match_type, "fallback": fallback}

    conn = embedder.connect()
    try:
        found = _detail(conn, fused)
    finally:
        conn.close()

    items = []
    for chunk_id in fused:
        row = found.get(chunk_id)
        if row is None:            # 融合后条目可能刚被删掉
            continue
        items.append({
            "chunk_id": chunk_id,
            "item_id": row["item_id"],
            "item_title": row["item_title"],
            "content": row["content"],
            "source": row["source"],
            "match_type": tag.get(chunk_id, "vector"),
            "snippet": snippet(row["content"], anchor),
        })
    return {"items": items, "match_type": match_type, "fallback": fallback}


def _fallback(text: str, ready: bool) -> str:
    """没跑向量的原因，要能一眼分辨"用户关了"和"没装组件"（M8 S-1）。

    - `vector_disabled`：开关关了，或开关开着但还没模型 —— M3 起就是这个语义
    - `vector_component_missing`：M8 新增，向量组件没装（原先把这种情况也报成
      `vector_disabled`，界面提示不了"去装"）
    """
    if len(text) < FTS_MIN_CHARS:
        return "like_short_query"
    if ready:
        return "none"
    if not get_settings().vector_enabled or embedder.usable():
        return "vector_disabled"
    return "vector_component_missing"
