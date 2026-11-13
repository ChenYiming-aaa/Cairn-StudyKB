"""question / quiz_attempt 的薄封装：语义化方法，内部是可读 SQL。

T4.3 去重的全部逻辑都在这里：
- `fingerprint()` 是**唯一**的归一化入口，出题与入库共用（M4 §6.3、排障表「归一化只写一处」）
- 入库用 `INSERT ... ON CONFLICT(fingerprint) DO NOTHING`，撞了指纹就查回已有 id，
  同一个条目反复出题不会让 question 表膨胀
- `quiz_attempt.user_answer` 是 TEXT：字符串原样存，列表/布尔按 JSON 存，
  读的时候用 `loads_answer()` 还原（数据契约 §3）
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from app.db.repo.items import now_iso

_WS = re.compile(r"\s+")
# 选项自带的字母前缀："A. xxx" / "B、xxx" / "(C) xxx" / "D）xxx" / "A：xxx"
# 只认**大写** A–Z + 分隔符：小写（"e.g."）、数字（"3.5 倍"）都不动
_OPT_PREFIX = re.compile(r"^\s*(?:[(（]\s*([A-Z])\s*[)）]|([A-Z])\s*[.．、,，)）:：。])\s*")


def strip_option_prefix(text: str) -> str:
    """去掉选项自带的字母前缀，返回裸文本。

    M4 缺陷（2026-11-08 用户复现）：prompt 要求 options 自带 "A. " 前缀，而 UI 又画了一层
    字母徽标，界面渲染成「A. A. 在即将忘记…」。**字母只能由界面给**，数据层一律存裸文本。
    生成侧（`quizzer._options`）与读取侧（`row_to_question`）都过这个函数：
    前者保证新数据干净，后者让缺陷期入库的老题不改库也能正常显示。
    """
    if not isinstance(text, str):
        return text
    return _OPT_PREFIX.sub("", text, count=1).strip()


def clean_options(options) -> list[str]:
    """批量剥前缀，顺带去空（整个选项只有一个 "A." 时剥完就是空串）。

    空项会被丢掉：`normalize()` 里答案越界校验用的是**清洗后**的个数，
    所以「全是前缀的垃圾选项」会让该题判 `bad_answer` 被跳过，而不是错位。
    """
    if not isinstance(options, list):
        return []
    return [t for t in (strip_option_prefix(str(o)) for o in options if o is not None) if t]



def normalize_question(text: str) -> str:
    """去掉所有空白后再哈希：同一道题多一个空格不该算新题。"""
    return _WS.sub("", text or "")


def fingerprint(item_id: int | None, qtype: str, question: str) -> str:
    """M4 §6.3：sha256(item_id | type | 归一化题干)。"""
    raw = f"{item_id}|{qtype}|{normalize_question(question)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def dumps_answer(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def loads_answer(value: str | None):
    if value is None:
        return None
    text = value.strip()
    if text.startswith(("[", "{", "true", "false", "null")) or text.lstrip("-").isdigit():
        try:
            return json.loads(text)
        except ValueError:
            return value
    return value


def upsert_question(
    conn: sqlite3.Connection,
    *,
    item_id: int | None,
    qtype: str,
    difficulty: str,
    payload: dict,
    fp: str,
    origin: str = "ai",
    number: str | None = None,
) -> tuple[int, bool]:
    """返回 (题目 id, 是否新建)。撞指纹时复用已有 id，不重复插入。

    `origin` / `number` 是 M10 给试卷导入用的（`imported` + 原卷题号）。
    默认值保住 M4 的出题调用点：模型生成的题恒为 `ai`、无题号（数据契约 `question.origin`）。

    **导入题的「改」不走这里**：复核页改题干/答案要原地改（`update_payload`），
    按指纹 upsert 会把「改了一个错字」变成「多出一道题」。
    """
    cur = conn.execute(
        """INSERT INTO question (item_id, type, difficulty, payload, fingerprint,
                                 origin, number, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(fingerprint) DO NOTHING""",
        (item_id, qtype, difficulty, json.dumps(payload, ensure_ascii=False), fp,
         origin, number, now_iso()),
    )
    if cur.rowcount:
        return int(cur.lastrowid), True
    row = conn.execute("SELECT id FROM question WHERE fingerprint=?", (fp,)).fetchone()
    return int(row["id"]), False


def update_payload(
    conn: sqlite3.Connection,
    question_id: int,
    *,
    qtype: str,
    difficulty: str,
    payload: dict,
    number: str | None,
) -> None:
    """原地改一道导入题（试卷复核「改完再导入」）。

    **指纹不动**：它只是出题去重的键（`item_id|type|归一化题干`），导入题的身份是
    「这份卷子的第几题」。跟着改指纹还会和别的行撞唯一索引 —— 复核页把两道题改成
    同一个题干是完全合法的操作。
    """
    conn.execute(
        "UPDATE question SET type=?, difficulty=?, payload=?, number=? WHERE id=?",
        (qtype, difficulty, json.dumps(payload, ensure_ascii=False), number, question_id),
    )


NUMBER_DIGITS = re.compile(r"^\d+$")


def _number_key(number: str | None) -> tuple[int, str]:
    """整卷题号的排序键：数字题号按数值排，其余（`二.3` / 空）排在后面按文本排。

    不能直接 `ORDER BY number`：`number` 是 TEXT，字典序会把第 10 题排到第 2 题前面，
    「按卷练」就变成「按字典练」。数据契约里它是 TEXT（要能存 `二.3`），排序只能在这里补。
    """
    text = (number or "").strip()
    if NUMBER_DIGITS.match(text):
        return (0, f"{int(text):06d}")
    return (1, text)


def list_paper(conn: sqlite3.Connection, item_id: int) -> list[dict]:
    """一份试卷的全部题目，按题号排好（`GET /api/quiz/paper/{item_id}`）。

    只取这一份内容的题：`question.item_id` 是「这份卷子」的唯一依据，
    同一道题被另一份卷子也导过会各有一条（指纹里带 item_id，M4 §6.3 的既有口径）。

    `number IS NOT NULL` 是「还属于这份卷子」的判据：用户删掉但有作答记录的题
    会被摘掉题号留在库里（见 `services/exam/commit._drop_unused`），不再出现在卷子里。
    """
    rows = conn.execute(
        """SELECT * FROM question
           WHERE item_id=? AND origin='imported' AND number IS NOT NULL
           ORDER BY id""",
        (item_id,),
    ).fetchall()
    items = [row_to_question(r) for r in rows]
    items.sort(key=lambda q: _number_key(q.get("number")))
    return items


def row_to_question(row: sqlite3.Row) -> dict:
    question = dict(row)
    try:
        payload = json.loads(question.pop("payload") or "{}")
    except (ValueError, TypeError):
        payload = {}
    # payload 原样留一份：分值/材料/题组只在里面（需求 §5.5 不改表），
    # M10 的「按卷练」要显示「第 12 题 · 2 分」和材料题共用的大段材料
    question["payload"] = payload
    question["question"] = payload.get("question", "")
    # 读侧也剥一次：缺陷期（prompt 要求带前缀）入库的老题不改库也能正常显示
    question["options"] = clean_options(payload.get("options"))
    question["answer"] = payload.get("answer")
    question["explanation"] = payload.get("explanation", "")
    return question


def get_question(conn: sqlite3.Connection, question_id: int) -> dict | None:
    """带来源标题：判分与错题本都要显示「这道题出自哪篇」。"""
    row = conn.execute(
        """SELECT q.*, i.title AS source_title
           FROM question q LEFT JOIN knowledge_item i ON i.id = q.item_id
           WHERE q.id = ?""",
        (question_id,),
    ).fetchone()
    return row_to_question(row) if row is not None else None


def list_questions(
    conn: sqlite3.Connection, *, item_id: int | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    clause, args = ("WHERE item_id = ?", [item_id]) if item_id is not None else ("", [])
    total = conn.execute(f"SELECT COUNT(*) FROM question {clause}", args).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM question {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        [*args, limit, offset],
    ).fetchall()
    return [row_to_question(r) for r in rows], total


def count_questions(conn: sqlite3.Connection, item_id: int | None = None) -> int:
    if item_id is None:
        return conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM question WHERE item_id=?", (item_id,)
    ).fetchone()[0]


def save_attempt(
    conn: sqlite3.Connection,
    *,
    question_id: int,
    user_answer,
    is_correct: int | None,
    feedback: str | None = None,
    duration_ms: int | None = None,
) -> int:
    """is_correct 三态：1 / 0 / NULL（待人工判断）。NULL 绝不能落成 0。"""
    cur = conn.execute(
        """INSERT INTO quiz_attempt
           (question_id, user_answer, is_correct, feedback, duration_ms, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (question_id, dumps_answer(user_answer), is_correct, feedback, duration_ms, now_iso()),
    )
    return int(cur.lastrowid)


def attempts_of(conn: sqlite3.Connection, question_id: int, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT id, user_answer, is_correct, feedback, duration_ms, created_at
           FROM quiz_attempt WHERE question_id=? ORDER BY id DESC LIMIT ?""",
        (question_id, limit),
    ).fetchall()
    out = []
    for row in rows:
        attempt = dict(row)
        attempt["user_answer"] = loads_answer(attempt["user_answer"])
        out.append(attempt)
    return out
