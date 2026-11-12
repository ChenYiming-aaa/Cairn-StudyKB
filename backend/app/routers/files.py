"""文件上传（T9.3）。只收原件、回报排队状态；读字在后台任务里做（T9.6 / T9.7）。

路由刻意很薄：校验扩展名、大小、去重、落盘、建内容全在 `services/files.py`，
这个文件只负责 multipart 解析与响应形状（接口契约 §3.1 `POST /api/files`）。
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.services import files as file_service

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("")
def upload_file(
    file: UploadFile = File(...),
    workspace_id: int | None = Form(default=None),
):
    """上传一个文件，返回 `{file_id, item_id, page_count, ocr_status, preview}`。

    `ocr_status` 如实回报：PDF / 图片是 `pending`（等后台识别），其余是 `none`（抽取不走识别）。
    同一份文件二次上传返回**同一个 item_id 与 file_id**，不占新盘（靠 `item_file.sha256`）。
    """
    declared = getattr(file, "size", None)
    if declared and declared > file_service.MAX_BYTES:
        # 已经收完的请求体不必再落一遍盘：头部给了大小就先拒
        raise file_service.too_large(int(declared))

    saved = file_service.save(
        file.file, filename=file.filename or "", workspace_id=workspace_id
    )
    return JSONResponse(
        status_code=201,
        content={
            "file_id": saved.file_id,
            "item_id": saved.item_id,
            "page_count": saved.page_count,
            "ocr_status": saved.ocr_status,
            "preview": saved.preview,
        },
    )
