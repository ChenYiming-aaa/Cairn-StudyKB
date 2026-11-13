"""本地识别的唯一入口（T9.5）。

上层只问三件事：能不能识别（`available`）、缺什么（`missing_hint`）、认这几页（`recognize`）。
**别在业务代码里直接 `components.call("ocr", ...)`** —— 三态判定、分批、错误归并都在这里，
否则每个调用点都要把"没装组件怎么办"重新想一遍（最后总有一处会写成静默返回空文本）。

三态直接来自 `components.resolve("ocr")`（组件 > 本机库 > 没有），这里不自己判断：
冻结包里 `rapidocr` / `cv2` 在 `MONOLITH_HEAVY` 里，`find_spec` 自然返回 None，于是自动落到
组件 —— 同一份代码两种形态，这是 M8 那套判定最值钱的地方（ADR-035 也明令别按"内置"改）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from app.services import components
from app.services.component_proc import ComponentError

log = logging.getLogger(__name__)

CID = "ocr"
BATCH = 5                  # 与组件协议上限一致（components/ocr/entry.py 的 BATCH_LIMIT）
# 一批 5 页的时限。**别按「2.8 秒/页」估**：那是稀疏试卷页的数字，双栏讲义页实测 15.7 秒/页，
# 5 页一批正常就要 100–120 秒。原来写 180 只留 1.5 倍余量，机器忙一点（同时补向量、杀软扫包）
# 就整批超时，重试也是整批重来，最后整份文件被标失败 —— 2026-11-13 全量回归踩到。
# 300 秒 = 5 页 × 60 秒，真卡死仍会被判超时（组件崩溃/死循环不会因此假装成功）。
CALL_TIMEOUT = 300.0
MISSING_MESSAGE = "读 PDF 与图片需要先装识别组件"


@dataclass
class PageResult:
    """一页的识别结果。`error` 非空就是这一页失败，`lines` 此时为空。"""

    key: str
    width: int = 0
    height: int = 0
    lines: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str = ""
    message: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def text(self) -> str:
        return "\n".join(str(ln.get("text") or "") for ln in self.lines if ln.get("text"))


# ── 三态 ────────────────────────────────────────────────
def available() -> str:
    """`"component"` / `"local"` / `"none"`。"""
    return components.resolve(CID) or "none"


def missing_hint() -> dict:
    return {"code": "OCR_MISSING", "message": MISSING_MESSAGE}


# ── 识别 ────────────────────────────────────────────────
def recognize(paths: Sequence[str | Path], *,
              on_progress: Callable[[int], None] | None = None) -> list[PageResult]:
    """按 5 页一批识别，返回结果**与入参一一对应、顺序一致**。

    - 某一页坏了只记 `PageResult.error`，不抛异常（第 7 页坏不该让 30 页白读）
    - 组件整体不可用（崩了 / 超时）才抛 `ComponentError`，交给任务层记失败
    - `available()=="none"` 一律抛 `OCR_MISSING`：**绝不返回空文本**，那会变成
      "识别成功但没有字"，用户以为文件本来就是空的
    """
    if not paths:
        return []
    if available() == "none":
        raise ComponentError("OCR_MISSING", MISSING_MESSAGE, CID)

    total = len(paths)
    results: list[PageResult] = []
    for start in range(0, total, BATCH):
        chunk = [Path(p) for p in paths[start:start + BATCH]]
        items = [{"key": f"p{start + i:04d}", "path": str(p)} for i, p in enumerate(chunk)]

        def _stage(pct: int, _start: int = start, _n: int = len(chunk)) -> None:
            if on_progress is None:
                return
            done = _start + _n * max(0, min(100, int(pct))) / 100
            on_progress(round(done * 100 / total))

        reply = components.call(CID, "ocr", {"items": items, "dpi": 150},
                                on_progress=_stage, timeout=CALL_TIMEOUT)
        by_key = {str(pg.get("key")): pg for pg in (reply.get("pages") or [])}
        for item in items:
            page = by_key.get(item["key"])
            if page is None:
                # 组件回了 ok 却漏了这页：当失败记，别当成"这页是空的"
                results.append(PageResult(key=item["key"], error="OCR_FAILED",
                                          message="组件没有返回这一页"))
                continue
            results.append(PageResult(
                key=item["key"],
                width=int(page.get("width") or 0),
                height=int(page.get("height") or 0),
                lines=list(page.get("lines") or []),
                elapsed_ms=int(page.get("elapsed_ms") or 0),
                error=str(page.get("error") or ""),
                message=str(page.get("message") or ""),
            ))

    if on_progress is not None:
        on_progress(100)
    return results


# ── 设置页「测试一下」 ──────────────────────────────────
def selftest() -> dict:
    """真跑一次识别（组件内置小图），用于设置页按钮。

    不在这里造图：主程序没有 PIL（它在组件的依赖里），而组件自带样本更方便。
    """
    mode = available()
    if mode == "none":
        return {"ok": False, "mode": mode, "text": "", "elapsed_ms": 0, **missing_hint()}
    try:
        reply = components.call(CID, "selfcheck", {}, timeout=CALL_TIMEOUT)
    except ComponentError as exc:
        return {"ok": False, "mode": mode, "text": "", "elapsed_ms": 0,
                "code": exc.code, "message": exc.message}

    page = (reply.get("pages") or [{}])[0]
    text = "".join(str(ln.get("text") or "") for ln in (page.get("lines") or []))
    ok = bool(text) and not page.get("error")
    return {
        "ok": ok,
        "mode": mode,
        "text": text[:40],
        "elapsed_ms": int(page.get("elapsed_ms") or 0),
        "code": "" if ok else str(page.get("error") or "OCR_FAILED"),
        "message": "" if ok else str(page.get("message") or "这次没认出字"),
    }
