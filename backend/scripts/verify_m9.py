"""M9 验收脚本（分组长大的那种）。

用法：
    cd backend && uv run python scripts/verify_m9.py
    cd backend && uv run python scripts/verify_m9.py --only layout    # 只跑判列
    cd backend && uv run python scripts/verify_m9.py --only resume    # 只跑断点续跑
    cd backend && uv run python scripts/verify_m9.py --only extract   # 只跑抽取（不需要识别组件）
    cd backend && uv run python scripts/verify_m9.py --only workspace # 只跑工作区（不需要识别组件）

退出码：0 全绿 / 1 有用例失败 / 2 环境不满足（缺组件）

覆盖分组（**T9.6 两组 + T9.7 一组**，T9.8–T9.11 的用例在 T9.12 往这里加）：
  §layout  T9.6 四组 `samples/*/twocol.pdf` 共 40 页：不丢行 / 双栏不交错 / 单栏 y 不回头 /
           行数不膨胀 / `python` 第 1 页字面锚词
  §resume  T9.6 断点续跑（跑 3 页 → 续跑只补 4..7 → 再跑一页不动）与单页重试（只识别点名页）
  §extract T9.7 四组 `course.docx` 结构与 `samples/_check.json` 逐项对齐、HTML 无 base64 图、
           pptx 备注与表格、xlsx 200 行截断与竖线转义、txt 三种编码判定，
           以及端到端：上传即排队 → 正文覆盖 → 页可读 → 坏文件不留半份正文
  §workspace T9.9 工作区 CRUD、计数口径（`item_count` / `none_count` / 列表 / 状态计数
           四处对齐）、「未归类」= `IS NULL`、删工作区只移出不删内容、批量整理按工作区收窄

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


# ── §extract（T9.7）────────────────────────────────────────────
FIXTURES = TMP / "fixtures"
DOCX_LEN = (2000, 20000)     # 四份讲义都在 2700–3400 字；出这个区间就是漏段或重复


def _wait_until(predicate, timeout: float = 120.0, interval: float = 0.3):
    """等后台任务收口。**别在"刚返回"那一瞬间下结论**（T9.6 验收踩过）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return None


def _make_fixtures() -> dict[str, Path]:
    """合成 pptx / xlsx / txt：真实格式、随脚本生成，不往仓库里塞二进制。"""
    from docx import Document
    from docx.shared import Inches
    from openpyxl import Workbook
    from pptx import Presentation
    from pptx.util import Inches as PInches

    FIXTURES.mkdir(parents=True, exist_ok=True)

    # pptx：1 页标题+要点（带层级）、1 页表格、第 1 页有备注
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "第三章 线性表"
    frame = slide.placeholders[1].text_frame
    frame.text = "顺序存储：用一段连续空间"
    sub = frame.add_paragraph()
    sub.text = "随机访问 O(1)"
    sub.level = 1
    slide.notes_slide.notes_text_frame.text = "这里强调插入删除的复杂度对比"
    table_slide = prs.slides.add_slide(prs.slide_layouts[5])
    table_slide.shapes.title.text = "复杂度对比"
    table = table_slide.shapes.add_table(
        2, 3, PInches(1), PInches(2), PInches(6), PInches(1.2)
    ).table
    for col, head in enumerate(("结构", "插入", "查找")):
        table.cell(0, col).text = head
    for col, value in enumerate(("顺序表", "O(n)", "O(1)")):
        table.cell(1, col).text = value
    prs.slides.add_slide(prs.slide_layouts[6])        # 空白页：文字为空
    pptx = FIXTURES / "lecture.pptx"
    prs.save(str(pptx))

    # xlsx：261 行 → 应截到 200；单元格里带竖线与换行；第二张表用来验"写明了读哪张"
    wb = Workbook()
    sheet = wb.active
    sheet.title = "成绩"
    sheet.append(["题型", "题量", "备注"])
    for i in range(1, 261):
        sheet.append([f"题{i}", i, "含|竖线"])
    sheet["C2"] = "含|竖线和\n换行"
    other = wb.create_sheet("透视")
    other.append(["不该被读到"])
    xlsx = FIXTURES / "score.xlsx"
    wb.save(str(xlsx))

    utf8 = FIXTURES / "notes.txt"
    utf8.write_text("第一行：数据结构\n第二行：算法\n", encoding="utf-8")
    gbk = FIXTURES / "gbk.txt"
    gbk.write_bytes("中文编码测试：线性表".encode("gbk"))
    broken = FIXTURES / "broken.txt"
    broken.write_bytes(b"\xff\xff\xff\xff")
    markdown = FIXTURES / "note.md"
    markdown.write_text("# 标题\n\n正文\n", encoding="utf-8")

    # 只有图、没有字的 docx：正文不该被覆盖（否则整理会照着空正文写笔记）
    doc = Document()
    doc.add_picture(str(ROOT / "samples" / "images" / "python_logo.png"), width=Inches(2))
    image_only = FIXTURES / "image-only.docx"
    doc.save(str(image_only))

    # 坏 docx：改后缀的二进制，抽取必须报 failed 而不是崩在半路
    bad = FIXTURES / "broken.docx"
    bad.write_bytes(b"not a real docx" * 100)
    return {"pptx": pptx, "xlsx": xlsx, "txt": utf8, "gbk": gbk, "broken_txt": broken,
            "md": markdown, "image_only_docx": image_only, "bad_docx": bad}


