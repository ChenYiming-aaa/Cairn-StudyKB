"""网页抓取 adapter（T2.1）。

约束（M2 §1.1）：路由与 service 都不许直接 import trafilatura，一律走 `BaseFetcher`，
以后换 readability / 换 headless 渲染只改一个实现类。

为什么不用 `trafilatura.fetch_url`（M2 §6.1）：它内部用自己的 urllib，
超时与 UA 不好控制；这里统一用 httpx，异常也能落到 6 类错误码。

三层结构（2026-11-06 加后两层）：
- `TrafilaturaFetcher`：httpx 取 HTML，几十毫秒，绝大多数站点走这条
- `BrowserFetcher`：真实浏览器渲染，2–4 秒，专治指纹拦截与动态渲染
- `BrowserFallbackFetcher`：先前者，只在"像是被拦/没渲染"的错上换后者
"""
from __future__ import annotations

import inspect
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx
import trafilatura

from app.services import browser
from app.services.fetch_errors import FetchError, code_for_status, to_fetch_error

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 30.0
MIN_TEXT_CHARS = 200          # 正文短于此判 FETCH_EMPTY（M2 §6.2）
MAX_TITLE_CHARS = 100

# 这些错换浏览器还有救：BLOCKED 是被反爬拦下，EMPTY 多半是 JS 没执行。
# 超时/DNS/404/非网页换浏览器也白搭，白白把 30 秒拖成 60 秒。
BROWSER_FALLBACK_CODES = frozenset({"FETCH_BLOCKED", "FETCH_EMPTY"})



@dataclass(frozen=True)
class FetchedPage:
    """一次成功抓取的结果。标题可能为空串，调用方自己兜底。"""

    url: str                  # 跟随重定向后的最终地址，用于查重
    title: str
    text: str


class BaseFetcher(ABC):
    @abstractmethod
    def fetch(self, url: str) -> FetchedPage:
        """抓取并抽取正文；失败一律抛 FetchError（带 code）。"""


def normalize_url(raw: str) -> str:
    """去空白、补协议、去掉 fragment。补协议是为了让用户能直接粘 `example.com/a`。"""
    url = (raw or "").strip()
    if not url:
        raise FetchError("URL_INVALID", detail="空链接")
    if "://" not in url:
        url = "https://" + url.lstrip("/")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise FetchError("URL_INVALID", detail=f"scheme={parsed.scheme or '无'}")
    if not parsed.netloc or "." not in parsed.netloc:
        raise FetchError("URL_INVALID", detail=f"netloc={parsed.netloc or '无'}")
    return urlunparse(parsed._replace(fragment=""))


def _extract_kwargs() -> dict:
    """按装到的 trafilatura 版本挑参数。

    1.x 有 `include_tables`，2.0 起表格恒包含、该参数被删，写死会 TypeError。
    只在 import 时算一次。
    """
    params = inspect.signature(trafilatura.extract).parameters
    kwargs: dict = {"include_comments": False, "favor_recall": True, "output_format": "txt"}
    if "include_tables" in params:
        kwargs["include_tables"] = True
    return kwargs


_EXTRACT_KWARGS = _extract_kwargs()


def _pick_title(page_url: str, meta_title: str | None, text: str) -> str:
    """标题优先级：页面 <title> → 正文首个非空行 → 域名。统一截断，避免撑爆左树。"""
    title = (meta_title or "").strip()
    if not title:
        for line in text.splitlines():
            if line.strip():
                title = line.strip()
                break
    if not title:
        title = urlparse(page_url).netloc or "未命名网页"
    return title[:MAX_TITLE_CHARS]


def _build_page(final_url: str, html: str, status: int) -> FetchedPage:
    """从 HTML 造 FetchedPage。**先看正文、再看状态码**。

    知乎专栏页返回 403，响应体却有 431KB、抽得出 3184 字正文；照旧在
    `code_for_status(403)` 就抛，等于把到手的正文扔了。所以顺序必须是：
    404/410 先排除（那是真没页面），其余情况正文够长就用，不够才按状态码报错。
    """
    if status in (404, 410):
        raise FetchError("FETCH_NOT_FOUND", detail=f"HTTP {status}")

    text = (trafilatura.extract(html, **_EXTRACT_KWARGS) or "").strip()
    if len(text) < MIN_TEXT_CHARS:
        code = code_for_status(status)
        if code:
            raise FetchError(code, detail=f"HTTP {status}")
        if status >= 400:
            # 未登记的 4xx/5xx + 正文不足 = 反爬挑战页或服务端异常页。
            # 典型：CSDN 对无 cookie 请求回 521 + 一段 `setTimeout("fy(45)")` 的 JS 挑战页，
            # 2348 字节、正文 0 字（2026-11-07 实测）。
            # 必须归 BLOCKED 而不是 INVALID：INVALID 专指 content-type 非 HTML（见 `_get`），
            # 归错会让前端说成"该链接不是网页"，还会错过浏览器降级——真浏览器能解开挑战页。
            raise FetchError("FETCH_BLOCKED", detail=f"HTTP {status}")
        raise FetchError("FETCH_EMPTY", detail=f"仅 {len(text)} 字")

    meta = trafilatura.extract_metadata(html)
    title = _pick_title(final_url, getattr(meta, "title", None), text)
    return FetchedPage(url=final_url, title=title, text=text)


