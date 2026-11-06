"""网页抓取 adapter（T2.1）。

约束（M2 §1.1）：路由与 service 都不许直接 import trafilatura，一律走 `BaseFetcher`，
以后换 readability / 换 headless 渲染只改一个实现类。

为什么不用 `trafilatura.fetch_url`（M2 §6.1）：它内部用自己的 urllib，
超时与 UA 不好控制；这里统一用 httpx，异常也能落到 6 类错误码。
"""
from __future__ import annotations

import inspect
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx
import trafilatura

from app.services.fetch_errors import FetchError, code_for_status, to_fetch_error

log = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = 30.0
MIN_TEXT_CHARS = 200          # 正文短于此判 FETCH_EMPTY（M2 §6.2）
MAX_TITLE_CHARS = 100


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


class TrafilaturaFetcher(BaseFetcher):
    """httpx 取页面 + trafilatura 抽正文。同步实现：路由用 def，FastAPI 丢线程池。"""

    def __init__(self, timeout: float = TIMEOUT):
        self.timeout = timeout

    def fetch(self, url: str) -> FetchedPage:
        url = normalize_url(url)
        html, final_url = self._get(url)
        text = trafilatura.extract(html, **_EXTRACT_KWARGS) or ""
        text = text.strip()
        if len(text) < MIN_TEXT_CHARS:
            raise FetchError("FETCH_EMPTY", detail=f"仅 {len(text)} 字")

        meta = trafilatura.extract_metadata(html)
        title = _pick_title(final_url, getattr(meta, "title", None), text)
        return FetchedPage(url=final_url, title=title, text=text)

    def _get(self, url: str) -> tuple[str, str]:
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=self.timeout,
                headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
            ) as client:
                resp = client.get(url)
        except Exception as exc:                    # noqa: BLE001 - 统一翻译成 6 类错误码
            raise to_fetch_error(exc) from exc

        error_code = code_for_status(resp.status_code)
        if error_code:
            raise FetchError(error_code, detail=f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            # 其余 4xx/5xx 没有专属语义，归到"不是网页"，比笼统的 TASK_FAILED 有用
            raise FetchError("FETCH_INVALID", detail=f"HTTP {resp.status_code}")

        ctype = (resp.headers.get("content-type") or "").lower()
        # 头部完全缺失时不拦（部分站点/反代不返回），交给后面 200 字阈值判空
        if ctype and "html" not in ctype:
            raise FetchError("FETCH_INVALID", detail=f"content-type={ctype}")

        return resp.text, str(resp.url)


_default_fetcher: BaseFetcher | None = None


def get_fetcher() -> BaseFetcher:
    """单例入口；测试里替换实现只需改这个模块的 `_default_fetcher`。"""
    global _default_fetcher
    if _default_fetcher is None:
        _default_fetcher = TrafilaturaFetcher()
    return _default_fetcher


def set_fetcher(fetcher: BaseFetcher | None) -> None:
    """给 verify 脚本 / 单测注入假实现（T2.10 的三种失败场景靠它）。"""
    global _default_fetcher
    _default_fetcher = fetcher
