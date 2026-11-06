"""视频现成字幕的选取与解析（T2.6 增强）。

**定位**：这是条加速路径，不是必经路径。有字幕就直接用，省掉「下音频 + 跑模型」；
任何一步拿不到（没字幕、要登录、格式不认、下载失败）都返回 None/抛异常，
由调用方静默退回语音识别。**字幕坏了绝不能让采集失败。**

为什么值得做（2026-11-06 定）：
- 一条 5 分钟视频，small 模型在 CUDA 上约 30 秒，CPU 上要几分钟；有字幕是毫秒级
- 没有显卡的机器，字幕是唯一现实可行的兜底
- 作者上传的人工字幕通常比 ASR 更准（专有名词、断句）

已知边界（实测）：
- **B 站字幕必须登录**。未登录时 yt-dlp 只给 danmaku，`subtitles` 为空，
  这里会自然返回 None → 走 ASR。要用请配 `.env` 的 `YTDLP_COOKIES`
- YouTube 的自动字幕可以直接拿（`automatic_captions`）
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass

from app.services import browser

log = logging.getLogger(__name__)

# 只认中文与英文：知识库是中文场景，日韩等的识别质量与产品定位都不匹配
_LANG_ORDER = ("zh-hans", "zh-cn", "zh", "zh-hant", "zh-tw", "en", "en-us", "en-gb")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_MAX_BYTES = 8 * 1024 * 1024          # 字幕不该有这么大，超过视为异常站点
_TS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})")


@dataclass(frozen=True)
class SubtitleTrack:
    lang: str               # 原样保留站点给的语言键，用于落库与展示
    auto: bool              # True = 自动生成字幕，质量参差
    url: str
    ext: str


def _rank(lang: str) -> int:
    """越小越优先；-1 表示不要。"""
    key = lang.lower().replace("_", "-")
    if key in _LANG_ORDER:
        return _LANG_ORDER.index(key)
    base = key.split("-")[0]
    if base == "zh":
        return 2            # zh-Hans-CN 这类带后缀的仍算简体优先档
    if base == "en":
        return 5
    return -1


def _prefer_format(entries: list[dict]) -> dict | None:
    """json(B 站，毫秒级时间) > vtt > srt。

    srv1/2/3 是 YouTube 的 XML 变体，解析成本高而收益低，刻意跳过；
    ttml 同理。只剩这些时宁可回去跑 ASR。
    """
    for want in ("json", "vtt", "srt"):
        for entry in entries:
            if (entry.get("ext") or "").lower() == want and entry.get("url"):
                return entry
    return None


def pick(info: dict) -> SubtitleTrack | None:
    """从 yt-dlp 的 info 里挑一条轨道。人工字幕优先于自动字幕。"""
    for auto, table in ((False, info.get("subtitles") or {}),
                        (True, info.get("automatic_captions") or {})):
        best: tuple[int, str, list[dict]] | None = None
        for lang, entries in table.items():
            rank = _rank(lang)
            if rank < 0 or not entries:
                continue
            if best is None or rank < best[0]:
                best = (rank, lang, entries)
        if best is None:
            continue
        _, lang, entries = best
        fmt = _prefer_format(entries)
        if fmt is not None:
            return SubtitleTrack(lang=lang, auto=auto,
                                 url=fmt["url"], ext=(fmt.get("ext") or "").lower())
    return None


def _headers(url: str) -> dict[str, str]:
    headers = {"User-Agent": _UA}
    # B 站字幕在 aisubtitle.hdslb.com，带 referer 才稳定
    if "bilibili" in url or "hdslb" in url:
        headers["Referer"] = "https://www.bilibili.com/"
    # 登录助手导出的 cookie 顺手带上：部分字幕地址会校验登录态
    if (cookies := browser.cookies_for(url)):
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return headers


def fetch(track: SubtitleTrack, timeout: float = 20.0) -> list[tuple[float, str]]:
    """下载并解析成 [(开始秒数, 文本)]。拿不到就抛，由调用方决定是否降级。"""
    req = urllib.request.Request(track.url, headers=_headers(track.url))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(_MAX_BYTES)
    text = raw.decode("utf-8", "replace")

    if track.ext == "json" or text.lstrip().startswith("{"):
        cues = _parse_json(text)
    else:
        cues = _parse_cues(text)
    return _clean(cues)


def _parse_json(text: str) -> list[tuple[float, str]]:
    """B 站字幕：{"body": [{"from": 1.2, "content": "..."}]}。"""
    data = json.loads(text)
    body = data.get("body") or data.get("subtitles") or []
    cues: list[tuple[float, str]] = []
    for item in body:
        start = item.get("from", item.get("start", 0)) or 0
        content = (item.get("content") or item.get("text") or "").strip()
        if content:
            cues.append((float(start), content))
    return cues


def _parse_cues(text: str) -> list[tuple[float, str]]:
    """WebVTT / SRT：只取每块第一条时间轴与它后面的文本行。"""
    cues: list[tuple[float, str]] = []
    start: float | None = None
    for line in text.splitlines():
        if "-->" in line:
            m = _TS.search(line)
            if m:
                h, mi, s, ms = m.groups()
                start = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000
            else:
                start = None
            continue
        stripped = line.strip()
        if not stripped:
            start = None
            continue
        if stripped.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or stripped.isdigit():
            continue
        if start is not None:
            cues.append((start, re.sub(r"<[^>]+>", "", stripped)))
    return cues


def _clean(cues: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """去掉空行、相邻重复（自动字幕滚动时常见）、以及同一时间轴的多行碎片。"""
    out: list[tuple[float, str]] = []
    last = ""
    for start, text in cues:
        text = " ".join(text.split())
        if not text or text == last:
            continue
        if out and abs(out[-1][0] - start) < 0.01:
            out[-1] = (out[-1][0], out[-1][1] + text)   # 中文不补空格
        else:
            out.append((start, text))
        last = text
    return out
