"""文件上传（T9.3）。只收原件、回报排队状态；读字在后台任务里做（T9.6 / T9.7）。

路由刻意很薄：校验扩展名、大小、去重、落盘、建内容全在 `services/files.py`，
这个文件只负责 multipart 解析、**入队识别**（T9.6）与响应形状（接口契约 §3.1 `POST /api/files`）。
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.db.conn import get_conn
from app.db.repo import files as file_repo
from app.services import dispatch, ocr
from app.services import files as file_service

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("")
def upload_file(
    file: UploadFile = File(...),
    workspace_id: int | None = Form(default=None),
):
    """上传一个文件，返回 `{file_id, item_id, page_count, ocr_status, preview}`。

    `ocr_status` 如实回报：PDF / 图片落盘后**立刻排队识别**（返回 `running`），其余是 `none`。
    同一份文件二次上传返回**同一个 item_id 与 file_id**，不占新盘（靠 `item_file.sha256`）。
    """
    declared = getattr(file, "size", None)
    if declared and declared > file_service.MAX_BYTES:
        # 已经收完的请求体不必再落一遍盘：头部给了大小就先拒
        raise file_service.too_large(int(declared))

    saved = file_service.save(
        file.file, filename=file.filename or "", workspace_id=workspace_id
    )
    task_id = _queue_ocr(saved)
    return JSONResponse(
        status_code=201,
        content={
            "file_id": saved.file_id,
            "item_id": saved.item_id,
            "page_count": saved.page_count,
            "ocr_status": saved.ocr_status,
            "preview": saved.preview,
            "task_id": task_id,
        },
    )


def _queue_ocr(saved: file_service.Saved) -> str:
    """PDF / 图片落盘后直接排进识别队列，返回 task_id（别的格式空串）。

    **不在这里 409 掉上传**：原件必须留住，「读不出字」是后续状态而不是上传失败
    （T9.8 的界面就是按「已存好 + 需要装识别组件」两段来提示的）。
    没装组件时状态留在 `pending`，装上组件后用户点一下重识别即可。
    先写 running 再派任务：中间的毫秒级窗口里第二个请求不该又派一份。
    """
    if saved.ocr_status != "pending" or ocr.available() == "none":
        return ""
    conn = get_conn()
    try:
        with conn:
            file_repo.set_ocr_status(conn, saved.file_id, "running")
    finally:
        conn.close()
    saved.ocr_status = "running"
    return dispatch.submit(dispatch.TASK_OCR_PAGES, {"file_id": saved.file_id})