class TrafilaturaFetcher(BaseFetcher):
    """httpx 取页面 + trafilatura 抽正文。同步实现：路由用 def，FastAPI 丢线程池。"""

    def __init__(self, timeout: float = TIMEOUT):
        self.timeout = timeout

    def fetch(self, url: str) -> FetchedPage:
        url = normalize_url(url)
        html, final_url, status = self._get(url)
        return _build_page(final_url, html, status)

    def _get(self, url: str) -> tuple[str, str, int]:
        """返回 (html, 最终地址, 状态码)。**不在这里判状态码**，交给 `_build_page`。

        登录助手导出的 cookie 顺手带上：对"登录后才给正文"的站点有用。
        但别指望它解决知乎那类指纹拦截 —— 带 cookie 依然 584 字节空壳。
        """
        headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
        if (cookies := browser.cookies_for(url)):
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())

        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self.timeout,
                headers=headers,
            ) as client:
                resp = client.get(url)
        except Exception as exc:                    # noqa: BLE001 - 统一翻译成 6 类错误码
            raise to_fetch_error(exc) from exc

        ctype = (resp.headers.get("content-type") or "").lower()
        # 头部完全缺失时不拦（部分站点/反代不返回），交给后面 200 字阈值判空
        if ctype and "html" not in ctype:
            raise FetchError("FETCH_INVALID", detail=f"content-type={ctype}")

        return resp.text, str(resp.url), resp.status_code


class BrowserFetcher(BaseFetcher):
    """真实浏览器渲染后抽正文。用于指纹拦截与纯 JS 渲染的站点。

    代价是每次 2–4 秒并起一个浏览器进程，所以不单独使用，挂在 Fallback 后面。
    """

    def __init__(self, headless: bool | None = None):
        self.headless = headless

    def fetch(self, url: str) -> FetchedPage:
        url = normalize_url(url)
        try:
            html, final_url, status = browser.render(url, headless=self.headless)
        except browser.BrowserTimeout as exc:
            raise FetchError("FETCH_TIMEOUT", detail=str(exc)[:120]) from exc
        except browser.BrowserUnavailable as exc:
            # 环境问题不能甩锅给目标站点，单列一个码，文案指向"装浏览器"
            raise FetchError("FETCH_BROWSER_UNAVAILABLE", detail=str(exc)[:120]) from exc
        return _build_page(final_url, html, status)


class BrowserFallbackFetcher(BaseFetcher):
    """先 httpx，只在"像被拦/没渲染"的错上换真浏览器。"""

    def __init__(self, primary: BaseFetcher | None = None,
                 fallback: BaseFetcher | None = None):
        self.primary = primary or TrafilaturaFetcher()
        self.fallback = fallback or BrowserFetcher()

    def fetch(self, url: str) -> FetchedPage:
        try:
            return self.primary.fetch(url)
        except FetchError as exc:
            if exc.code not in BROWSER_FALLBACK_CODES or not browser.available():
                raise
            log.info("httpx 采集失败（%s），改用浏览器渲染：%s", exc.code, url)
            try:
                page = self.fallback.fetch(url)
            except FetchError as browser_exc:
                # 两边都失败时挑信息量大的那个报：浏览器说"被拦/要登录"比
                # httpx 的"没抽到正文"更能指向真实原因（指纹 vs 真的没内容）
                if browser_exc.code in ("FETCH_BLOCKED", "FETCH_LOGIN_REQUIRED",
                                        "FETCH_BROWSER_UNAVAILABLE"):
                    raise browser_exc from exc
                raise exc from browser_exc
            log.info("浏览器渲染成功，%s 字", len(page.text))
            return page



_default_fetcher: BaseFetcher | None = None


def get_fetcher() -> BaseFetcher:
    """单例入口；测试里替换实现只需改这个模块的 `_default_fetcher`。

    默认是 `BrowserFallbackFetcher`：正常站点走的还是 httpx，浏览器只在失败时登场，
    所以这里换实现不会拖慢任何一条现有路径。
    """
    global _default_fetcher
    if _default_fetcher is None:
        _default_fetcher = BrowserFallbackFetcher()
    return _default_fetcher


def set_fetcher(fetcher: BaseFetcher | None) -> None:
    """给 verify 脚本 / 单测注入假实现（T2.10 的三种失败场景靠它）。"""
    global _default_fetcher
    _default_fetcher = fetcher
