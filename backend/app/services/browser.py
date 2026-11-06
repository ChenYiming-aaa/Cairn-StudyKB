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

**线程模型**：Playwright 的 sync API 不是线程安全的，且同一个 user_data_dir
同时只能被一个实例打开。所有浏览器操作都用 `_pw_lock` 串行化：任务池只有 2 个
worker，一次渲染 2–4 秒，排队可接受。登录会长时间占锁（默认最长 5 分钟），
这是用户主动触发的低频操作，同样可接受。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings

log = logging.getLogger(__name__)

# 未安装 playwright 时整站要能照常启动，只是浏览器能力不可用
try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except Exception:                       # noqa: BLE001 - 缺包/缺驱动都归到不可用
    sync_playwright = None
    PlaywrightError = Exception         # type: ignore[assignment,misc]
    PLAYWRIGHT_AVAILABLE = False

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

NAV_TIMEOUT_MS = 25_000
SETTLE_ROUNDS = 8          # 可见文本连续两次不变视为渲染稳定，最多 8×300ms
SETTLE_STEP_MS = 300
LOGIN_TIMEOUT = 300        # 用户手动登录，给足 5 分钟
PROFILE_DIRNAME = "browser"
COOKIE_FILENAME = "cookies.txt"


class BrowserUnavailable(RuntimeError):
    """没装 playwright / 没有可用浏览器 / 启动失败。调用方据此回落到原错误。"""


class BrowserTimeout(RuntimeError):
    """导航超时。"""


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

_pw_lock = threading.Lock()
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


# ── cookie 读写 ─────────────────────────────────────────────

def _to_netscape(cookies: list[dict]) -> str:
    """Playwright 的 cookie 列表 → Netscape cookies.txt（yt-dlp / curl 通用格式）。

    HttpOnly 的 cookie 必须加 `#HttpOnly_` 前缀，否则 MozillaCookieJar 会把整行
    当注释跳过。B 站的 SESSDATA 正是 HttpOnly —— 漏了这个前缀，文件看着正常，
    yt-dlp 却当未登录，这个坑很隐蔽。
    """
    lines = ["# Netscape HTTP Cookie File", "# 由 Cairn 登录助手导出", ""]
    for c in cookies:
        domain = (c.get("domain") or "").strip()
        name = (c.get("name") or "").strip()
        if not domain or not name:
            continue
        expires = int(c.get("expires") or 0)
        if expires <= 0:
            expires = 0                  # 会话 cookie：0 是 Netscape 的约定
        prefix = "#HttpOnly_" if c.get("httpOnly") else ""
        lines.append("\t".join([
            prefix + domain,
            "TRUE" if domain.startswith(".") else "FALSE",
            c.get("path") or "/",
            "TRUE" if c.get("secure") else "FALSE",
            str(expires),
            name,
            c.get("value") or "",
        ]))
    return "\n".join(lines) + "\n"


def _read_cookie_names() -> set[str]:
    """只读文件名，不启动浏览器 —— 状态查询要快。"""
    path = cookie_file()
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names: set[str] = set()
    for line in text.splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            names.add(parts[5].strip())
    return names


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


# ── 启动 ────────────────────────────────────────────────────

def _launch_context(p, headless: bool):
    """优先用本机已装的 Edge/Chrome（零下载），失败再退回 playwright 自带 Chromium。"""
    cfg = get_settings()
    profile = profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    common = {
        "user_data_dir": str(profile),
        "headless": headless,
        "locale": "zh-CN",
        "user_agent": UA,
        # 这个开关换掉 navigator.webdriver 的暴露，知乎这类站点会看
        "args": ["--disable-blink-features=AutomationControlled"],
        "viewport": {"width": 1440, "height": 900},
    }
    channel = (cfg.browser_channel or "").strip()
    if channel:
        try:
            return p.chromium.launch_persistent_context(channel=channel, **common)
        except PlaywrightError as exc:
            log.warning("浏览器通道 %s 启动失败（%s），回落到内置 Chromium",
                        channel, type(exc).__name__)
    try:
        return p.chromium.launch_persistent_context(**common)
    except PlaywrightError as exc:
        raise BrowserUnavailable(
            "没有可用的浏览器：请安装 Edge/Chrome，或执行 playwright install chromium"
        ) from exc


