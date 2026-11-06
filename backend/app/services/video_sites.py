"""视频站点链接归一化（T2.7 补丁）。

**为什么需要这个模块**（2026-11-06 实测，抖音真实链接）：

1. 用户从 App 复制出来的抖音链接常是聚合页而不是单条视频：
   `https://www.douyin.com/jingxuan?modal_id=7704937199334116608`
   yt-dlp 对它直接报 `Unsupported URL`，任务以 `TRANSCRIBE_UNSUPPORTED` 失败。
   真正的单条视频地址在 `modal_id` 里，改写成 `https://www.douyin.com/video/<id>` 即可。

2. 改写后 yt-dlp 仍然失败：`Fresh cookies (not necessarily logged in) are needed`。
   抖音的详情接口要 `a_bogus` 签名，签名由页面自己的 JS 生成，我们算不出来；
   但**页面自己会发这个请求**，所以让浏览器打开视频页、截获它自己的响应
   （`browser.capture_json`）就能拿到完整数据。

归一化还有一个副作用是正面的：同一个视频的不同分享形式（带 `?t=`、
`spm_id_from=` 等追踪参数）会收敛成同一个 URL，查重不再漏。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx

log = logging.getLogger(__name__)

# 短链域名 → 需要先跟随跳转才知道真实地址
SHORT_HOSTS = {"v.douyin.com", "b23.tv", "bili2233.cn"}

# 纯追踪参数，去掉不影响取到同一个视频（`p` 不能删：它是分 P 号）
_TRACKING = {
    "t", "spm_id_from", "vd_source", "share_source", "share_medium", "share_plat",
    "bbid", "ts", "from", "from_spmid", "seid", "sessionid", "is_story_h5",
    "modal_id", "mid", "wid", "upsig", "uparams", "is_from_webapp", "sender_device",
    "share_token", "web_id",
}

_MODAL_RE = re.compile(r"modal_id=(\d+)")
_DOUYIN_VIDEO_RE = re.compile(r"/video/(\d+)")
_DOUYIN_NOTE_RE = re.compile(r"/(?:note|slides)/(\d+)")
_BILI_BV_RE = re.compile(r"/video/(BV[0-9A-Za-z]{10}|av\d+)", re.I)
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _bare(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def is_douyin(url: str) -> bool:
    host = _bare(_host(url))
    return host.endswith("douyin.com") or host.endswith("iesdouyin.com")


def short_id(url: str) -> str:
    """归一化后能直接用的 URL；短链跟随跳转后再归一化一次。"""
    if not url:
        return url
    host = _bare(_host(url))
    if host in SHORT_HOSTS:
        resolved = resolve_short(url)
        if resolved and resolved != url:
            return short_id(resolved)
        return url
    return url


def resolve_short(url: str, timeout: float = 10.0) -> str:
    """短链 → 最终地址。失败原样返回，让下游按自己的错误码收口。"""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout,
                          headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(url)
        final = str(resp.url)
        log.info("短链解析 %s → %s", url, final[:120])
        return final
    except Exception as exc:                      # noqa: BLE001 - 解析失败不算致命
        log.info("短链解析失败（%s），按原链接处理", type(exc).__name__)
        return url


def canonicalize(url: str) -> str:
    """把分享链接改写成「单条视频」的规范地址；认不出的原样返回。"""
    url = short_id(url)
    parsed = urlparse(url)
    host = _bare((parsed.hostname or "").lower())

    if host.endswith("douyin.com") or host.endswith("iesdouyin.com"):
        return _canonical_douyin(url, parsed)

    if host in ("bilibili.com", "b23.tv", "bili2233.cn", "bilibili.tv"):
        return _strip_tracking(url, parsed)

    if host == "youtu.be":
        vid = parsed.path.strip("/").split("/")[0]
        if _YOUTUBE_ID_RE.match(vid):
            return f"https://www.youtube.com/watch?v={vid}"
        return url
    return _strip_tracking(url, parsed)


def _canonical_douyin(url: str, parsed) -> str:
    vid = _DOUYIN_VIDEO_RE.search(parsed.path)
    if vid:
        return f"https://www.douyin.com/video/{vid.group(1)}"
    # 聚合页把视频 id 藏在 query 里：jingxuan?modal_id=…、discover?modal_id=…
    modal = _MODAL_RE.search(parsed.query) or _MODAL_RE.search(parsed.fragment or "")
    if modal:
        return f"https://www.douyin.com/video/{modal.group(1)}"
    note = _DOUYIN_NOTE_RE.search(parsed.path)
    if note:
        # 图文笔记没有视频轨道，交给 transcriber 判 UNSUPPORTED（这里只负责识别）
        return f"https://www.douyin.com/note/{note.group(1)}"
    return url


def _strip_tracking(url: str, parsed) -> str:
    query = parse_qs(parsed.query, keep_blank_values=True)
    kept = {k: v for k, v in query.items() if k.lower() not in _TRACKING}
    if len(kept) == len(query):
        return url
    pairs = []
    for key, values in kept.items():
        for value in values:
            pairs.append(f"{key}={value}")
    return urlunparse(parsed._replace(query="&".join(pairs)))


def douyin_note_id(url: str) -> str | None:
    """图文笔记的 id：这类链接会让下游明确拒绝，而不是报"下载失败"。"""
    parsed = urlparse(url)
    note = _DOUYIN_NOTE_RE.search(parsed.path)
    return note.group(1) if note else None
