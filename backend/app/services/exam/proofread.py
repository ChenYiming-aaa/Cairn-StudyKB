"""模型校对（T10.4）：**只改错，不改写**。

识别给了 95% 正确的文字，剩下的 5% 是形近字、全半角、题号读错。这些错靠规则修不掉
（`clean.normalize_width` 只处理标点，不认「己/已」），交给模型最划算。

但「让模型看一遍文字」是这一层最危险的地方：它会顺手把卷子改成一篇通顺的文章，
而用户看不出来——题还是那些题，字却变了，答案对不上只能怪自己。
所以三道闸门，缺一不可：

1. **只收结构化 diff**（`[{line, before, after, why}]`），不收整篇重写。
   行数必须对得上，`before` 必须与原文一字不差（去空白比）——模型在抄错 `before`，
   说明它在编，这一条直接丢。
2. **编辑距离 ≤ 行长 × 30%**（需求 §8.4）。超了整条丢，记进 `dropped` 并说明原因。
   拦的就是「顺手润色」：把一句话重写完，编辑距离一定远超 30%。
3. **原文永不被覆盖**：结果写 `item_page.text_reviewed`，`text` 一直是识别原样。
   任何时候 `reset` 一下就能退回去（需求 §8.5 最后一条）。

「拒绝执行指令」也在这里：识别文本里夹着「请润色」四个字时，那是卷子内容，
不是给模型的命令 —— prompt 里写死了照原样留着。
"""
from __future__ import annotations

import logging

from app.db.conn import get_conn
from app.errors import ApiError
from app.paths import app_path
from app.services import llm

log = logging.getLogger(__name__)

MAX_BLOCK_CHARS = 2000      # 单块上限（需求 §8.4）：再长模型开始跳行，行号对不上
MAX_EDIT_RATIO = 0.30       # 编辑距离 / 行长，超了整条丢弃
WHY_KINDS = ("错字", "全半角", "题号")


def _template() -> str:
    return (app_path("prompts") / "exam_proof.md").read_text(encoding="utf-8")


def split_blocks(lines: list[str], *, limit: int = MAX_BLOCK_CHARS) -> list[list[tuple[int, str]]]:
    """按字数切块，保留**页内行号**（1-based）。

    行号是模型与原文之间唯一的锚：它说「第 12 行」，我们改第 12 行。
    所以切块只能切在行边界上，绝不能把一行劈成两块 —— 劈开的行模型会当成两行，
    报回来的行号全部错位。
    """
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    size = 0
    for index, line in enumerate(lines, 1):
        need = len(line) + 8            # 行号前缀 `12|` + 换行
        if current and size + need > limit:
            blocks.append(current)
            current, size = [], 0
        current.append((index, line))
        size += need
    if current:
        blocks.append(current)
    return blocks


def _render(block: list[tuple[int, str]]) -> str:
    return "\n".join(f"{number}|{line}" for number, line in block)


def messages(block: list[tuple[int, str]]) -> list[dict]:
    body = (
        f"{_template()}\n\n"
        "—— 识别文本开始 ——\n"
        f"{_render(block)}\n"
        "—— 识别文本结束 ——\n\n"
        "现在只输出那个 JSON 对象。"
    )
    return [{"role": "user", "content": body}]


def _squash(text: str) -> str:
    """去掉所有空白再比：识别会在行首行尾塞空格，不该因为空格判 `before` 抄错。"""
    return "".join(str(text).split())


def _levenshtein(a: str, b: str) -> int:
    """编辑距离。行最长几百字，朴素 DP 够用（不做 Myers，那要多一大段代码）。"""
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _answer_guard(origin: str, after: str) -> str | None:
    """答案行只许改标点，不许改字母数字。

    编辑距离拦不住这一条：`答案：B` → `答案：C` 只差一个字，30% 的闸门放得下。
    但这是整个 M10 里伤害最大的一种错——用户按错的答案复习（风险表第 7 条）。
    答案由复核页的人来定，校对层一个字都不许碰。
    """
    if "答案" not in origin:
        return None

    def keep(text: str) -> str:
        return "".join(ch for ch in text if ch.isalnum())

    return None if keep(origin) == keep(after) else "答案内容被改动"