def group_extract() -> None:
    import json

    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import embedder, extractors

    fixtures = _make_fixtures()
    expected = json.loads((ROOT / "samples" / "_check.json").read_text(encoding="utf-8"))

    # ① 四份真实 docx：结构与样本自检记录逐项对齐（比"字数看着差不多"可靠）
    for name in SAMPLES:
        path = ROOT / "samples" / name / "course.docx"
        if not path.is_file():
            check(f"{name}/course.docx 存在", False, str(path))
            continue
        doc = extractors.extract(path, "docx", path.name)
        want = expected[name]["course"]
        meta = doc.meta
        check(f"{name} docx 表数对得上（{want['tables']}）", meta["tables"] == want["tables"],
              f"抽到 {meta['tables']}")
        check(f"{name} docx 图数对得上（{want['images']}）",
              meta["images"] == want["images"], f"抽到 {meta['images']}")
        check(f"{name} docx 标题数对得上（{want['headings']}）",
              meta["headings"] == want["headings"], f"抽到 {meta['headings']}")
        check(f"{name} docx 段落数对得上（{want['paragraphs']}）",
              meta["paragraphs"] == want["paragraphs"], f"抽到 {meta['paragraphs']}")
        low, high = DOCX_LEN
        check(f"{name} docx 正文字数在 {low}–{high}",
              low <= len(doc.text) <= high, f"{len(doc.text)} 字")
        heads = sum(1 for line in doc.text.splitlines() if line.startswith("#"))
        check(f"{name} docx 有标题层级（# 开头）", heads > 0, f"{heads} 个标题行")
        separators = doc.text.count("\n| --- |")
        check(f"{name} docx 表格都转成了 Markdown（{want['tables']} 个）",
              separators == want["tables"], f"表头分隔行 {separators} 个")
        html = doc.pages[0].html or ""
        check(f"{name} docx HTML 含 <table>", "<table" in html, f"{len(html)} 字符")
        check(f"{name} docx HTML 无 base64 内联图", "data:image" not in html,
              f"html {len(html)} 字符，含 data:image={'data:image' in html}")
        check(f"{name} docx HTML 无 <script> / <img>",
              "<script" not in html.lower() and "<img" not in html.lower())
        check(f"{name} docx 单页且非空", doc.page_count == 1 and bool(doc.text.strip()))

    # ② 合成样本
    pptx = extractors.extract(fixtures["pptx"], "pptx")
    check("pptx 按幻灯片分页（3 页）", pptx.page_count == 3, f"{pptx.page_count} 页")
    check("pptx 抽到演讲者备注", "复杂度对比" in pptx.pages[0].text, pptx.pages[0].text[-40:])
    check("pptx 要点层级带缩进", "  - 随机访问" in pptx.pages[0].text)
    check("pptx 表格转 Markdown", "| 顺序表 | O(n) | O(1) |" in pptx.pages[1].text,
          pptx.pages[1].text[:60])
    check("pptx 空白页如实为空页", pptx.pages[2].text == "", repr(pptx.pages[2].text))

    xlsx = extractors.extract(fixtures["xlsx"], "xlsx")
    check("xlsx 截到 200 行并标记 truncated",
          xlsx.meta["truncated"] and xlsx.meta["rows_read"] == 200, str(xlsx.meta))
    check("xlsx 只读第一张表并写明表名", xlsx.text.startswith("工作表：成绩"),
          xlsx.text[:30])
    check("xlsx 没把第二张表读进来", "不该被读到" not in xlsx.text)
    check("xlsx 单元格竖线被转义", "含\\|竖线" in xlsx.text,
          f"转义 {xlsx.text.count(chr(92) + '|')} 处")
    check("xlsx 单元格换行被压平", "换行" in xlsx.text and "含\\|竖线和 换行" in xlsx.text)
    # 200 行含表头，数据行 199；用 `题<数字>` 判行，别用「以 | 题 开头」——表头也是"题"
    data_rows = sum(1 for line in xlsx.text.splitlines() if re.match(r"\| 题\d+ \|", line))
    check("xlsx Markdown 表行数与读取行数一致（199 数据行）", data_rows == 199,
          f"{data_rows} 行")

    txt = extractors.extract(fixtures["txt"], "txt")
    check("txt utf-8 直读", txt.meta["encoding"] == "utf-8" and "数据结构" in txt.text,
          str(txt.meta))
    gbk = extractors.extract(fixtures["gbk"], "txt")
    check("txt GBK 识别正确（无替换符）",
          gbk.meta["encoding"] == "gbk" and "中文编码测试" in gbk.text, str(gbk.meta))
    broken = extractors.extract(fixtures["broken_txt"], "txt")
    check("txt 混合编码兜底为 replace 且不整份拒收",
          "replace" in broken.meta["encoding"] and broken.page_count == 1, str(broken.meta))
    md = extractors.extract(fixtures["md"], "md")
    check("md 与 txt 同一套读取（内容原样）", "# 标题" in md.text, md.text[:20])

    image_only = extractors.extract(fixtures["image_only_docx"], "docx")
    check("只有图的 docx 抽出来是空正文", image_only.text == "", repr(image_only.text[:20]))

    # ③ 端到端：HTTP 上传 → 后台抽取 → 正文覆盖 → 页可读
    scheduled: list[int] = []
    embedder.schedule = lambda item_id, *a, **k: scheduled.append(int(item_id))  # noqa: ARG005

    with TestClient(app) as client:
        docx_path = ROOT / "samples" / "python" / "course.docx"
        body = docx_path.read_bytes()
        started = time.monotonic()
        resp = client.post("/api/files", files={"file": ("course.docx", body)})
        cost = time.monotonic() - started
        check("上传 docx 返回 201 + running + task_id",
              resp.status_code == 201 and resp.json()["ocr_status"] == "running"
              and resp.json()["task_id"], resp.text[:160])
        check(f"上传 {cost:.2f} s 内返回（不等抽取）", cost < 3.0, f"{cost:.2f}s")
        item_id = resp.json()["item_id"]

        progress = _wait_until(
            lambda: (lambda p: p if p["status"] in ("done", "partial", "failed") else None)(
                client.get(f"/api/knowledge/{item_id}/ocr").json()),
            timeout=120,
        ) or client.get(f"/api/knowledge/{item_id}/ocr").json()
        check("docx 抽取收口为 done（1/1 页）",
              progress["status"] == "done" and progress["done_pages"] == 1, str(progress))

        page = client.get(f"/api/knowledge/{item_id}/pages/1").json()
        detail = client.get(f"/api/knowledge/{item_id}").json()
        check("页文字与抽取结果一致",
              page["text"].startswith("全国计算机等级考试") and page["source"] == "extract",
              page["text"][:30])
        check("抽取页没有页图，image_url 为 null", page["image_url"] is None, str(page["image_url"]))
        check("正文已被覆盖（不再是 [文件] 占位）",
              not detail["raw_content"].startswith("[文件] "), detail["raw_content"][:30])
        check("正文重建了 chunk", len(detail["chunks"]) > 0, f"{len(detail['chunks'])} 块")
        check("原件信息标了有文字层", detail["file"]["has_text_layer"] == 1,
              str(detail["file"]))
        check("整份读完后派了补向量", scheduled.count(item_id) == 1, str(scheduled))

        original = client.get(f"/api/knowledge/{item_id}/file")
        check("原件仍可下载（字节数一致）",
              original.status_code == 200 and len(original.content) == len(body),
              f"{original.status_code} / {len(original.content)} B")
        html_path = TMP / "pages" / str(detail["file"]["id"]) / "0001.html"
        check("docx HTML 落到 pages/<file_id>/0001.html", html_path.is_file(),
              str(html_path))

        again = client.post(f"/api/knowledge/{item_id}/ocr", json={})
        check("docx 也能「重新读取」（202，不是 409）", again.status_code == 202, again.text[:120])
        _wait_until(lambda: client.get(f"/api/knowledge/{item_id}/ocr").json()["status"]
                    != "running", timeout=60)

        # ④ 坏文件：状态 failed、不留半份正文
        bad = client.post("/api/files", files={
            "file": ("broken.docx", fixtures["bad_docx"].read_bytes())})
        bad_item = bad.json()["item_id"]
        bad_progress = _wait_until(
            lambda: (lambda p: p if p["status"] in ("failed", "done", "partial") else None)(
                client.get(f"/api/knowledge/{bad_item}/ocr").json()),
            timeout=60,
        ) or client.get(f"/api/knowledge/{bad_item}/ocr").json()
        check("坏 docx 收口为 failed", bad_progress["status"] == "failed", str(bad_progress))
        bad_detail = client.get(f"/api/knowledge/{bad_item}").json()
        check("坏 docx 正文保持占位（不留半份）",
              bad_detail["raw_content"].startswith("[文件] "), bad_detail["raw_content"][:30])

        # ⑤ 只有图的 docx：partial，且正文不覆盖（整理会照着空正文写笔记）
        img = client.post("/api/files", files={
            "file": ("image-only.docx", fixtures["image_only_docx"].read_bytes())})
        img_item = img.json()["item_id"]
        img_progress = _wait_until(
            lambda: (lambda p: p if p["status"] in ("failed", "done", "partial") else None)(
                client.get(f"/api/knowledge/{img_item}/ocr").json()),
            timeout=60,
        ) or client.get(f"/api/knowledge/{img_item}/ocr").json()
        check("只有图的 docx 收口为 partial", img_progress["status"] == "partial",
              str(img_progress))
        img_detail = client.get(f"/api/knowledge/{img_item}").json()
        check("只有图的 docx 正文仍为占位",
              img_detail["raw_content"].startswith("[文件] "), img_detail["raw_content"][:30])

        # ⑥ 截断不许说 done（T9.8 实测 261 行 xlsx 显示「已读取 1 页」）：
        # 页是齐的、内容是半份，界面上却看不出任何异常，整理会照着半份写笔记
        cut = client.post("/api/files", files={
            "file": ("long.xlsx", fixtures["xlsx"].read_bytes())})
        cut_item = cut.json()["item_id"]
        cut_progress = _wait_until(
            lambda: (lambda p: p if p["status"] in ("failed", "done", "partial") else None)(
                client.get(f"/api/knowledge/{cut_item}/ocr").json()),
            timeout=60,
        ) or client.get(f"/api/knowledge/{cut_item}/ocr").json()
        check("xlsx 超 200 行收口为 partial（不是 done）",
              cut_progress["status"] == "partial", str(cut_progress))




