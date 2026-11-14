"""txt / md 抽取（T9.7）：直读，只做编码判定。

**编码顺序有讲究**：中文 Windows 上"记事本存出来的"文件十有八九是 GBK，
但 utf-8 解码 GBK 中文时**不一定报错**（有些字节序列恰好合法），
所以顺序是 utf-8 → gbk → utf-8-sig，最后兜底 `errors="replace"` 并记下用的是哪档。
宁可留几个替换符也要把余下的字读出来 —— 整份拒收更糟。

**1M 字符上限**：上传白名单允许 200 MB，一份 200 MB 的 txt 走完切块要几十秒、
补向量几千条，用户只觉得"卡住了"。上限只截内容不改状态（`meta.truncated` 记着），
因为"读到的就是全文的前一段"是读取策略，不是失败，不该挡住整理。
"""
from __future__ import annotations

from pathlib import Path

from app.services.extractors.base import ExtractedDoc, Extractor, ExtractError, PageText, tidy

MAX_CHARS = 1_000_000
_ENCODINGS = ("utf-8", "gbk", "utf-8-sig")


class PlainExtractor(Extractor):
    """txt 与 md 共用一套实现，`EXT_BY_CLASS` 里注册两次。"""

    def __init__(self, ext: str = "txt"):
        self.ext = ext

    def extract(self, path: Path, original_name: str = "", asset_url=None) -> ExtractedDoc:
        raw = path.read_bytes()
        text, encoding = _decode(raw)

        truncated = len(text) > MAX_CHARS
        if truncated:
            text = text[:MAX_CHARS]
        text = tidy(text)

        meta = {
            "encoding": encoding,
            "chars": len(text),
            "bytes": len(raw),
            "truncated": truncated,
            "lines": text.count("\n") + 1 if text else 0,
        }
        page = PageText(page_no=1, text=text)
        return ExtractedDoc(text=text, pages=[page], page_count=1, meta=meta)


def _decode(raw: bytes) -> tuple[str, str]:
    if not raw:
        raise ExtractError("FILE_EMPTY", "这个文件是空的")
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    # 三种都不行（二进制被改了后缀、混合编码）：留字，别整份拒收
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"