def verify(raw: list, block: list[tuple[int, str]]) -> tuple[list[dict], list[dict]]:
    """校验模型给的改动，返回 (收下的, 丢掉的)。丢掉的带原因，界面要能解释。"""
    by_line = {number: line for number, line in block}
    accepted: list[dict] = []
    dropped: list[dict] = []
    seen: set[int] = set()

    for item in raw or []:
        if not isinstance(item, dict):
            dropped.append({"line": None, "why": "格式不对"})
            continue
        try:
            number = int(item.get("line"))
        except (TypeError, ValueError):
            dropped.append({"line": None, "why": "没有行号"})
            continue
        if number not in by_line:
            dropped.append({"line": number, "why": "行号不在这一块里"})
            continue
        if number in seen:
            # 一行只收一条：两条改同一行，后一条会盖掉前一条，用户看到的和实际存的不一样
            dropped.append({"line": number, "why": "同一行给了两条改动"})
            continue

        origin = by_line[number]
        before = str(item.get("before") or "")
        after = str(item.get("after") or "")
        if _squash(before) != _squash(origin):
            # 模型抄错 before = 它在编，不是在改错字。这条不能信
            dropped.append({"line": number, "why": "before 与原文对不上"})
            continue
        if not after.strip():
            dropped.append({"line": number, "why": "改成了空行"})
            continue
        if _squash(after) == _squash(origin):
            continue                     # 改了等于没改，不算改动也不报错
        answer_issue = _answer_guard(origin, after)
        if answer_issue:
            dropped.append({"line": number, "why": answer_issue})
            continue
        dist = _levenshtein(_squash(origin), _squash(after))
        allowed = max(1, len(_squash(origin)) * MAX_EDIT_RATIO)
        if dist > allowed:
            # 这条最关键：改写/润色都会落在这里。宁可漏一个错字，也不要换掉整句话
            dropped.append({"line": number,
                            "why": f"改动过大（{dist} 字，上限 {int(allowed)}）"})
            continue

        why = str(item.get("why") or "").strip()
        seen.add(number)
        accepted.append({
            "line": number,
            "before": origin,
            "after": after,
            "why": why if why in WHY_KINDS else "错字",
        })
    accepted.sort(key=lambda c: c["line"])
    return accepted, dropped


def _page_lines(text: str) -> list[str]:
    """页文本 → 行。**不归一、不合并**：校对的行号必须与落库的 `text` 一一对应。"""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def review_page(page_no: int, text: str, *, use_llm: bool = True) -> dict:
    """校对一页。返回 `{page_no, lines, changes, dropped, failed}`。"""
    lines = _page_lines(text)
    changes: list[dict] = []
    dropped: list[dict] = []
    failed = 0

    if use_llm:
        for block in split_blocks(lines):
            if not any(line.strip() for _, line in block):
                continue
            try:
                raw = llm.chat(messages(block), agent="exam_proof", json_mode=True)
                data = llm.extract_json(raw)
            except llm.LLMError as exc:
                log.warning("第 %s 页第 %s 行起的块校对放弃（%s）", page_no, block[0][0], exc.code)
                failed += 1
                continue
            except Exception as exc:        # noqa: BLE001 - 一块失败不能拖垮整页
                log.warning("第 %s 页校对异常：%s", page_no, type(exc).__name__)
                failed += 1
                continue
            got, lost = verify(data.get("changes"), block)
            changes.extend(got)
            dropped.extend(lost)

    return {
        "page_no": page_no,
        "lines": len(lines),
        "changes": changes,
        "dropped": dropped,
        "failed": failed,
    }


