"""试卷提交（T10.3）：复核后的草稿 → 1 条内容 + N 条题目。

**一次事务、失败整批回滚**。半成品是最糟的结果：内容进来了、题目只写了一半，
用户既不能练，也不知道缺哪几题（需求 §6「草稿不落库」的另一面）。

三条判断：

1. **复用上传时建好的那条内容**，不新建。L1 上传就已经落了一条占位内容（原件挂在它
   身上、页图按它的 `item_id` 建目录），这里只把它定性成 `kind='exam'`。
   另建一条会让原件找不到归属、知识库里出现两条同名内容。
2. **重复提交不导两遍**：先删掉这份内容旧的导入题（**已有作答记录的不删**，
   那会连带删掉用户练过的记录），再写这一批。所以「复核页改完再提交」得到的就是改后的版本。
3. **答案与题型必须自洽**：选择题少一个选项就不能是 `single`（界面画不出选项，
   判分也必然错），降级成 `short` 并在返回值里列出来 —— 宁可明说「这题存成填空了」，
   也不要存一条看起来正常、答不了的选择题。
"""
from __future__ import annotations

import logging
import sqlite3

from app.db.conn import get_conn
from app.db.repo import files as file_repo
from app.db.repo import items as item_repo
from app.db.repo import questions as question_repo
from app.errors import ApiError

log = logging.getLogger(__name__)

TYPES = ("single", "multiple", "boolean", "short")
LETTERS = "ABCDEFGH"
# 导入题的难度一律记这个：试卷不标难度，硬猜一个（basic/apply）会让练习页的难度筛选失真
IMPORTED_DIFFICULTY = "understand"
MAX_TITLE = 20


def _clean_drafts(drafts: list[dict]) -> tuple[list[dict], list[str]]:
    """过滤掉题干为空的草稿，其余按契约字段规整。返回 (可用草稿, 被丢掉的题号)。"""
    kept: list[dict] = []
    dropped: list[str] = []
    for raw in drafts:
        question = str(raw.get("question") or "").strip()
        number = str(raw.get("number") or "").strip()
        if not question:
            dropped.append(number or "?")
            continue
        kept.append({
            "number": number or None,
            "type": str(raw.get("type") or "short"),
            "question": question,
            "options": [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()],
            "answer": raw.get("answer"),
            "explanation": str(raw.get("explanation") or "").strip(),
            "score": raw.get("score"),
            "material": (str(raw.get("material") or "").strip() or None),
            "group": (str(raw.get("group") or "").strip() or None),
        })
    return kept, dropped


def _settle(draft: dict) -> tuple[str, object]:
    """定题型与答案：选项不够就降级，答案不合题型就留空（不猜）。"""
    qtype = draft["type"] if draft["type"] in TYPES else "short"
    options = draft["options"]
    answer = draft["answer"]

    if qtype in ("single", "multiple") and len(options) < 2:
        return "short", (str(answer).strip() if isinstance(answer, str) else answer)
    if qtype == "single":
        text = str(answer or "").strip().upper()
        letters = [ch for ch in text if ch in LETTERS]
        if len(letters) == 1 and len(options) < LETTERS.index(letters[0]) + 1:
            letters = []
        return qtype, (letters[0] if len(letters) == 1 else None)
    if qtype == "multiple":
        if not isinstance(answer, list):
            answer = [ch for ch in str(answer or "").upper() if ch in LETTERS]
        letters = sorted({str(a).strip().upper()[:1] for a in answer} & set(LETTERS[:len(options)]))
        return qtype, (letters or None)
    if qtype == "boolean":
        if isinstance(answer, bool):
            return qtype, answer
        text = str(answer or "").strip()
        return qtype, (True if text in ("true", "True", "对", "正确", "√") else
                       False if text in ("false", "False", "错", "错误", "×") else None)
    text = "" if answer is None else str(answer).strip()
    return "short", (text or None)


