"""本地识别组件 worker（T9.4：PDF 与图片读字）。

为什么是独立组件：`rapidocr` + `onnxruntime` + `opencv` 解包近 300 MB，主包放不下
（ADR-035：合并后只剩 8.5 MB 余量，且要推翻 M8 的 `MONOLITH_HEAVY` 与崩溃隔离）。
主程序通过管道驱动，组件自带解释器与模型。

四条硬约定：

1. **stdout 只放协议行**。rapidocr 自己的日志走 logging 的 StreamHandler（stderr，
   不会串到 stdout），但默认 INFO 每页刷四行，会把主程序的 `app.log` 灌满；
   这里用 `Global.log_level=warning` 压掉。
2. **模型随包自带**（`rapidocr/models/*.onnx`，约 31 MB），`model_root_dir` 显式指过去。
   rapidocr 只在文件缺失时才联网下载（`utils/download_file.py`），所以"目录不在就直接报错"
   是**结构上的断网保证**，不是靠运气 —— 自检可以真断网跑。
3. **单页失败不影响整包**：一页解码失败就回 `{key, error}`，其余页照常识别。
   第 7 页坏掉不该让整份 30 页的材料白读。
4. **传路径不传 base64**：页图已经在盘上，1.5 MB × 30 页的编解码纯属浪费。
   `cv2.imread` 在 Windows 上读不了中文路径，所以走 `read_bytes()` + `imdecode`。
"""
from __future__ import annotations

import base64
import logging
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _protocol import OpError, main  # noqa: E402

VERSION = "0.2.0"
BATCH_LIMIT = 5                  # 协议约定：一次最多 5 页
MAX_PIXELS = 40_000_000          # 10000 × 4000；A4@150dpi 是 1240×1754，给足余量

_engine = None
_engine_lock = threading.Lock()
_run_lock = threading.Lock()     # 组件进程全局串行；后端并发调没有意义（T9.6 负责排队）


def _models_dir() -> Path:
    """包内模型目录。不存在就报错 —— 绝不让 rapidocr 退到"缺了就下载"。"""
    import rapidocr

    base = Path(rapidocr.__file__).resolve().parent / "models"
    print(f"[ocr] 模型目录 {base}（存在={base.is_dir()}，rapidocr={rapidocr.__file__}）",
          file=sys.stderr, flush=True)
    if not base.is_dir():
        raise OpError("OCR_FAILED", f"包内没有模型目录：{base}")
    return base


def _block_downloads() -> None:
    """把 rapidocr 的下载入口改成"只许用包内已有文件"（T9.4「显式禁网」）。

    rapidocr 没有关闭下载的开关：`DownloadFile.run` 只在文件存在**且 sha256 匹配**时
    跳过，否则就去 `requests.get` —— 模型缺失或包被裁剪过时会静默联网。
    组件必须离线可用，所以这里包一层：**保留它自己的跳过判断**（文件齐全时照常返回），
    只在"真要下载"那一刻抛错。这样自检可以真断网跑。

    注意别把 `run` 整个换掉：rapidocr 每次加载模型都会调它（齐全时只是空转），
    整替换会让正常的加载也报"缺模型"（本轮踩过）。
    """
    from rapidocr.utils import download_file as dl

    def _guarded(cls, params) -> None:
        cls.verbose = bool(getattr(params, "verbose", False))   # 原 run 的第一行，跳过判断要用
        save = Path(str(getattr(params, "save_path", "")))
        logger = getattr(params, "logger", None) or logging.getLogger("RapidOCR")
        if cls._should_skip_download(save, getattr(params, "sha256", None), logger):
            return
        why = "包内没有这个文件" if not save.exists() else "包内文件校验不通过"
        raise OpError("OCR_FAILED",
                      f"{why}：{save.name}。组件包不完整，不做联网下载")

    dl.DownloadFile.run = classmethod(_guarded)  # type: ignore[method-assign]


def _load():
    global _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        import rapidocr

        _block_downloads()
        try:
            _engine = rapidocr.RapidOCR(params={
                "Global.model_root_dir": str(_models_dir()),
                "Global.log_level": "warning",
            })
        except OpError:
            raise                       # 缺模型/禁网已经是明确的码，别再包一层
        except Exception as exc:  # noqa: BLE001 - DLL 缺失 / 模型损坏 / 引擎初始化失败都在这里
            raise OpError("OCR_FAILED",
                          f"识别引擎加载失败（{type(exc).__name__}: {str(exc)[:160]}）") from exc
        return _engine


