"""playwright 的机械动作 —— **主程序与 browser 组件共用这一份**。

为什么不放在 `app/services/`：组件是独立 exe，只带 playwright，**不能** import `app`
（那会把 fastapi / sqlite / trafilatura 一大坨拖进组件包，白加一百多兆）；而主程序在
冻结包里被 `excludes` 剔掉了 playwright。两边唯一能共用的是"只依赖 playwright +
标准库"的代码，所以它单独成一个顶层包 `shared`。

**两份副本是更糟的选择**：开发机走本进程（`browser.py`），装机版走组件（`components/
browser/entry.py`）。两边渲染参数一旦不一致，问题只会在装机版复现 —— 而装机版恰恰
是最难调试的地方。所以这里的原则是：**凡是要"动浏览器"的代码都写在这个文件里**，
上层只负责"从哪拿设置、往哪报状态"。

设置一律**当参数传**，不读 `app.config`：组件里没有那个模块。
"""
from __future__ import annotations

import json
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright  # noqa: F401 - 给调用方复用的入口

from shared.cookies import to_netscape  # noqa: F401 - 组件要用；主程序从 shared.cookies 直接取

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

NAV_TIMEOUT_MS = 25_000
SETTLE_ROUNDS = 8          # 可见文本连续两次不变视为渲染稳定，最多 8×300ms
SETTLE_STEP_MS = 300
LOGIN_POLL_S = 0.8


class BrowserUnavailable(RuntimeError):
    """没装 playwright / 没有可用浏览器 / 启动失败。调用方据此回落到原错误。"""


class BrowserTimeout(RuntimeError):
    """导航超时，或等不到目标 XHR。"""


def launch_context(p, *, user_data_dir: str, headless: bool, channel: str = ""):
    """优先用本机已装的 Edge/Chrome（零下载），失败再退回 playwright 自带 Chromium。"""
    common = {
        "user_data_dir": user_data_dir,
        "headless": headless,
        "locale": "zh-CN",
        "user_agent": UA,
        # 这个开关换掉 navigator.webdriver 的暴露，知乎这类站点会看
        "args": ["--disable-blink-features=AutomationControlled"],
        "viewport": {"width": 1440, "height": 900},
    }
    channel = (channel or "").strip()
    if channel:
        try:
            return p.chromium.launch_persistent_context(channel=channel, **common)
        except PlaywrightError:
            pass                          # 回落内置 Chromium
    try:
        return p.chromium.launch_persistent_context(**common)
    except PlaywrightError as exc:
        raise BrowserUnavailable(
            "没有可用的浏览器：请安装 Edge/Chrome，或执行 playwright install chromium"
        ) from exc


def settle(page) -> None:
    """等**可见文本**稳定，而不是等 HTML 稳定。

    知乎的 HTML 体积会一直变（推荐流、埋点上报），按 content() 判要跑满 4 秒；
    正文却 1 秒内就不动了。实测：inner_text 在 900ms 稳定、content() 要 1800ms。
    """
    last = -1
    for _ in range(SETTLE_ROUNDS):
        page.wait_for_timeout(SETTLE_STEP_MS)
        try:
            size = len(page.inner_text("body"))
        except PlaywrightError:
            continue
        if size > 0 and size == last:
            return
        last = size


def safe_close(ctx) -> None:
    try:
        ctx.close()
    except Exception:                   # noqa: BLE001 - 窗口已被用户关掉
        pass


