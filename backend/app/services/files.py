"""原件落盘（T9.3）：文件进来先留住原件，再去读字。

原件是「认错了能回看」的唯一凭据（需求文档 L3），所以这里的顺序是**先落盘、再排队识别**，
任何抽取/识别失败都不许把原件弄丢。

四条必须守住的约束：

1. **流式接收**：边写临时文件边算 sha256，不 `read()` 一把梭（200 MB 会吃掉整个进程的内存）。
2. **存储名与展示名分离**：盘上只用 `<sha256 前 8 位>.<ext>`，原名只进数据库。
   中文、空格、重名都不会变成路径问题（Windows 上尤其明显）。
3. **同一份文件只占一次盘**：`item_file.sha256` 命中就复用已有内容，既不新建内容也不复制文件。
4. **`stored_path` 存相对数据目录的路径**（`files/12/a1b2c3d4.pdf`），
   整个数据目录搬走（换机器、换盘符）后仍能读到。
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.config import get_settings
from app.db.conn import get_conn
from app.db.repo import files as file_repo
from app.db.repo import items as item_repo
from app.db.repo import workspaces as workspace_repo
from app.errors import ApiError

log = logging.getLogger(__name__)

MAX_BYTES = 200 * 1024 * 1024
_READ_CHUNK = 1024 * 1024

# 扩展名白名单（小写、不带点）。加一种格式要同时想清楚：谁来读它（T9.6 识别 / T9.7 抽取）。
ALLOWED_EXT = {"docx", "pdf", "pptx", "xlsx", "txt", "md",
               "png", "jpg", "jpeg", "webp"}
IMAGE_EXT = {"png", "jpg", "jpeg", "webp"}
# 老格式单独给「另存为」的话，比一句「不支持」有用得多
LEGACY_EXT = {"doc": "docx", "wps": "docx", "ppt": "pptx", "xls": "xlsx", "xlt": "xlsx"}

_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


@dataclass
class Saved:
    """一次上传的落地结果。`duplicated=True` 表示这份文件库里已经有，没占新盘。"""

    file_id: int
    item_id: int
    page_count: int
    ocr_status: str
    preview: str
    duplicated: bool


def root() -> Path:
    return get_settings().data_dir / "files"


def item_dir(item_id: int) -> Path:
    return root() / str(item_id)


def abs_path(stored_path: str) -> Path:
    """相对路径 → 绝对路径。只认 `stored_path` 里存的那种形式。"""
    return get_settings().data_dir / stored_path


def ext_of(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def mime_of(ext: str) -> str:
    return _MIME.get(ext, "application/octet-stream")


def usage() -> dict:
    """原件占用统计（设置页显示「原件占了多少盘」）。临时目录不算。"""
    base = root()
    if not base.exists():
        return {"count": 0, "bytes": 0}
    count = total = 0
    for path in base.rglob("*"):
        if path.is_file() and path.parent.name != "_tmp":
            count += 1
            total += path.stat().st_size
    return {"count": count, "bytes": total}


def clear_tmp() -> int:
    """清掉上一次崩溃留下的半截上传（启动时调用）。"""
    tmp = root() / "_tmp"
    if not tmp.exists():
        return 0
    removed = 0
    for path in tmp.glob("*.part"):
        try:
            path.unlink()
            removed += 1
        except OSError:            # 另一个进程还在写，交给下一次启动
            pass
    return removed


def purge_item(item_id: int) -> None:
    """删内容时连带删原件目录。目录是内容独占的（同名文件也各存一份），不会误伤别的条目。"""
    folder = item_dir(item_id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
        log.info("已删除原件目录 files/%s", item_id)


def _check_ext(filename: str) -> str:
    ext = ext_of(filename)
    if ext in ALLOWED_EXT:
        return ext
    target = LEGACY_EXT.get(ext)
    if target:
        raise ApiError(
            "FILE_UNSUPPORTED",
            f"暂不支持 .{ext}，请另存为 .{target} 再上传",
            detail=f"legacy:{ext}",
            status=415,
        )
    raise ApiError(
        "FILE_UNSUPPORTED",
        f"暂不支持 .{ext or '未知'} 格式，可上传 Word / PDF / PPT / Excel / 图片 / 文本",
        status=415,
    )


def too_large(size: int) -> ApiError:
    """413。router 用它做 Content-Length 前置拦截，流式里也用它报错。"""
    mb = round(size / (1024 * 1024))
    return ApiError(
        "FILE_TOO_LARGE",
        f"这个文件 {mb} MB，超过 200 MB 上限，先压缩或拆分再试",
        status=413,
    )


def _stream_to_temp(stream: BinaryIO) -> tuple[Path, str, int]:
    """边写临时文件边算 sha256，超过上限立刻停手并删掉半截文件。"""
    tmp_dir = root() / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{uuid4().hex}.part"

    digest = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = stream.read(_READ_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:      # 先停手再报错：不落盘就没什么要清
                    raise too_large(size)
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise ApiError("FILE_EMPTY", "这个文件是空的，换个文件再试", status=422)
    return tmp, digest.hexdigest(), size


def _placeholder_title(filename: str) -> str:
    """列表里先给个人看得懂的名字；整理后会被 AI 标题覆盖（上限 20 字，同 PATCH 口径）。"""
    stem = Path(filename or "").stem.strip()
    return (stem or "未命名文件")[:20]


def _create_item(conn: sqlite3.Connection, *, filename: str, digest: str,
                 ext: str, workspace_id: int | None) -> sqlite3.Row:
    """建内容时先写占位正文，抽取完成后由 `replace_raw_content()` 覆盖。

    为什么要占位：`create_item` 用 `sha256(raw_content)` 去重，抽取前正文是空串，
    **所有文件类内容都会撞成同一个 hash**，第二个文件就会被判重复、直接返回第一个。
    占位正文让每条内容有各自的 hash；文件级去重另外靠 `item_file.sha256`。

    同名不同内容会撞占位正文（两次上传都还没抽取时），所以撞了就加 sha 前缀再来一次。
    """
    kind = "image" if ext in IMAGE_EXT else "material"
    title = _placeholder_title(filename)
    base = f"[文件] {filename}"
    for text in (base, *(f"{base}（{digest[:n]}）" for n in (8, 16, 32))):
        row, duplicated = item_repo.create_item(
            conn, title=title, raw_content=text, source_type="file",
            kind=kind, workspace_id=workspace_id,
        )
        if not duplicated:
            return row
    # 四种占位正文都撞上，说明库里有同名且同 hash 的占位内容 —— 不该发生
    raise RuntimeError("无法为这份文件建内容：占位正文全部撞哈希")


def _initial_ocr_status(ext: str) -> str:
    """标识待办状态：PDF 与图片要等识别，其余由抽取适配器直接读。

    这里只置 `pending`，真正入队发生在 T9.6/T9.7（任务处理器在那边注册）——
    绝不静默留 `none`，否则前端会显示「不需要识别」，用户以为已经读完了。
    """
    if ext == "pdf" or ext in IMAGE_EXT:
        return "pending"
    return "none"


def save(stream: BinaryIO, *, filename: str, workspace_id: int | None = None) -> Saved:
    """收一个文件：校验 → 落临时文件（算 sha）→ 去重 → 归位 → 建内容与原件行。

    调用方只负责把 `UploadFile.file` 递进来；错误一律是 `ApiError`，带 HTTP 状态。
    """
    ext = _check_ext(filename)
    tmp, digest, size = _stream_to_temp(stream)

    conn = get_conn()
    try:
        if workspace_id is not None and workspace_repo.get(conn, workspace_id) is None:
            tmp.unlink(missing_ok=True)
            raise ApiError("WORKSPACE_NOT_FOUND", "工作区不存在，可能已经被删了", status=404)

        hit = file_repo.find_by_hash(conn, digest)
        if hit is not None and abs_path(hit["stored_path"] or "").is_file():
            # 同一份文件：不新建内容、不复制文件，直接告诉调用方它在哪
            tmp.unlink(missing_ok=True)
            item = item_repo.get_item(conn, hit["item_id"])
            return Saved(
                file_id=int(hit["id"]), item_id=int(hit["item_id"]),
                page_count=int(hit["page_count"] or 0),
                ocr_status=hit["ocr_status"] or "none",
                preview=(item["raw_content"] if item else "")[:500],
                duplicated=True,
            )

        item_id: int | None = None
        try:
            with conn:
                row = _create_item(conn, filename=filename, digest=digest,
                                   ext=ext, workspace_id=workspace_id)
                item_id = int(row["id"])

                # 先建目录再挪文件：`shutil.move` 不建父目录，中文名也一律不进路径
                folder = item_dir(item_id)
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{digest[:8]}.{ext}"
                shutil.move(str(tmp), str(target))

                stored_path = target.relative_to(get_settings().data_dir).as_posix()
                file_id = file_repo.create(
                    conn, item_id=item_id, original_name=filename, ext=ext,
                    mime=mime_of(ext), size=size, sha256=digest,
                    stored_path=stored_path, ocr_status=_initial_ocr_status(ext),
                )
                # 反向指针：内容详情一次查询就能拿到主原件
                file_repo.link_item(conn, item_id, file_id)
                saved = file_repo.get(conn, file_id)
        except BaseException:
            # 事务已回滚，但文件可能已经挪进去了：目录按 item_id 独占，整目录删掉不会误伤
            tmp.unlink(missing_ok=True)
            if item_id is not None:
                purge_item(item_id)
            raise
    finally:
        conn.close()

    return Saved(
        file_id=int(saved["id"]), item_id=item_id,
        page_count=int(saved["page_count"] or 0),
        ocr_status=saved["ocr_status"],
        preview=f"[文件] {filename}"[:500],
        duplicated=False,
    )