# ── 单页 ────────────────────────────────────────────────
def _decode(path: Path):
    """读盘 → BGR ndarray。返回 (arr, width, height)。"""
    import cv2
    import numpy as np

    if not path.is_file():
        raise OpError("IMAGE_NOT_FOUND", f"页图不存在：{path.name}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OpError("IMAGE_DECODE_FAILED", f"页图读不出来（{type(exc).__name__}）") from exc
    if not raw:
        raise OpError("IMAGE_DECODE_FAILED", "页图是空文件")

    arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise OpError("IMAGE_DECODE_FAILED", "解不出图像（格式不支持或文件损坏）")
    height, width = arr.shape[:2]
    if width * height > MAX_PIXELS:
        raise OpError("IMAGE_DECODE_FAILED",
                      f"页图 {width}×{height} 过大，超过 {MAX_PIXELS // 1_000_000} 百万像素")
    return arr, width, height


def _box(raw) -> list[list[int]]:
    return [[int(round(float(x))), int(round(float(y)))] for x, y in raw]


def _lines(result) -> list[dict]:
    """引擎输出是三个平行数组；空值时 txts/scores 可能是 None，boxes 可能缺元素。"""
    texts = getattr(result, "txts", None) or ()
    scores = getattr(result, "scores", None) or ()
    boxes = getattr(result, "boxes", None)
    out: list[dict] = []
    for i, text in enumerate(texts):
        if not text:
            continue
        conf = float(scores[i]) if i < len(scores) else 0.0
        box = _box(boxes[i]) if boxes is not None and i < len(boxes) else []
        out.append({"text": str(text), "box": box, "conf": round(conf, 4)})
    return out


def _one(item: dict, index: int) -> dict:
    key = str(item.get("key") or f"p{index:04d}")
    started = time.perf_counter()
    arr, width, height = _decode(Path(str(item.get("path") or "")))
    with _run_lock:
        result = _load()(arr)
    return {
        "key": key, "width": width, "height": height,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "lines": _lines(result),
    }


# ── 主入口 ──────────────────────────────────────────────
def ocr(req: dict, progress) -> dict:
    items = req.get("items")
    if not isinstance(items, list) or not items:
        raise OpError("COMPONENT_BAD_OP", "items 不能为空")
    if len(items) > BATCH_LIMIT:
        raise OpError("COMPONENT_BAD_OP", f"一批最多 {BATCH_LIMIT} 页，收到 {len(items)}")

    total = len(items)
    pages: list[dict] = []
    for i, item in enumerate(items):
        try:
            pages.append(_one(item if isinstance(item, dict) else {}, i))
        except OpError as exc:
            pages.append({"key": str((item or {}).get("key") or f"p{i:04d}"),
                          "error": exc.code, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - 一页炸了不能拖垮整包
            pages.append({"key": str((item or {}).get("key") or f"p{i:04d}"),
                          "error": "OCR_FAILED",
                          "message": f"{type(exc).__name__}: {str(exc)[:160]}"})
        progress(round((i + 1) * 100 / total))
    return {"pages": pages}


# ── 自检 ────────────────────────────────────────────────
# 320×80、白底黑字「本地识别」，微软雅黑 44 px。3.8 KB 的常量，比外部样本可靠
# （打包后跑自检时不该依赖仓库里的 samples/ 目录在不在）。
SELFTEST_PNG = (
    "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"
    "YCuuAAAAAElFTkSuQmCC"
)
SELFTEST_WIDTH, SELFTEST_HEIGHT = 320, 80


def _selftest_sample() -> dict:
    """样本图落在系统临时目录：父子进程同机，`--serve` 子进程读得到。"""
    path = Path(tempfile.gettempdir()) / "cairn-ocr-selftest.png"
    path.write_bytes(base64.b64decode(SELFTEST_PNG))
    return {"op": "ocr", "items": [{"key": "p0001", "path": str(path)}], "dpi": 150}


def _expect(reply: dict) -> tuple[bool, str]:
    pages = reply.get("pages") or []
    if not reply.get("ok") or len(pages) != 1:
        return False, f"回包形状不对：{str(reply)[:160]}"
    page = pages[0]
    if page.get("error"):
        return False, f"识别失败：{page.get('error')} {page.get('message', '')}"
    lines = page.get("lines") or []
    text = "".join(ln.get("text", "") for ln in lines)
    if "识别" not in text:
        return False, f"没认出「识别」两个字：{text!r}"
    if (page.get("width"), page.get("height")) != (SELFTEST_WIDTH, SELFTEST_HEIGHT):
        return False, f"尺寸不对：{page.get('width')}×{page.get('height')}"
    for ln in lines:
        if ln.get("box") and len(ln["box"]) != 4:
            return False, f"box 必须是四个点：{ln['box']}"
        if not 0.0 <= float(ln.get("conf", 0)) <= 1.0:
            return False, f"conf 越界：{ln.get('conf')}"
    return True, (f"ocr ok：{text!r}，{len(lines)} 行，{page.get('elapsed_ms')} ms，"
                  f"最高分 {max((ln.get('conf', 0) for ln in lines), default=0):.3f}")


if __name__ == "__main__":
    sample = _selftest_sample() if "--selftest" in sys.argv else {}
    sys.exit(main("ocr", VERSION, {"ocr": ocr}, sample=sample, expect=_expect))
