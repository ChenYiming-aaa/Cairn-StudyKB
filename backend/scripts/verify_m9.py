"""M9 验收脚本（分组长大的那种）。

用法：
    cd backend && uv run python scripts/verify_m9.py
    cd backend && uv run python scripts/verify_m9.py --only layout    # 只跑判列
    cd backend && uv run python scripts/verify_m9.py --only resume    # 只跑断点续跑

退出码：0 全绿 / 1 有用例失败 / 2 环境不满足（缺组件）

覆盖分组（**当前只有 T9.6 的两组**，T9.7–T9.11 的用例在 T9.12 往这里加）：
  §layout  T9.6 四组 `samples/*/twocol.pdf` 共 40 页：不丢行 / 双栏不交错 / 单栏 y 不回头 /
           行数不膨胀 / `python` 第 1 页字面锚词
  §resume  T9.6 断点续跑（跑 3 页 → 续跑只补 4..7 → 再跑一页不动）与单页重试（只识别点名页）

**为什么这两组值得单独落成脚本**：`ocr_layout.order_lines` 和 `ingest_file` 是 T9.6 里最容易
被后手改坏的两处（T9.8 / T9.10 会碰它们周边）。判列错了不会报错，只会让检索和整理拿到
语义断裂的文本 —— 没有回归网就是裸奔。

**不联网、不调 LLM**：真起 `cairn-ocr` 子进程（从 `backend/build/components/dist/cairn-ocr`
复制进临时数据目录，跟线上 `components/ocr` 的形态一致），识别是真识别。缺构建产物直接退出 2。

判据**在脚本里独立重算**（不 import `ocr_layout._is_two_column`）：实现把阈值改松了要能被发现，
自己调自己不算验。
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
import traceback
import zlib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m9-"))
(TMP / ".env").write_text("LLM_API_KEY=sk-verify-m9-not-a-real-key\n", encoding="utf-8")
os.environ["DATA_DIR"] = str(TMP)            # 必须早于 import app
os.environ["VECTOR_ENABLED"] = "0"           # 这里验识别，不验向量；补向量单独打桩计数
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ["CAIRN_COMPONENT_MODE"] = "process"   # 走真子进程，跟线上一致
os.environ.setdefault("LOG_LEVEL", "WARNING")

sys.path.insert(0, str(BACKEND))

from app.services import components, ocr, ocr_layout, pdf_pages      # noqa: E402

COMPONENT_SRC = BACKEND / "build" / "components" / "dist" / "cairn-ocr"
SAMPLES = ("cet6", "java", "math", "python")
_TAG = re.compile("\x00(\\d+)\x00")
LIMIT = 0          # --pages N：每组只跑前 N 页（调试判列用；正式跑不要给）

RESULTS: list[tuple[bool, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((bool(ok), name, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  {mark}  {name}" + (f"   → {detail}" if detail else ""))
    return bool(ok)


def prepare_component() -> str:
    """把构建产物复制成临时数据目录里的 `components/ocr`（这就是装完之后的形态）。"""
    if not COMPONENT_SRC.is_dir():
        return f"缺构建产物 {COMPONENT_SRC}，先 cd backend && uv run python ../tools/build_components.py --only ocr"
    dst = TMP / "components" / "ocr"
    if not dst.exists():
        shutil.copytree(COMPONENT_SRC, dst)
    mode = components.resolve("ocr")
    if mode != "component":
        return f"组件起不来（resolve 返回 {mode!r}），检查 {dst} 里的 exe 与 manifest"
    return ""


# ── 几何工具：故意不复用 ocr_layout 的私有函数 ─────────────────
def _box(line: dict) -> tuple[float, float, float, float]:
    pts = [p for p in (line.get("box") or []) if len(p) >= 2]
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _cx(line: dict) -> float:
    x0, _, x1, _ = _box(line)
    return (x0 + x1) / 2


def _cy(line: dict) -> float:
    _, y0, _, y1 = _box(line)
    return (y0 + y1) / 2


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def spec_two_column(lines: list[dict], width: float) -> bool:
    """规格（执行计划 §T9.6）：两侧各 ≥2 行、横跨整页的行不参与、P90/P10 不重叠。"""
    mid = width / 2
    left = [ln for ln in lines if _cx(ln) < mid]
    right = [ln for ln in lines if _cx(ln) >= mid]
    if len(left) < 2 or len(right) < 2:
        return False
    span = 0.7 * width
    le = [ln for ln in left if _box(ln)[2] - _box(ln)[0] <= span]
    re_ = [ln for ln in right if _box(ln)[2] - _box(ln)[0] <= span]
    if len(le) < 2 or len(re_) < 2:
        return False
    tol = max(8.0, 0.02 * width)
    return _pct([_box(ln)[2] for ln in le], 0.9) <= _pct([_box(ln)[0] for ln in re_], 0.1) + tol


def _audit_page(label: str, result) -> None:
    """逐页断言。

    **归属判定用唯一标记，不用文字反查**：`1` `-` `=` 这类短文本会命中半页的行，
    按「输出行里包含哪些输入行」归左右会得到一堆假交错（2026-11-13 第一版就这么翻车，
    126 条里 30 条假 FAIL）。给每行文字尾部打一个 `\\x00<序号>\\x00`，标记只影响拼接空隙、
    不参与几何与判列，却能精确定位每一行。
    """
    raw = [ln for ln in result.lines if str(ln.get("text") or "").strip()]
    if not raw:
        check(f"{label} 有文字", False, "这一页一行都没认出来")
        return
    tagged = []
    for index, line in enumerate(raw):
        item = dict(line)
        item["text"] = f"{line['text']}\x00{index}\x00"
        tagged.append(item)

    out = ocr_layout.order_lines(tagged, result.width)
    joined = "\n".join(out)

    missing = [i for i in range(len(raw)) if f"\x00{i}\x00" not in joined]
    check(f"{label} 不丢行（{len(raw)} 行）", not missing, f"丢了行号 {missing[:5]}")
    check(f"{label} 行数不膨胀", len(out) <= len(raw), f"{len(out)} 行输出 / {len(raw)} 行输入")

    mid = result.width / 2
    sequence: list[str] = []
    for row in out:
        ids = [int(m) for m in _TAG.findall(row)]
        if not ids:
            continue
        sides = {"L" if _cx(raw[i]) < mid else "R" for i in ids}
        if len(sides) == 1:          # 跨中线的一行（通栏标题）不参与左右序列
            sequence.append(sides.pop())
    marks = "".join(sequence)

    if spec_two_column(raw, result.width):
        switches = sum(1 for a, b in zip(marks, marks[1:]) if a != b)
        check(f"{label} 双栏整栏左→整栏右", switches <= 1, f"左右切换 {switches} 次：{marks[:90]}")
    else:
        height = max(_cy(ln) for ln in raw) - min(_cy(ln) for ln in raw) or 1.0
        back, high = 0, -1.0
        for row in out:
            ids = [int(m) for m in _TAG.findall(row)]
            if not ids:
                continue
            y = _cy(raw[min(ids, key=lambda i: _box(raw[i])[0])])
            if y < high - 0.05 * height:
                back += 1
            high = max(high, y)
        check(f"{label} 单栏 y 不回头", back == 0, f"回头 {back} 次")


# ── §layout ────────────────────────────────────────────────────
def group_layout() -> None:
    total_pages = 0
    for name in SAMPLES:
        path = ROOT / "samples" / name / "twocol.pdf"
        if not path.is_file():
            check(f"{name}/twocol.pdf 存在", False, str(path))
            continue
        # 伪 file_id 兼作页图缓存键：同一常量会让四组读到同一份缓存（2026-11-12 踩过）
        fid = 9100 + zlib.crc32(str(path).encode("utf-8")) % 900
        pdf = pdf_pages.open_pdf(path)
        try:
            count = pdf_pages.page_count(pdf)
            check(f"{name}/twocol.pdf 有 {count} 页", count == 10, f"{count} 页")
            if LIMIT:
                count = min(count, LIMIT)
            for start in range(0, count, ocr.BATCH):
                chunk = list(range(start, min(start + ocr.BATCH, count)))
                images = [pdf_pages.render(pdf, index, fid) for index in chunk]
                # 按生产的方式 5 页一批：单页调用会反复触发组件握手，40 页能跑成 10 分钟
                results = ocr.recognize([pdf_pages.abs_path(img.path) for img in images])
                for index, result in zip(chunk, results):
                    label = f"{name} 第 {index + 1} 页"
                    if not result.ok:
                        check(f"{label} 识别成功", False, str(result.error))
                        continue
                    _audit_page(label, result)
                    total_pages += 1
        finally:
            pdf.close()
    check(f"四组共 {total_pages} 页都跑过判列", total_pages == (4 * LIMIT if LIMIT else 40),
          f"{total_pages} 页")

    # 字面锚词：左栏后段的词必须排在右栏开头的词之前（交错就会翻过来）
    path = ROOT / "samples" / "python" / "twocol.pdf"
    fid = 9100 + zlib.crc32(str(path).encode("utf-8")) % 900
    pdf = pdf_pages.open_pdf(path)
    try:
        image = pdf_pages.render(pdf, 0, fid)
        result = ocr.recognize([pdf_pages.abs_path(image.path)])[0]
    finally:
        pdf.close()
    text = "\n".join(ocr_layout.order_lines(result.lines, result.width))
    a, b = text.find("标准库"), text.find("余数要满足")
    check("python 第 1 页：左栏末段在右栏开头之前", 0 <= a < b, f"标准库@{a} 余数要满足@{b}")


# ── §resume ────────────────────────────────────────────────────
def group_resume() -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import embedder
    from app.services import files as file_service
    from app.services import ingest_file

    scheduled: list[int] = []
    embedder.schedule = lambda item_id, *a, **k: scheduled.append(int(item_id))  # noqa: ARG005

    rendered: list[int] = []
    real_render = pdf_pages.render

    def spy(pdf, index, file_id):                      # noqa: ANN001
        rendered.append(index + 1)
        return real_render(pdf, index, file_id)

    pdf_pages.render = spy
    try:
        with TestClient(app):
            # 走服务层 save：HTTP 上传会当场排队识别，和下面手动 run 打架
            with (ROOT / "samples" / "python" / "exam.pdf").open("rb") as handle:
                saved = file_service.save(handle, filename="exam.pdf")
            payload = {"file_id": saved.file_id}

            rendered.clear()
            ingest_file.run({**payload, "pages": [1, 2, 3]})
            check("点名 3 页只识别 3 页", rendered == [1, 2, 3], str(rendered))

            rendered.clear()
            first = ingest_file.run(payload, task_id=None)
            check("续跑只补没落库的 4..7（不重识别 1..3）", rendered == [4, 5, 6, 7], str(rendered))
            check("续跑收口 7/7 且状态 done",
                  first["done_pages"] == 7 and first["total_pages"] == 7 and first["status"] == "done",
                  str(first))
            check("整份齐了才派补向量（只派一次）", scheduled.count(saved.item_id) == 1,
                  f"派了 {scheduled.count(saved.item_id)} 次")

            rendered.clear()
            again = ingest_file.run(payload)
            check("再跑整份一页都不重识别", rendered == [], str(rendered))
            check("已跑完的整份如实报 skipped", again["skipped"] is True, str(again))

            rendered.clear()
            retry = ingest_file.run({**payload, "pages": [3]})
            check("单页重试只识别第 3 页", rendered == [3], str(rendered))
            check("单页重试后仍是 7/7", retry["done_pages"] == 7, str(retry))
    finally:
        pdf_pages.render = real_render


GROUPS = (("layout", group_layout), ("resume", group_resume))


def main() -> int:
    global LIMIT
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    if "--pages" in sys.argv:
        LIMIT = int(sys.argv[sys.argv.index("--pages") + 1])
    print(f"Cairn M9 验收 · 临时数据目录 {TMP}")
    hint = prepare_component()
    if hint:
        print(f"× {hint}")
        return 2
    started = time.monotonic()
    for name, fn in GROUPS:
        if only and only != name:
            continue
        print(f"§{name}")
        try:
            fn()
        except Exception:
            traceback.print_exc()
            check(f"§{name} 跑完", False, "异常中断，见上面的栈")
    components.stop_all()
    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS · {time.monotonic() - started:.0f} s")
    print(f"临时数据目录：{TMP}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