# ── §workspace（T9.9）──────────────────────────────────────────
def group_workspace() -> None:
    """工作区 CRUD 与四处计数口径。**不碰识别组件、不调模型**。

    这里只验接口层：界面上「左栏计数与筛选结果一致」在 `verify_m7.py` 的工作区那一组里
    （真浏览器），两处一起才算过完 T9.9。
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import tasks as task_queue

    with TestClient(app) as c:
        def make(text: str) -> int:
            return int(c.post("/api/knowledge", json={"raw_content": text}).json()["id"])

        # ① 建：名字上限 20、同名允许（用户叫两个「英语」不算错）
        a = c.post("/api/workspaces", json={"name": "数据结构"})
        b = c.post("/api/workspaces", json={"name": "英语二"})
        same = c.post("/api/workspaces", json={"name": "数据结构"})
        check("建工作区返回 201 且带 item_count",
              a.status_code == 201 and a.json()["item_count"] == 0, a.text[:120])
        check("同名允许（两个「数据结构」）",
              same.status_code == 201 and same.json()["id"] != a.json()["id"], same.text[:120])
        check("名字超过 20 字 422",
              c.post("/api/workspaces", json={"name": "x" * 21}).status_code == 422)
        check("空名字 422", c.post("/api/workspaces", json={"name": ""}).status_code == 422)
        check("name 是必填", c.post("/api/workspaces", json={}).status_code == 422)
        c.delete(f"/api/workspaces/{same.json()['id']}")     # 同名那个先删掉，后面只算两个

        ws_a, ws_b = int(a.json()["id"]), int(b.json()["id"])
        ids = [make(f"第 {i} 条内容，用来验工作区计数口径") for i in range(7)]
        for item_id in ids[:3]:
            c.patch(f"/api/knowledge/{item_id}", json={"workspace_id": ws_a})
        for item_id in ids[3:6]:
            c.patch(f"/api/knowledge/{item_id}", json={"workspace_id": ws_b})

        # ② 四处计数必须对齐：/workspaces、列表 total、状态计数、分类树
        listing = c.get("/api/workspaces").json()
        counts = {w["id"]: w["item_count"] for w in listing["items"]}
        check("工作区列表带内容数", counts == {ws_a: 3, ws_b: 3}, str(counts))
        check("none_count = 没有工作区的内容数",
              listing["none_count"] == 1, str(listing["none_count"]))
        check("总数守恒（各工作区 + 未归类 = 全部）",
              sum(counts.values()) + listing["none_count"] == 7, str(listing))
        check("列表按工作区筛出 3 条",
              c.get("/api/knowledge", params={"workspace_id": ws_a}).json()["total"] == 3)
        check("列表 workspace_id=none 只看未归类",
              c.get("/api/knowledge", params={"workspace_id": "none"}).json()["total"] == 1)
        check("workspace_id 不是数字时 422",
              c.get("/api/knowledge", params={"workspace_id": "abc"}).status_code == 422)
        scoped = c.get("/api/knowledge/categories", params={"workspace_id": ws_a}).json()
        check("状态计数跟着工作区收窄（3 条）", scoped["counts"]["total"] == 3,
              str(scoped["counts"]))
        check("分类树本身仍是全库（不收窄）",
              len(scoped["categories"]) == len(c.get("/api/knowledge/categories").json()["categories"]))
        check("未归类也能量（none）",
              c.get("/api/knowledge/categories",
                    params={"workspace_id": "none"}).json()["counts"]["total"] == 1)

        # ③ 列表项与会话详情都带 workspace_id（前端靠它显示「属于哪个工作区」）
        first = c.get("/api/knowledge", params={"workspace_id": ws_a}).json()["items"][0]
        check("列表项带 workspace_id", first.get("workspace_id") == ws_a, str(first))
        detail = c.get(f"/api/knowledge/{first['id']}").json()
        check("详情与列表的工作区一致", detail["workspace_id"] == ws_a, str(detail["workspace_id"]))

        # ④ 批量整理按工作区收窄（真派发会去调模型，这里只记派了谁）
        sent: list[dict] = []
        original = task_queue.submit
        task_queue.submit = lambda *args, **kw: (sent.append(args[2]), "fake-task")[1]
        try:
            resp = c.post("/api/knowledge/organize-pending", params={"workspace_id": ws_a})
        finally:
            task_queue.submit = original
        queued = {item["item_id"] for item in resp.json()["items"]}
        check("批量整理只取当前工作区的待整理",
              queued == set(ids[:3]) and len(sent) == 3, f"{sorted(queued)} / 派出 {len(sent)}")

        # ⑤ 改名 / 404
        renamed = c.patch(f"/api/workspaces/{ws_a}", json={"name": "数据结构（改）"})
        check("改名生效且回 item_count",
              renamed.status_code == 200 and renamed.json()["name"] == "数据结构（改）"
              and renamed.json()["item_count"] == 3, renamed.text[:120])
        check("改不存在的工作区 404",
              c.patch("/api/workspaces/99999", json={"name": "x"}).status_code == 404)
        check("移入不存在的工作区 404",
              c.patch(f"/api/knowledge/{ids[6]}", json={"workspace_id": 99999}).status_code == 404)

        # ⑥ 删工作区：内容回落「未归类」，一条都不删
        before_total = c.get("/api/knowledge").json()["total"]
        deleted = c.delete(f"/api/workspaces/{ws_b}")
        after_total = c.get("/api/knowledge").json()["total"]
        listing = c.get("/api/workspaces").json()
        check("删工作区返回 freed=false",
              deleted.status_code == 200 and deleted.json() == {"freed": False},
              deleted.text[:80])
        check("内容数不变（只移出不删）", after_total == before_total, str(before_total))
        check("被删工作区的内容回到未归类",
              listing["none_count"] == 4, str(listing["none_count"]))
        check("那些内容确实变回 NULL",
              c.get("/api/knowledge", params={"workspace_id": "none"}).json()["total"] == 4)
        check("删不存在的工作区 404", c.delete(f"/api/workspaces/{ws_b}").status_code == 404)


GROUPS = (
    ("layout", group_layout), ("resume", group_resume),
    ("extract", group_extract), ("workspace", group_workspace),
)


def main() -> int:
    global LIMIT
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    if "--pages" in sys.argv:
        LIMIT = int(sys.argv[sys.argv.index("--pages") + 1])
    print(f"Cairn M9 验收 · 临时数据目录 {TMP}")
    # 抽取（§extract）与工作区（§workspace）都不碰识别组件：
    # 单独跑它们时不该被"没构建组件"挡住
    if only not in ("extract", "workspace"):
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