def render(url: str, *, user_data_dir: str, headless: bool, channel: str = "",
           timeout_ms: int = NAV_TIMEOUT_MS) -> tuple[str, str, int]:
    """用真实浏览器打开 `url`，返回 `(html, 最终地址, HTTP 状态码)`。

    状态码可能是 403 而正文完整（知乎专栏就是），**判断成败要看正文，不要看码**，
    这件事交给调用方（`fetcher.BrowserFetcher`）。
    """
    try:
        with sync_playwright() as p:
            ctx = launch_context(p, user_data_dir=user_data_dir, headless=headless,
                                 channel=channel)
            try:
                page = ctx.new_page()
                try:
                    # domcontentloaded 就够：settle 负责等正文挂载完。
                    # 用 "commit"/"load" 都不合适：前者太早拿到空壳，后者被长连接拖死。
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except PlaywrightError as exc:
                    if "Timeout" in type(exc).__name__ or "Timeout" in str(exc):
                        raise BrowserTimeout(str(exc)[:120]) from exc
                    raise
                status = resp.status if resp is not None else 0
                settle(page)
                html = page.content()
                final = page.url
            finally:
                safe_close(ctx)
    except (BrowserUnavailable, BrowserTimeout):
        raise
    except PlaywrightError as exc:
        raise BrowserUnavailable(f"{type(exc).__name__}: {str(exc)[:120]}") from exc
    return html, final, status


def capture_json(url: str, *, contains: str, user_data_dir: str, headless: bool,
                 channel: str = "", timeout_ms: int = NAV_TIMEOUT_MS,
                 wait_ms: int = 12_000, min_bytes: int = 1000) -> tuple[dict, list[dict]]:
    """打开页面，截获**页面自己发出**的、URL 含 `contains` 的 JSON 响应。

    为什么不让 httpx 直接请求：抖音详情接口要 `a_bogus` 签名，签名算在页面自己的
    JS 里，外部复现不了；用页面自己去请求，我们只在旁边听结果，就不用逆向签名。

    返回 `(json, cookies)`。`cookies` 给调用方下载媒体用（部分 CDN 会校验）。
    """
    found: dict = {}

    def _on_response(resp) -> None:
        if found or contains not in resp.url:
            return
        try:
            if resp.status != 200:
                return
            body = resp.text()
        except Exception:               # noqa: BLE001 - 响应体可能已被丢弃
            return
        if len(body) < min_bytes:
            # 抖音缺签名时返回 200 + 空体，别把它当成成功
            return
        try:
            found["json"] = json.loads(body)
        except ValueError:
            return

    try:
        with sync_playwright() as p:
            ctx = launch_context(p, user_data_dir=user_data_dir, headless=headless,
                                 channel=channel)
            try:
                page = ctx.new_page()
                page.on("response", _on_response)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except PlaywrightError as exc:
                    if "Timeout" in type(exc).__name__ or "Timeout" in str(exc):
                        raise BrowserTimeout(str(exc)[:120]) from exc
                    raise
                for _ in range(max(1, wait_ms // 500)):
                    if found:
                        break
                    page.wait_for_timeout(500)
                cookies = ctx.cookies()
            finally:
                safe_close(ctx)
    except (BrowserUnavailable, BrowserTimeout):
        raise
    except PlaywrightError as exc:
        raise BrowserUnavailable(f"{type(exc).__name__}: {str(exc)[:120]}") from exc

    if not found:
        raise BrowserTimeout(f"等 {wait_ms // 1000} 秒没等到 {contains} 的响应")
    return found["json"], cookies


def open_for_login(login_url: str, markers, *, user_data_dir: str, channel: str = "",
                   timeout_s: int = 300, cancelled=None, on_tick=None) -> list[dict]:
    """弹一个**可见**窗口让用户登录，轮询 cookie 里的标记项。

    `cancelled()` 返回 True 就放弃（主程序通过一个哨兵文件实现，见 `browser.py`）；
    `on_tick(now)` 每轮调一次，用来把"还在等你"报到界面上。
    窗口被用户关掉时立刻返回空列表，不傻等 5 分钟。
    """
    with sync_playwright() as p:
        ctx = launch_context(p, user_data_dir=user_data_dir, headless=False,
                             channel=channel)
        try:
            page = ctx.new_page()
            page.goto(login_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                if cancelled and cancelled():
                    return []
                if on_tick:
                    on_tick(time.time())
                try:
                    cookies = ctx.cookies()
                except PlaywrightError:
                    return []
                if any((c.get("name") or "") in markers for c in cookies):
                    time.sleep(1.0)
                    return cookies
                time.sleep(LOGIN_POLL_S)
            return []
        finally:
            safe_close(ctx)