def _load_pages(file_id: int) -> tuple[int, list[dict]]:
    conn = get_conn()
    try:
        file = conn.execute(
            "SELECT id, item_id FROM item_file WHERE id=?", (file_id,)).fetchone()
        if file is None:
            raise ApiError("FILE_NOT_FOUND", "这份原件不在库里了，重新上传一次", status=404)
        rows = conn.execute(
            """SELECT page_no, text, text_reviewed FROM item_page
               WHERE file_id=? ORDER BY page_no""",
            (file_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise ApiError("FILE_NOT_READY", "这个文件还在读字，读完再校对。进度在采集面板里能看到",
                       status=409)
    return int(file["item_id"]), [dict(r) for r in rows]


def proofread(file_id: int, *, use_llm: bool = True) -> dict:
    """整份校对。**纯计算不落库**：改动先给用户看，接受哪些由 `apply` 决定。"""
    item_id, pages = _load_pages(file_id)
    results = [review_page(p["page_no"], p["text"], use_llm=use_llm) for p in pages]
    total_lines = sum(r["lines"] for r in results)
    changed = sum(len(r["changes"]) for r in results)
    dropped = sum(len(r["dropped"]) for r in results)
    log.info("校对完成：file=%s %s 行，改动 %s 处，丢弃 %s 条，失败块 %s",
             file_id, total_lines, changed, dropped,
             sum(r["failed"] for r in results))
    return {
        "item_id": item_id,
        "file_id": file_id,
        "use_llm": use_llm,
        "total_lines": total_lines,
        "changed": changed,
        "dropped": dropped,
        "pages": results,
    }


def apply(file_id: int, accepted: list[dict]) -> dict:
    """把用户接受的改动写进 `text_reviewed`。**每次都从 `text` 重建**。

    从原文重建而不是在已有结果上打补丁：用户拒掉一条、再接受另一条，打补丁会留下
    上一轮的痕迹（同一条被应用两次、或撤销不掉的改动）。重建是幂等的，调多少次
    结果都只取决于这一次收到的清单。

    落库前再校验一遍编辑距离：清单是前端传回来的，中间可能被别的路径改过。
    守卫只在服务端才算数。
    """
    item_id, pages = _load_pages(file_id)
    if not pages:
        raise ApiError("FILE_NOT_READY", "这个文件还在读字，读完再校对", status=409)

    wanted: dict[int, dict[int, str]] = {}
    for item in accepted or []:
        if not isinstance(item, dict):
            continue
        try:
            page_no = int(item.get("page_no"))
            line = int(item.get("line"))
        except (TypeError, ValueError):
            continue
        after = str(item.get("after") or "")
        if after.strip():
            wanted.setdefault(page_no, {})[line] = after

    applied = 0
    dropped: list[dict] = []
    conn = get_conn()
    try:
        with conn:
            for page in pages:
                lines = _page_lines(page["text"])
                picks = wanted.get(page["page_no"]) or {}
                if not picks:
                    conn.execute("UPDATE item_page SET text_reviewed=NULL WHERE file_id=? AND page_no=?",
                                 (file_id, page["page_no"]))
                    continue
                out = list(lines)
                for number, after in picks.items():
                    if not (1 <= number <= len(lines)):
                        dropped.append({"page_no": page["page_no"], "line": number,
                                        "why": "这一页没有这个行号"})
                        continue
                    origin = lines[number - 1]
                    if _answer_guard(origin, after):
                        dropped.append({"page_no": page["page_no"], "line": number,
                                        "why": "答案内容被改动"})
                        continue
                    dist = _levenshtein(_squash(origin), _squash(after))
                    if dist > max(1, len(_squash(origin)) * MAX_EDIT_RATIO):
                        dropped.append({"page_no": page["page_no"], "line": number,
                                        "why": "改动过大"})
                        continue
                    out[number - 1] = after
                    applied += 1
                reviewed = "\n".join(out)
                # 一个字都没改就不存：存一份和原文一样的副本，「已校对」就成了假话
                value = None if reviewed == page["text"] else reviewed
                conn.execute(
                    "UPDATE item_page SET text_reviewed=? WHERE file_id=? AND page_no=?",
                    (value, file_id, page["page_no"]),
                )
    finally:
        conn.close()

    log.info("校对落库：file=%s 接受 %s 处（丢弃 %s 条）", file_id, applied, len(dropped))
    return {
        "item_id": item_id,
        "file_id": file_id,
        "pages": sum(1 for p in pages if (wanted.get(p["page_no"]) or {})),
        "applied": applied,
        "dropped": dropped,
    }


def reset(file_id: int) -> dict:
    """回退到原始识别文本（需求 §8.5：任何时候能退回去）。"""
    item_id, pages = _load_pages(file_id)
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE item_page SET text_reviewed=NULL WHERE file_id=? AND text_reviewed IS NOT NULL",
                (file_id,),
            )
    finally:
        conn.close()
    log.info("校对回退：file=%s 清掉 %s 页的校对结果", file_id, cur.rowcount)
    return {"item_id": item_id, "file_id": file_id, "reverted": int(cur.rowcount or 0),
            "pages": len(pages)}


def page_text(conn, file_id: int, page_no: int) -> str:
    """读某一页**当前该用的**文本：校对过就用校对结果，否则用原识别文本。

    只有一个入口，免得调用方自己写 `text_reviewed or text` —— 漏一处就读到旧文本。
    """
    row = conn.execute(
        "SELECT text, text_reviewed FROM item_page WHERE file_id=? AND page_no=?",
        (file_id, page_no),
    ).fetchone()
    if row is None:
        return ""
    return row["text_reviewed"] or row["text"] or ""
