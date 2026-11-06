"""网页采集的错误码与中文文案（T2.2）。

集中一个 dict 的理由（M2 §1.3）：错误码给程序看、文案给人看，
前端要把 message 原样显示成"人话"，所以文案必须只在这里定义一次。
**不要**塞进 `app/errors.py`：那里只管 HTTP 错误响应的形状，不管业务原因。
"""
from __future__ import annotations

import httpx

# 错误码 → 中文文案（M2 §6.2 照抄；URL_INVALID 是接口契约 §3 的第 7 个码）
FETCH_MESSAGES: dict[str, str] = {
    "FETCH_TIMEOUT": "目标站点响应超时，请稍后重试",
    "FETCH_DNS": "无法连接到该站点，请检查链接或网络",
    "FETCH_BLOCKED": "目标站点拒绝访问（可能需要登录或限制抓取）",
    "FETCH_NOT_FOUND": "目标页面不存在或已删除",
    "FETCH_INVALID": "该链接不是网页",
    "FETCH_EMPTY": "未能提取到正文（可能是动态渲染页面），建议改用粘贴文本",
    "URL_INVALID": "链接格式不正确，请粘贴完整的 http(s) 地址",
}

# 这些状态码归到哪一类（403/429 是反爬或限流，404/410 是页面没了）
STATUS_CODES: dict[int, str] = {403: "FETCH_BLOCKED", 429: "FETCH_BLOCKED",
                                404: "FETCH_NOT_FOUND", 410: "FETCH_NOT_FOUND"}


class FetchError(Exception):
    """采集失败的统一异常。

    `tasks.submit` 靠 `exc.code` / `exc.message` 落 agent_task（红线 8），
    因此这两个属性名不能改。
    """

    def __init__(self, code: str, detail: str = "", message: str | None = None):
        self.code = code
        self.message = message or FETCH_MESSAGES.get(code, "采集失败")
        self.detail = detail
        super().__init__(self.message)


def code_for_status(status: int) -> str | None:
    """已知状态码映射；其余 4xx/5xx 交给调用方判断。"""
    return STATUS_CODES.get(status)


def to_fetch_error(exc: Exception) -> FetchError:
    """把 httpx 的异常翻译成 6 类错误码之一（M2 §6.2）。

    层级别搞错就会误报：`TimeoutException` 与 `ProxyError` 都是 `HTTPError` 的子类，
    所以必须先判超时，再把整个 `TransportError` 家族（连不上 / DNS / 代理 / 连接被重置）
    归到 `FETCH_DNS`——对用户而言都是"这个站点到不了"。
    detail 只放异常类型，不放原始消息 —— 部分 httpx 异常带请求头（红线 7）。
    """
    if isinstance(exc, httpx.TimeoutException):
        return FetchError("FETCH_TIMEOUT", detail=type(exc).__name__)
    if isinstance(exc, httpx.TransportError):
        return FetchError("FETCH_DNS", detail=type(exc).__name__)
    if isinstance(exc, httpx.HTTPError):
        # 协议层错误（重定向过多、响应体非法等）：不是超时也不可达，归到"不是网页"
        return FetchError("FETCH_INVALID", detail=type(exc).__name__)
    return FetchError("FETCH_INVALID", detail=type(exc).__name__)