def _drop_unused(conn: sqlite3.Connection, item_id: int, used: set[int]) -> tuple[int, list[str]]:
    """这一批没碰到的旧导入题怎么处理。返回 (删掉几条, 因为练过而留着的题号)。

    有作答记录的题**不删**（删题会连带删掉练习记录），但它不能再出现在「按卷练习」里：
    用户是明着删掉这一题的，历史留在「错题本」就够。所以把 `number` 置空 ——
    `list_paper` 只取有题号的题，等于把这一题从卷子里摘出来，历史还在。
    """
    rows = conn.execute(
        """SELECT id, number, EXISTS(SELECT 1 FROM quiz_attempt WHERE question_id=question.id) AS used
           FROM question WHERE item_id=? AND origin='imported'""",
        (item_id,),
    ).fetchall()
    stale = [r for r in rows if int(r["id"]) not in used]
    if not stale:
        return 0, []

    deletable = [int(r["id"]) for r in stale if not r["used"]]
    practiced = [r for r in stale if r["used"]]
    if deletable:
        marks = ",".join("?" * len(deletable))
        conn.execute(f"DELETE FROM question WHERE id IN ({marks})", deletable)
    if practiced:
        ids = [int(r["id"]) for r in practiced]
        marks = ",".join("?" * len(ids))
        conn.execute(f"UPDATE question SET number=NULL WHERE id IN ({marks})", ids)
    return len(deletable), [str(r["number"]) for r in practiced if r["number"]]


def _same_number(conn: sqlite3.Connection, item_id: int, number: str | None) -> int | None:
    """这份卷子里题号相同的旧题 id。

    **身份认题号，不认指纹**：指纹含题干，而复核页最常见的改动就是改题干里的错字。
    按指纹认会「改一个字 = 多出一道题」，卷子里出现两个第 3 题。
    """
    if not number:
        return None
    row = conn.execute(
        """SELECT id FROM question
           WHERE item_id=? AND origin='imported' AND number=?
           ORDER BY id LIMIT 1""",
        (item_id, number),
    ).fetchone()
    return int(row["id"]) if row else None


def commit(file_id: int, drafts: list[dict]) -> dict:
    """提交复核结果。返回 `{item_id, imported, replaced, number_map, downgraded}`。"""
    kept, dropped = _clean_drafts(drafts or [])
    if not kept:
        raise ApiError("EXAM_COMMIT_EMPTY", "至少要保留一道题", status=422)

    conn = get_conn()
    try:
        file = file_repo.get(conn, file_id)
        if file is None:
            raise ApiError("FILE_NOT_FOUND", "这份原件不在库里了，重新上传一次", status=404)
        item_id = int(file["item_id"])
        item = item_repo.get_item(conn, item_id)
        if item is None:
            raise ApiError("FILE_NOT_FOUND", "这条内容不存在了，重新上传一次", status=404)

        number_map: dict[str, int] = {}
        downgraded: list[str] = []
        used: set[int] = set()
        with conn:
            item_repo.set_kind(conn, item_id, "exam")
            for draft in kept:
                qtype, answer = _settle(draft)
                if qtype != draft["type"]:
                    downgraded.append(draft["number"] or draft["question"][:12])
                payload = {
                    "question": draft["question"],
                    "options": draft["options"],
                    "answer": answer,
                    "explanation": draft["explanation"],
                    # 分值/材料/题组进 payload，不改表（需求 §5.5 末段）
                    "score": draft["score"],
                    "material": draft["material"],
                    "group": draft["group"],
                }
                existing = _same_number(conn, item_id, draft["number"])
                if existing is not None:
                    # 同一个题号：原地改。id 不变，练过的记录与复习计划都还认这一行
                    question_repo.update_payload(
                        conn, existing, qtype=qtype, difficulty=IMPORTED_DIFFICULTY,
                        payload=payload, number=draft["number"],
                    )
                    qid = existing
                else:
                    fp = question_repo.fingerprint(item_id, qtype, draft["question"])
                    qid, _ = question_repo.upsert_question(
                        conn, item_id=item_id, qtype=qtype, difficulty=IMPORTED_DIFFICULTY,
                        payload=payload, fp=fp, origin="imported", number=draft["number"])
                used.add(qid)
                if draft["number"]:
                    number_map[str(draft["number"])] = qid

            replaced, kept_practiced = _drop_unused(conn, item_id, used)
    finally:
        conn.close()

    log.info("试卷导入完成：item=%s 写入 %s 题（替换旧题 %s 条，练过留着 %s 条，降级 %s 题，丢弃 %s 条）",
             item_id, len(kept), replaced, len(kept_practiced), len(downgraded), len(dropped))
    return {
        "item_id": item_id,
        "file_id": file_id,
        "title": item["title"],
        "imported": len(kept),
        "replaced": replaced,
        "number_map": number_map,
        "downgraded": downgraded,
        "dropped": dropped,
        # 练过的题删不掉（会连带删掉作答记录），从卷子里摘出来但留在库里。
        # 前端据此说一句「有 2 题练过了，没能删掉」，而不是假装删成功
        "kept_practiced": kept_practiced,
    }
