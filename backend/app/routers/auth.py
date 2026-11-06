"""站点登录（L3）：弹一个受控浏览器窗口让用户登录，登录态导出给采集链路复用。

为什么不是"跳转到系统浏览器登录再回读 cookie"（2026-11-06 实测结论）：
- Chrome 127+ 的 App-Bound Encryption 解不开、Edge 的 cookie 库被锁，读不出来
- 知乎没有面向第三方的开放平台、B 站开放平台要企业资质，也没有 code 可换

所以唯一可行的是自己维护一个 profile（`services/browser.py`），
登录结果落成 cookies.txt，同时喂给两条链路：yt-dlp 拿字幕、httpx 带 cookie。

登录是长操作（等人手动扫码/输密码，最长 5 分钟），因此：
`POST` 立刻返回，前端轮询 `GET /api/auth/status` 看 `login.status`。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.errors import error_payload
from app.services import browser

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def auth_status() -> dict:
    """各站点登录态 + 当前登录任务进度。只读 cookies.txt，不启动浏览器，可以频繁轮询。"""
    return browser.status()


@router.post("/login/{site}")
def auth_login(site: str):
    """起一个后台登录窗口，立即返回。`site` 取 `/api/auth/status` 里的键（bilibili/zhihu）。"""
    if site not in browser.SITES:
        return JSONResponse(
            status_code=404,
            content=error_payload("SITE_UNKNOWN", "暂不支持该站点的登录", site),
        )
    return browser.start_login(site)
