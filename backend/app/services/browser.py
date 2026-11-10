"""浏览器会话：登录态、页面渲染、cookie 导出。

**为什么需要这个模块**（2026-11-06 实测，不是推测）：

1. 知乎专栏页对 httpx 返回 403 + **584 字节空壳**；把 UA、Accept、Referer、
   sec-ch-ua、Sec-Fetch-* 全部伪装成真实 Chrome，结果**一模一样**。同一个 URL
   用真实浏览器打开还是 403，但响应体 **431KB**，抽得出 3184 字正文。
   → 拦的是 TLS/指纹层，不是登录态。往 httpx 里塞 cookie 解决不了。
2. B 站字幕要登录态。系统浏览器的 cookie 读不出来（Chrome 127+ 的
   App-Bound Encryption 解不开、Edge 的库被锁，`transcriber.py` 里已记过）。
   → 只能自己维护一个 profile，登录态存在里面。

所以「跳转到系统浏览器登录、事后回读 cookie」和「OAuth 式回调」都走不通，
唯一可行的路是**弹一个我们自己控制的浏览器窗口**让用户在里面登录：
后端跑在用户本机，弹窗天然成立；登录态落在 `data/browser/` 这个独立 profile 里，
既能导出成 cookies.txt 喂 yt-dlp，又能直接用来渲染页面 —— 登录和渲染是同一套东西。

**M8 起这份文件只做"调度"**：真正动浏览器的代码在 `shared/browser_pw.py`，
主程序和 browser 组件共用那一份（理由见该文件顶部）。这里负责三件事：
从设置里取参数、决定走本进程还是组件管道、把状态报给界面。

**线程模型**：Playwright 的 sync API 不是线程安全的，且同一个 user_data_dir
同时只能被一个实例打开。**本进程模式**用 `_pw_lock` 串行化（任务池只有 2 个 worker，
一次渲染 2–4 秒，排队可接受）；**组件模式**天然串行（组件一个进程一次一条请求）。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.services import components
from shared.cookies import cookie_names as _cookie_names
from shared.cookies import to_netscape as _to_netscape

log = logging.getLogger(__name__)

# 未安装 playwright 时整站要能照常启动，只是浏览器能力不可用。
# 冻结包里 playwright 在 excludes 里 → 这个 import 必失败 → 自动落到组件（如果有）
try:
    from shared.browser_pw import (           # noqa: F401
        NAV_TIMEOUT_MS,
        BrowserTimeout,
        BrowserUnavailable,
        UA,
        capture_json as _pw_capture_json,
        open_for_login,
        render as _pw_render,
    )

    PLAYWRIGHT_AVAILABLE = True
except Exception:                       # noqa: BLE001 - 缺包/缺驱动都归到不可用
    PLAYWRIGHT_AVAILABLE = False
    NAV_TIMEOUT_MS = 25_000
    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    class BrowserUnavailable(RuntimeError):
        """没装 playwright / 没有可用浏览器 / 启动失败。调用方据此回落到原错误。"""

    class BrowserTimeout(RuntimeError):
        """导航超时。"""


LOGIN_TIMEOUT = 300        # 用户手动登录，给足 5 分钟
PROFILE_DIRNAME = "browser"
COOKIE_FILENAME = "cookies.txt"
CANCEL_FILENAME = "browser-login.cancel"   # 组件模式下的"取消"哨兵（跨进程只能靠文件）


@dataclass(frozen=True)
class SiteSpec:
    """一个需要登录的站点。`markers` 是登录成功后才会出现的 cookie 名。"""

    key: str
    label: str
    login_url: str
    markers: tuple[str, ...]


# 知乎匿名访问也会发 d_c0 等 cookie，只有 z_c0 代表真正登录，别拿错判据
SITES: dict[str, SiteSpec] = {
    "bilibili": SiteSpec("bilibili", "B 站",
                         "https://passport.bilibili.com/login", ("SESSDATA",)),
    "zhihu": SiteSpec("zhihu", "知乎",
                      "https://www.zhihu.com/signin", ("z_c0",)),
}

_pw_lock = threading.Lock()          # 本进程模式串行化
_login_cancel = threading.Event()
_login_state: dict = {"status": "idle", "site": "", "message": ""}


# ── 路径 ────────────────────────────────────────────────────

def profile_dir() -> Path:
    """独立的浏览器 profile。**不要**指向用户日常浏览器的目录。"""
    return get_settings().data_dir / PROFILE_DIRNAME


def cookie_file() -> Path:
    """cookies.txt 的落点：配了 YTDLP_COOKIES 就用它，否则用 data/cookies.txt。

    导出到这里等于同时满足两个消费方 —— yt-dlp 直接读文件，
    网页抓取从同一份文件构造 Cookie 头。
    """
    configured = get_settings().ytdlp_cookies.strip()
    if configured:
        return Path(configured).expanduser()
    return get_settings().data_dir / COOKIE_FILENAME


def _cancel_file() -> Path:
    path = get_settings().data_dir / "tmp" / CANCEL_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ── cookie 读 ───────────────────────────────────────────────

def _read_cookie_names() -> set[str]:
    """只读文件名，不启动浏览器 —— 状态查询要快。"""
    return _cookie_names(cookie_file())


def cookies_for(url: str) -> dict[str, str]:
    """从导出的 cookies.txt 里挑出适用于该 URL 的 cookie，供 httpx 使用。

    只是"顺手带上"，不指望它解决反爬：知乎那类站点拦的是指纹，带 cookie
    依然是空壳。真正救场的是 `render()`。
    """
    path = cookie_file()
    if not path.exists():
        return {}
    host = ""
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
    except Exception:                   # noqa: BLE001
        return {}
    if not host:
        return {}
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    for line in text.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain = parts[0].removeprefix("#HttpOnly_").lstrip(".").lower()
        if host == domain or host.endswith("." + domain):
            out[parts[5].strip()] = parts[6].strip()
    return out


# ── 跑哪一种 ────────────────────────────────────────────────

def _mode() -> str | None:
    """`"component"` / `"local"` / `None`。判定顺序见 `components.resolve`。"""
    return components.resolve("browser")


def available() -> bool:
    """有任何一条路能开浏览器就算可用。

    源码运行看本进程（`PLAYWRIGHT_AVAILABLE`）；装机版本进程一定没有 playwright，
    但装了组件就还是可用 —— 少了这一条，设置页会永远显示"不可用"。
    """
    return PLAYWRIGHT_AVAILABLE or _mode() == "component"


def _launch_kwargs() -> dict:
    cfg = get_settings()
    return {"user_data_dir": str(profile_dir()), "channel": cfg.browser_channel}


# ── 渲染 ────────────────────────────────────────────────────

def render(url: str, *, headless: bool | None = None,
           timeout_ms: int = NAV_TIMEOUT_MS) -> tuple[str, str, int]:
    """用真实浏览器打开 `url`，返回 `(html, 最终地址, HTTP 状态码)`。

    状态码可能是 403 而正文完整（知乎专栏就是），**判断成败要看正文，不要看码**，
    这件事交给调用方（`fetcher.BrowserFetcher`）。
    """
    mode = _mode()
    want_headless = get_settings().browser_headless if headless is None else headless

    if mode == "component":
        reply = _call("render", {"url": url, "headless": want_headless,
                                 "timeout_ms": timeout_ms, **_launch_kwargs()},
                      timeout=timeout_ms / 1000 + 60)
        return str(reply.get("html") or ""), str(reply.get("final_url") or url), \
            int(reply.get("status") or 0)

    if mode == "local":
        with _pw_lock:
            return _pw_render(url, headless=want_headless, timeout_ms=timeout_ms,
                              **_launch_kwargs())
    raise BrowserUnavailable("网页渲染组件还没装")


# ── 截获页面自己的 XHR ──────────────────────────────────────

def capture_json(url: str, *, contains: str, headless: bool | None = None,
                 timeout_ms: int = NAV_TIMEOUT_MS, wait_ms: int = 12_000,
                 min_bytes: int = 1000) -> tuple[dict, list[dict]]:
    """打开页面，截获**页面自己发出**的、URL 含 `contains` 的 JSON 响应。

    为什么不让 httpx 直接请求：抖音详情接口要 `a_bogus` 签名，签名算在页面自己的
    JS 里，外部复现不了；用页面自己去请求，我们只在旁边听结果，就不用逆向签名。

    返回 `(json, cookies)`。`cookies` 给调用方下载媒体用（部分 CDN 会校验）。
    """
    mode = _mode()
    want_headless = get_settings().browser_headless if headless is None else headless

    if mode == "component":
        reply = _call("capture_json",
                      {"url": url, "contains": contains, "headless": want_headless,
                       "timeout_ms": timeout_ms, "wait_ms": wait_ms,
                       "min_bytes": min_bytes, **_launch_kwargs()},
                      timeout=(timeout_ms + wait_ms) / 1000 + 60)
        data = reply.get("json")
        if not isinstance(data, dict):
            raise BrowserTimeout("组件没截到目标响应")
        return data, list(reply.get("cookies") or [])

    if mode == "local":
        with _pw_lock:
            return _pw_capture_json(url, contains=contains, headless=want_headless,
                                    timeout_ms=timeout_ms, wait_ms=wait_ms,
                                    min_bytes=min_bytes, **_launch_kwargs())
    raise BrowserUnavailable("网页渲染组件还没装")


def _call(op: str, payload: dict, *, timeout: float) -> dict:
    """走组件管道，把组件的错误翻成调用方认识的两种异常。

    `fetcher.py` 只 catch `BrowserUnavailable` / `BrowserTimeout` 来决定"要不要回落
    到 httpx 并给用户一句人话"；让 `ComponentError` 直接冒出去的话，一个没装组件的
    机器会把整次采集当成"未知错误"。
    """
    try:
        return components.call("browser", op, payload, timeout=timeout)
    except components.ComponentError as exc:
        if exc.code in ("COMPONENT_MISSING",):
            raise BrowserUnavailable(exc.message) from exc
        if "Timeout" in (exc.detail or "") or "超时" in exc.message:
            raise BrowserTimeout(exc.message) from exc
        raise BrowserUnavailable(exc.message) from exc


# ── 登录 ────────────────────────────────────────────────────

def login_state() -> dict:
    return dict(_login_state)


def _set_state(status: str, site: str = "", message: str = "") -> None:
    _login_state.update({"status": status, "site": site, "message": message})


def _write_cookies(cookies: list[dict]) -> bool:
    path = cookie_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_to_netscape(cookies), encoding="utf-8")
        return True
    except OSError:
        return False


def _login_local(spec: SiteSpec) -> None:
    """本进程模式：起自己的浏览器窗口，轮询 cookie。"""
    def cancelled() -> bool:
        return _login_cancel.is_set()

    try:
        with _pw_lock:
            cookies = open_for_login(spec.login_url, spec.markers,
                                     timeout_s=LOGIN_TIMEOUT, cancelled=cancelled,
                                     **_launch_kwargs())
    except Exception as exc:            # noqa: BLE001 - 线程里必须自己收口
        log.warning("登录 %s 失败：%s", spec.key, type(exc).__name__)
        _set_state("failed", spec.key, "无法打开登录窗口，请检查浏览器是否可用")
        return
    _finish_login(spec, cookies)


def _login_remote(spec: SiteSpec) -> None:
    """组件模式：窗口开在组件进程里（跨管道开不了可见窗口，见 M8 补充记录 S-3）。"""
    cancel = _cancel_file()
    try:
        cancel.unlink(missing_ok=True)
    except OSError:
        pass
    payload = {"login_url": spec.login_url, "markers": list(spec.markers),
               "cookie_file": str(cookie_file()), "cancel_file": str(cancel),
               "timeout_s": LOGIN_TIMEOUT, **_launch_kwargs()}
    try:
        # 空闲超时 30s：组件每轮都会报一次 progress，真卡住才判死
        reply = components.call("browser", "login", payload, timeout=30, idle=True)
    except components.ComponentError as exc:
        log.warning("登录 %s 失败：%s", spec.key, exc.code)
        _set_state("failed", spec.key, "登录窗口没能打开，可以再试一次")
        return
    finally:
        try:
            cancel.unlink(missing_ok=True)
        except OSError:
            pass

    if reply.get("cancelled"):
        _set_state("failed", spec.key, "已取消登录")
        return
    count = int(reply.get("cookies") or 0)
    if not count:
        _set_state("failed", spec.key, "登录超时或窗口已关闭，可以再试一次")
        return
    # 组件已经写好了 cookie 文件，这里只报结果（不重复写，免得两边格式不一致）
    log.info("已登录 %s，导出 %s 条 cookie 到 %s", spec.label, count, cookie_file())
    _set_state("success", spec.key, f"已登录{spec.label}，字幕与受限页面将自动启用")


def _finish_login(spec: SiteSpec, cookies: list[dict]) -> None:
    if not cookies:
        _set_state("failed", spec.key, "登录超时或窗口已关闭，可以再试一次")
        return
    if not _write_cookies(cookies):
        _set_state("failed", spec.key, "登录成功但写入 cookie 文件失败，请检查目录权限")
        return
    # 只记站点与条数，cookie 内容一律不进日志（红线 7）
    log.info("已登录 %s，导出 %s 条 cookie 到 %s", spec.label, len(cookies), cookie_file())
    _set_state("success", spec.key, f"已登录{spec.label}，字幕与受限页面将自动启用")


def start_login(site_key: str) -> dict:
    """起一个后台线程弹窗登录，立刻返回。前端轮询 `status()` 看结果。"""
    spec = SITES.get(site_key)
    if spec is None:
        raise KeyError(site_key)
    if not available():
        _set_state("failed", site_key, "网页渲染组件还没装，装好后才能登录")
        return login_state()
    if _login_state.get("status") == "running":
        # 同一时间只允许一个登录窗口：profile 被两个实例打开会直接崩
        return login_state()

    _login_cancel.clear()
    _set_state("running", site_key, f"请在弹出的窗口里登录{spec.label}")
    target = _login_remote if _mode() == "component" else _login_local
    threading.Thread(target=target, args=(spec,), name=f"cairn-login-{site_key}",
                     daemon=True).start()
    return login_state()


def cancel_login() -> None:
    """两个模式各一条路：本进程置事件，组件模式留一个哨兵文件。"""
    _login_cancel.set()
    try:
        _cancel_file().write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def shutdown() -> None:
    """进程退出时让登录线程尽快收手，避免留下孤立的浏览器窗口。"""
    _login_cancel.set()


# ── 状态 ────────────────────────────────────────────────────

def status() -> dict:
    names = _read_cookie_names()
    sites = {
        key: {
            "label": spec.label,
            "logged_in": any(m in names for m in spec.markers),
        }
        for key, spec in SITES.items()
    }
    path = cookie_file()
    return {
        "browser_available": available(),
        "cookie_file": str(path) if path.exists() else "",
        "sites": sites,
        "login": login_state(),
    }
