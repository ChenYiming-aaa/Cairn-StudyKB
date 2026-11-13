"""读字流水线：PDF/图片走识别（T9.6），docx/pptx/xlsx/txt 走抽取（T9.7）。

**两条路，一个收口**：`run()` 按扩展名分派 —— `OCR_EXT` 进 `_run_ocr()`，
`extractors.EXTRACT_EXT` 进 `run_extract()`，两者最后都汇到 `_finish()`。
这样「只有每一页都有行才覆盖正文」这条不变量只写一次，不会出现
"识别那条守住了、抽取那条忘了"的裂缝（少写一次覆盖，用户看到的是半份笔记）。

识别是**逐页**的（30 页可以崩在第 12 页），抽取是**整份**的（一次解析要么成要么败）——
所以抽取不需要断点续跑：失败时一页都不写，重试就是从头再来，代价不过一两秒。

--- 以下是识别链路的细节（T9.6）---

渲染一页 → 识别一页 → 落库一页 → 释放。

**逐页流式**不是讲究：30 页 A4 在 150 dpi 下约 1.3 MB/页，一次全渲染就是 40 MB 常驻，
300 页的教材会直接把内存吃掉（执行计划 §8.3「内存涨到 1 GB+」）。所以任何时刻
内存里最多只有一批（5 张）位图，落库后立刻丢掉。

**断点续跑靠的是"页在库里"这件事本身**：`item_page` 有这一页的行，就不再识别；
没有就补。中途 kill 进程最多丢当前那一批（最多 5 页），已落库的一页都不会重跑。
这也是 `item_page` 必须逐页写、逐页提交的原因 —— 攒到最后一次性写，断点续跑就失效了。

**失败分两级**（和数据契约一致）：

- 单页失败（图读不出来 / 组件报错）：这一页**不写行**，于是它自然出现在「没识别的页」里，
  可以单独重试；不影响别的页。
- 整份失败（组件崩了 / 没装组件）：任务记 failed，`ocr_status` 按已完成的量写
  `partial` 或 `failed`，**不留 running**（留着的话界面永远转圈）。

**空页不是失败**：`text` 为空照样写行、`avg_conf=0`，整份里有空页就标 `partial`。
把空页当成失败会让"这份文件本来就没字"和"识别没跑完"混成一件说不清的事。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from app.db.conn import get_conn
from app.db.repo import files as file_repo
from app.db.repo import items as item_repo
from app.db.repo import pages as page_repo
from app.errors import ApiError
from app.services import files as file_service
from app.services import extractors, ocr, ocr_layout, pdf_pages, tasks as task_queue

log = logging.getLogger(__name__)

TASK_TYPE = "ocr_pages"
TASK_EXTRACT = "extract_text"
STAGE = "ocr"
STAGE_EXTRACT = "extract"
OCR_EXT = {"pdf"} | file_service.IMAGE_EXT


def run(payload: dict, task_id: str | None = None) -> dict:
    """任务入口：`payload = {"file_id": 12, "pages": [3]}`，按扩展名分派。

    不认识的格式**静默跳过**而不是报错：调用方可能是批量导入的通用入口，
    它不该为"这格式不用读"失败（T9.6 定的口径，T9.7 沿用）。
    """
    row = _load_file(payload)
    ext = _ext(row)
    if ext in OCR_EXT:
        return _run_ocr(row, _page_list(payload.get("pages")), task_id)
    if extractors.for_ext(ext) is not None:
        return run_extract(payload, task_id)
    return {"skipped": True, "file_id": int(row["id"]),
            "reason": f"{ext or '未知格式'} 没有读取路径"}


def _load_file(payload: dict) -> sqlite3.Row:
    file_id = int(payload.get("file_id") or 0)
    conn = get_conn()
    try:
        row = file_repo.get(conn, file_id)
    finally:
        conn.close()
    if row is None:
        raise ApiError("FILE_NOT_FOUND", "原件不存在，可能已经被删了", status=404)
    return row


def _ext(row: sqlite3.Row) -> str:
    return str(row["ext"] or "").lower()


def _run_ocr(row: sqlite3.Row, only: list[int], task_id: str | None) -> dict:
    file_id = int(row["id"])
    item_id = int(row["item_id"])
    ext = _ext(row)
    source = file_service.abs_path(str(row["stored_path"] or ""))
    if not source.is_file():
        raise ApiError("FILE_NOT_FOUND", "原件在盘上找不到了，重新上传一次", status=404)

    pdf = pdf_pages.open_pdf(source) if ext == "pdf" else None

    try:
        total = pdf_pages.page_count(pdf) if pdf is not None else 1
        if total <= 0:
            raise ApiError("OCR_FAILED", "这份 PDF 里没有页面", status=502)
        todo = _todo_pages(file_id, total, only)
        _mark(file_id, "running", page_count=total)
        if not todo:
            # 断点续跑的常见结局：上次已经跑完，或用户点重试的页刚跑好
            return _finish(file_id, item_id, total, task_id, skipped=True)

        done_before = _count_pages(file_id)
        for chunk in _batches(todo, ocr.BATCH):
            images = [(no, _render(pdf, file_id, no, ext, row)) for no in chunk]
            results = ocr.recognize([_abs(img) for _, img in images])
            for (page_no, img), result in zip(images, results):
                _write_page(item_id, file_id, page_no, result, img)
            done_before += len(chunk)
            if task_id:
                # 分批上报：30 页走 6 批，界面每批跳一次，不用等整份
                task_queue.update_progress(
                    task_id, round(done_before * 100 / total),
                    f"{STAGE} {done_before}/{total}",
                )
    except BaseException:
        # 整份中断（组件崩、超时、磁盘满）：状态必须诚实，不能停在 running
        done = _count_pages(file_id)
        _mark(file_id, "partial" if done else "failed")
        raise
    finally:
        if pdf is not None:
            pdf.close()

    return _finish(file_id, item_id, total, task_id)


def run_extract(payload: dict, task_id: str | None = None) -> dict:
    """抽取入口（T9.7）：一次解析、一次落库、一次收口。

    **整份要么成要么败**：不像识别那样逐页写，所以这里先把解析做完再动库 ——
    解析到一半失败时库里一页都没写，重试就是干净的重来（也正因此不需要断点续跑）。
    """
    row = _load_file(payload)
    file_id = int(row["id"])
    item_id = int(row["item_id"])
    ext = _ext(row)
    if extractors.for_ext(ext) is None:
        return {"skipped": True, "file_id": file_id, "reason": f"{ext} 不走抽取"}

    source = file_service.abs_path(str(row["stored_path"] or ""))
    if not source.is_file():
        raise ApiError("FILE_NOT_FOUND", "原件在盘上找不到了，重新上传一次", status=404)

    _mark(file_id, "running")
    try:
        doc = extractors.extract(source, ext, original_name=str(row["original_name"] or ""))
    except BaseException:
        # 打不开 / 加密 / 空表：状态必须是 failed，不能停在 running
        _mark(file_id, "failed")
        raise
    if task_id:
        task_queue.update_progress(task_id, 50, f"{STAGE_EXTRACT} 已读取 {doc.page_count} 页")

    _write_extracted(item_id, file_id, doc)
    if task_id:
        task_queue.update_progress(task_id, 90, f"{STAGE_EXTRACT} 已写入 {doc.page_count} 页")
    # 截断（xlsx 超 200 行、txt 超 100 万字）必须降到 partial：
    # 页是齐的，但内容只有一部分 —— 说 done 会让「整理」照着半份写笔记，
    # 而用户在界面上看不到任何异常（T9.8 实测：261 行 xlsx 显示「已读取 1 页」）
    result = _finish(file_id, item_id, doc.page_count, task_id,
                     truncated=bool(doc.meta.get("truncated")))
    result["meta"] = doc.meta
    return result


# ── 对内 ────────────────────────────────────────────────
def _page_list(value) -> list[int]:
    """`pages` 允许 [3] / ["3"] / None；越界与非法值一律忽略，由调用方先校验。"""
    if not value:
        return []
    out: list[int] = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number >= 1 and number not in out:
            out.append(number)
    return out


def _todo_pages(file_id: int, total: int, only: list[int]) -> list[int]:
    """要识别的页号：点名了就跑点名页（重试），否则补所有还没落库的页。"""
    if only:
        return [n for n in only if 1 <= n <= total]
    conn = get_conn()
    try:
        have = {int(r["page_no"]) for r in page_repo.list_by_file(conn, file_id)}
    finally:
        conn.close()
    return [n for n in range(1, total + 1) if n not in have]


def _batches(items: list[int], size: int) -> list[list[int]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _render(pdf, file_id: int, page_no: int, ext: str, row: sqlite3.Row):
    """页图：PDF 现渲染；图片文件的页图就是原件本身（不复制、不重编码）。"""
    if pdf is not None:
        return pdf_pages.render(pdf, page_no - 1, file_id)
    return pdf_pages.PageImage(path=str(row["stored_path"]), width=0, height=0)


def _abs(image: pdf_pages.PageImage) -> Path:
    return pdf_pages.abs_path(image.path)


def _count_pages(file_id: int) -> int:
    conn = get_conn()
    try:
        return len(page_repo.list_by_file(conn, file_id))
    finally:
        conn.close()


def _mark(file_id: int, status: str, page_count: int | None = None) -> None:
    conn = get_conn()
    try:
        with conn:
            fields: dict = {"ocr_status": status}
            if page_count is not None:
                fields["page_count"] = page_count
            file_repo.update(conn, file_id, fields)
    finally:
        conn.close()


def _write_page(item_id: int, file_id: int, page_no: int,
                result: ocr.PageResult, image: pdf_pages.PageImage) -> None:
    """一页一提交：崩在下一批也不丢这一页（断点续跑的全部依据）。"""
    if not result.ok:
        log.warning("第 %s 页没识别出来：%s %s", page_no, result.error, result.message)
        return
    rows = ocr_layout.order_lines_detail(result.lines, result.width or image.width)
    text = "\n".join(row["text"] for row in rows)
    conn = get_conn()
    try:
        with conn:
            page_repo.upsert(
                conn, item_id=item_id, file_id=file_id, page_no=page_no,
                text=text, source="ocr",
                avg_conf=ocr_layout.avg_conf(result.lines),
                # 逐行置信度与 text 同源、同一顺序：原文页签按行标黄全靠它
                line_conf=json.dumps([row["conf"] for row in rows], ensure_ascii=False) if rows else None,
                image_path=image.path,
            )
    finally:
        conn.close()


def _write_extracted(item_id: int, file_id: int, doc) -> None:
    """抽取结果一次写完：先删旧页再插新页，同一个事务。

    删旧页是为了「重新读取」：第二次解析如果页数变少（改了 pptx 再传一次，
    但内容相同不会重传，这条主要防手工触发的重读），残留的旧页会让
    `done != total` 永远不成立，正文永远不覆盖。
    """
    conn = get_conn()
    try:
        with conn:
            page_repo.delete_by_file(conn, file_id)
            for page in doc.pages:
                page_repo.upsert(
                    conn, item_id=item_id, file_id=file_id, page_no=page.page_no,
                    text=page.text, source="extract", image_path=None,
                )
            file_repo.update(conn, file_id, {
                "has_text_layer": 1, "page_count": doc.page_count,
            })
    finally:
        conn.close()
    # HTML 存盘而不是入库：它是给原文页签渲染用的，检索用不到，
    # 进库只会把 SQLite 撑大（一份带版式的讲义 HTML 有几十 KB）
    _save_html(file_id, doc.pages)


def _save_html(file_id: int, pages: list) -> None:
    """docx 的 HTML 落到 `pages/<file_id>/0001.html`（与页图同目录，删内容时一并清掉）。"""
    for page in pages:
        if not page.html:
            continue
        path = pdf_pages.file_dir(file_id) / f"{page.page_no:04d}.html"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(page.html, encoding="utf-8")
        except OSError as exc:
            # 原文页签缺一份 HTML 不影响检索与整理，不值得让整份抽取失败
            log.warning("第 %s 页 HTML 没写成（%s）", page.page_no, exc)


def _finish(file_id: int, item_id: int, total: int, task_id: str | None,
            skipped: bool = False, truncated: bool = False) -> dict:
    """收口：算状态 → 状态写回 → （整份齐了）覆盖正文、重建 chunk。

    只有**每一页都有行**才覆盖正文：缺页时覆盖会把半份内容当成全文，
    检索能搜到、整理会照着半份写笔记，而用户看不出少了什么。
    """
    conn = get_conn()
    try:
        rows = page_repo.list_by_file(conn, file_id)
        done = len(rows)
        empty = sum(1 for r in rows if not (r["text"] or "").strip())
        if done == 0:
            status = "failed"
        elif done < total or empty or truncated:
            status = "partial"
        else:
            status = "done"

        with conn:
            file_repo.update(conn, file_id, {"ocr_status": status, "page_count": total})
            replaced = False
            if done == total:
                text = _join_text(rows)
                if text.strip():
                    item_repo.replace_raw_content(conn, item_id, text)
                    item_repo.rebuild_chunks(conn, item_id, text, "raw")
                    replaced = True
    finally:
        conn.close()

    if replaced:
        # EMBED_AFTER 刻意不含 ocr_pages（卡里明写不变）：识别是后台长任务，
        # 补向量另起一条，失败也不该把识别结果判成失败
        try:
            from app.services import embedder

            embedder.schedule(item_id)
        except Exception as exc:              # noqa: BLE001
            log.warning("识别完成但补向量没派出去（%s），条目 %s", type(exc).__name__, item_id)

    if task_id:
        task_queue.update_progress(task_id, 100, f"{STAGE} {done}/{total}")
    log.info("识别收口 file=%s item=%s %s/%s 页，空页 %s，状态 %s%s",
             file_id, item_id, done, total, empty, status, "（无需重跑）" if skipped else "")
    return {
        "file_id": file_id, "item_id": item_id, "status": status,
        "done_pages": done, "total_pages": total, "empty_pages": empty,
        "skipped": skipped,
    }


def _join_text(rows: list[sqlite3.Row]) -> str:
    """全文按页顺序拼，空页不占位。

    不加「第 N 页」标记：那会把版面噪音写进正文，检索与整理都被带偏。
    页与 chunk 的对应关系在 T11.2 用 `item_page.text` 反查，不靠正文里的标记。
    """
    return "\n".join((r["text"] or "").strip() for r in rows if (r["text"] or "").strip())


# ── 启动清理 ────────────────────────────────────────────
def reset_stale() -> int:
    """把上次没跑完的 `running` 拨回 `pending`（启动时调用，见 repo.reset_running）。"""
    conn = get_conn()
    try:
        with conn:
            count = file_repo.reset_running(conn)
        if count:
            log.info("已将 %s 份原件的识别状态从 running 拨回 pending", count)
        return count
    finally:
        conn.close()