def _settle(page) -> None:
    """等**可见文本**稳定，而不是等 HTML 稳定。

    知乎的 HTML 体积会一直变（推荐流、埋点上报），按 content() 判要跑满 4 秒；
    正文却 1 秒内就不动了。实测：inner_text 在 900ms 稳定、content() 要 1800ms，
    而且 inner_text 单次 21–170ms，content() 要 400ms+。
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


def _safe_close(ctx) -> None:
    try:
        ctx.close()
    except Exception:                   # noqa: BLE001 - 窗口已被用户关掉
        pass


def available() -> bool:
    return PLAYWRIGHT_AVAILABLE


# ── 渲染 ────────────────────────────────────────────────────

def render(url: str, *, headless: bool | None = None,
           timeout_ms: int = NAV_TIMEOUT_MS) -> tuple[str, str, int]:
    """用真实浏览器打开 `url`，返回 `(html, 最终地址, HTTP 状态码)`。

    状态码可能是 403 而正文完整（知乎专栏就是），**判断成败要看正文，不要看码**，
    这件事交给调用方（`fetcher.BrowserFetcher`）。
    """
    if not PLAYWRIGHT_AVAILABLE:
        raise BrowserUnavailable("未安装 playwright")
    want_headless = get_settings().browser_headless if headless is None else headless

    with _pw_lock:
        try:
            with sync_playwright() as p:
                ctx = _launch_context(p, want_headless)
                try:
                    page = ctx.new_page()
                    try:
                        # domcontentloaded 就够：_settle 负责等正文挂载完。
                        # 用 "commit"/"load" 都不合适：前者太早拿到空壳，后者被长连接拖死。
                        resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    except PlaywrightError as exc:
                        if "Timeout" in type(exc).__name__ or "Timeout" in str(exc):
                            raise BrowserTimeout(str(exc)[:120]) from exc
                        raise
                    status = resp.status if resp is not None else 0
                    _settle(page)
                    html = page.content()
                    final = page.url
                finally:
                    _safe_close(ctx)
        except (BrowserUnavailable, BrowserTimeout):
            raise
        except PlaywrightError as exc:
            raise BrowserUnavailable(f"{type(exc).__name__}: {str(exc)[:120]}") from exc
    return html, final, status


# ── 登录 ────────────────────────────────────────────────────

def login_state() -> dict:
    return dict(_login_state)


def _set_state(status: str, site: str = "", message: str = "") -> None:
    _login_state.update({"status": status, "site": site, "message": message})


def _await_login(ctx, spec: SiteSpec) -> bool:
    """轮询 cookie 等用户把登录做完。窗口被关掉就立刻返回 False。"""
    deadline = time.time() + LOGIN_TIMEOUT
    while time.time() < deadline:
        if _login_cancel.is_set():
            return False
        try:
            cookies = ctx.cookies()
        except PlaywrightError:
            return False                # 用户把窗口关了
        if any((c.get("name") or "") in spec.markers for c in cookies):
            # 有些站点登录后几秒内才补齐其余 cookie，多等一下再整体导出
            time.sleep(1.0)
            return True
        time.sleep(0.8)
    return False


def _login_worker(spec: SiteSpec) -> None:
    ok = False
    cookies: list[dict] = []
    try:
        with _pw_lock:
            with sync_playwright() as p:
                ctx = _launch_context(p, headless=False)
                try:
                    page = ctx.new_page()
                    page.goto(spec.login_url, wait_until="domcontentloaded",
                              timeout=NAV_TIMEOUT_MS)
                    ok = _await_login(ctx, spec)
                    cookies = ctx.cookies() if ok else []
                finally:
                    _safe_close(ctx)
    except Exception as exc:            # noqa: BLE001 - 线程里必须自己收口
        log.warning("登录 %s 失败：%s", spec.key, type(exc).__name__)
        _set_state("failed", spec.key, "无法打开登录窗口，请检查浏览器是否可用")
        return

    if not ok:
        _set_state("failed", spec.key, "登录超时或窗口已关闭，可以再试一次")
        return

    path = cookie_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_to_netscape(cookies), encoding="utf-8")
    except OSError:
        _set_state("failed", spec.key, "登录成功但写入 cookie 文件失败，请检查目录权限")
        return
    # 只记站点与条数，cookie 内容一律不进日志（红线 7）
    log.info("已登录 %s，导出 %s 条 cookie 到 %s", spec.label, len(cookies), path)
    _set_state("success", spec.key, f"已登录{spec.label}，字幕与受限页面将自动启用")


def start_login(site_key: str) -> dict:
    """起一个后台线程弹窗登录，立刻返回。前端轮询 `status()` 看结果。"""
    spec = SITES.get(site_key)
    if spec is None:
        raise KeyError(site_key)
    if not PLAYWRIGHT_AVAILABLE:
        _set_state("failed", site_key, "未安装 playwright，无法打开登录窗口")
        return login_state()
    if _login_state.get("status") == "running":
        # 同一时间只允许一个登录窗口：profile 被两个实例打开会直接崩
        return login_state()

    _login_cancel.clear()
    _set_state("running", site_key, f"请在弹出的窗口里登录{spec.label}")
    threading.Thread(target=_login_worker, args=(spec,), name=f"cairn-login-{site_key}",
                     daemon=True).start()
    return login_state()


def cancel_login() -> None:
    _login_cancel.set()


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
        "browser_available": PLAYWRIGHT_AVAILABLE,
        "cookie_file": str(path) if path.exists() else "",
        "sites": sites,
        "login": login_state(),
    }
