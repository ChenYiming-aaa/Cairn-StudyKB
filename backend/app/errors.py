"""统一错误响应与异常。总纲 §7：{"error": {"code","message","detail"}}。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, code: str, message: str, detail: str = "", status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.status = status


def error_payload(code: str, message: str, detail: str = "") -> dict:
    return {"error": {"code": code, "message": message, "detail": detail}}


def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=error_payload(exc.code, exc.message, exc.detail),
    )
