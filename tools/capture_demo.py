#!/usr/bin/env python
"""重抓在线演示站的 `frontend/src/demo/fixtures.json`（发版前跑一次）。

**为什么需要它**：演示站（github.io）没有后端，`frontend/src/demo/index.js` 把
「真后端曾经返回过的响应」当数据源。后端每加一层形状，旧 fixture 就跟不上 ——
M9 加了 `kind` / `workspace_id` / 详情里的 `file`，M11 又加了页文字与定位，v0.3 的
三类原件（PDF / Word 内嵌图 / 试卷）在演示站里一条都没有。

**怎么保证不是编的**：不手写假响应。
- 文本那 6 条：把旧 fixture 原样灌进临时库，再用**真后端**把 GET 响应重抓一遍。
  分块 id 不变，问答来源与复习题里的 `item_id` / `chunk_id` 仍指得着。
- 原件那三条（`--with-files`）：**真上传** `samples/python/` 里的 PDF / Word / 试卷，
  真识别、真渲染页图，把 detail / pages / 页图 / 内嵌图一起导出来。
  页文字与页图出自同一份原件，所以演示站上点引用能真落到那一段 —— 这正是要证明的东西。

用法：
    python tools/capture_demo.py                 # 只重抓文本那几段（不联网、不碰组件）
    python tools/capture_demo.py --with-files    # 加上真上传 PDF / Word / 试卷（要本机能跑 OCR）
    python tools/capture_demo.py --check         # 只打印新形状与差异，不写文件
"""
from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FIXTURES = ROOT / "frontend" / "src" / "demo" / "fixtures.json"

# 演示站里那两个工作区：名字刻意与「分类」不同（工作区是用户自己划的抽屉，分类是机器给的）
WORKSPACES = [
    ("英语二", "#3F6F5F", [1, 2, 3]),
    ("期末考试", "#8A6C3B", [5, 6]),
]


def _load() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _seed(fixtures: dict) -> set[int]:
    """把旧 fixture 里**纯文本**那几条灌进临时库（id 原样，别的表还指着它们）。

    原件类（`file` 非空）不灌：它们每次都由 `--with-files` 重新真上传，
    灌进来只会让 id 一路往上漂（跑第二遍就变成 7..12、第三遍 7..15）。
    返回真正灌进去的 id 集合，`_capture` 只重抓这批 —— 其余的在新库里不存在。
    """
    from app.db.migrate import get_conn, init_db

    init_db()
    kept: set[int] = set()
    conn = get_conn()
    try:
        with conn:
            for idx, (name, color, _) in enumerate(WORKSPACES, start=1):
                conn.execute(
                    """INSERT INTO workspace (id, name, color, sort_order, created_at, updated_at)
                       VALUES (?, ?, ?, ?, '2026-11-08T19:40:00+08:00', '2026-11-08T19:40:00+08:00')""",
                    (idx, name, color, idx),
                )

            home = {item_id: ws_id for ws_id, (_, _, ids) in enumerate(WORKSPACES, start=1) for item_id in ids}

            for key, detail in sorted(fixtures["details"].items(), key=lambda kv: int(kv[0])):
                if detail.get("file"):
                    continue          # 原件类：这次会真上传，不用旧数据
                item_id = int(key)
                kept.add(item_id)
                conn.execute(
                    """INSERT INTO knowledge_item
                       (id, title, source_type, source_url, raw_content, content_hash, summary,
                        key_points, structured_note, note_edited, category, tags, status, truncated,
                        created_at, updated_at, workspace_id, kind)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'material')""",
                    (
                        item_id,
                        detail["title"],
                        detail.get("source_type") or "text",
                        detail.get("source_url"),
                        detail.get("raw_content") or "",
                        detail.get("content_hash") or f"demo-{item_id}",
                        detail.get("summary") or "",
                        json.dumps(detail.get("key_points") or [], ensure_ascii=False),
                        detail.get("structured_note") or "",
                        int(detail.get("note_edited") or 0),
                        detail.get("category"),
                        json.dumps(detail.get("tags") or [], ensure_ascii=False),
                        detail.get("status") or "ready",
                        int(detail.get("truncated") or 0),
                        detail.get("created_at") or "2026-11-08T19:47:47+08:00",
                        detail.get("updated_at") or detail.get("created_at") or "2026-11-08T19:47:47+08:00",
                        home.get(item_id),
                    ),
                )
                for chunk in detail.get("chunks") or []:
                    conn.execute(
                        "INSERT INTO chunk (id, item_id, position, content, source) VALUES (?,?,?,?,?)",
                        (
                            int(chunk["id"]),
                            item_id,
                            int(chunk.get("position") or 0),
                            chunk.get("content") or "",
                            chunk.get("source") or "raw",
                        ),
                    )
    finally:
        conn.close()
    return kept


def _capture(fixtures: dict, keep: set[int]) -> dict:
    """用真后端把会变形的几段重抓一遍。"""
    from fastapi.testclient import TestClient

    from app.main import app

    out = dict(fixtures)
    with TestClient(app) as c:
        out["health"] = c.get("/api/health").json()
        out["env"] = c.get("/api/env/check").json()
        out["categories"] = c.get("/api/knowledge/categories").json()
        out["items"] = c.get("/api/knowledge", params={"page_size": 50}).json()
        out["workspaces"] = c.get("/api/workspaces").json()
        details = {}
        for key in fixtures["details"]:
            if int(key) not in keep:
                continue      # 原件类不在这里抓：每次都由 _capture_files 真上传
            resp = c.get(f"/api/knowledge/{key}")
            details[key] = resp.json()
        out["details"] = details
    out["captured_at"] = datetime.now(timezone.utc).isoformat()
    return out


# ── 原件那三条（v0.3：PDF / Word 内嵌图 / 试卷）────────────
#
# 这三条不能像文本那样「灌旧数据再重抓」：页文字与页图必须出自同一份原件，
# 否则演示站上点引用会落到别处 —— 那比不放这个功能更糟。

ASSETS_DIR = ROOT / "frontend" / "public" / "demo"
SAMPLES = ROOT / "samples" / "python"


def _wait_ocr(c, item_id: int, timeout: float = 600.0) -> dict:
    end = time.time() + timeout
    started = time.time()
    while time.time() < end:
        got = c.get(f"/api/knowledge/{item_id}/ocr").json()
        if got.get("status") in ("done", "partial", "failed"):
            print(f"    识别 {got.get('status')}，用时 {time.time() - started:.0f} s")
            return got
        time.sleep(1)
    raise RuntimeError("识别超时（10 分钟）")


def _upload(c, path: Path, name: str | None = None) -> dict:
    """上传一份原件。`name` 可换文件名 —— 试卷的标题就取它（`commit` 不改标题），
    传 `exam.pdf` 上去，演示站侧栏就只会看到一条叫「exam」的内容。"""
    filename = name or path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with path.open("rb") as fh:
        resp = c.post("/api/files", files={"file": (filename, fh, mime)})
    if resp.status_code >= 400:
        raise RuntimeError(f"上传失败 {resp.status_code}：{resp.text[:200]}")
    return resp.json()


def _export(c, item_id: int, detail: dict, pages: dict, tag: str) -> dict:
    """把页图、原件、Word 内嵌图导到 `public/demo/`，返回演示层要的地址表。

    Word 的版式 HTML 在 `/pages/1` 里（不在详情里），图以 `/api/knowledge/{id}/assets/<hash>` 引用；
    fixtures 里**保留原样**（那是后端真返回的东西，改了就不再是"抓下来的"），
    由演示层在返回响应时把地址换成静态文件，见 `demo/index.js` 的 `rewriteAssets()`。
    """
    import re

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    file = detail.get("file") or {}
    ext = (file.get("ext") or "").lower()
    page_images: list[str] = []

    for n in range(1, int(file.get("page_count") or 0) + 1):
        got = c.get(f"/api/knowledge/{item_id}/file", params={"page": n})
        if got.status_code != 200:
            continue
        name = f"{tag}-p{n}.jpg"
        (ASSETS_DIR / name).write_bytes(got.content)
        page_images.append(name)

    out: dict = {"page_images": page_images, "original": "", "images": {}}

    if ext == "pdf":
        got = c.get(f"/api/knowledge/{item_id}/file")
        if got.status_code == 200:
            (ASSETS_DIR / f"{tag}.pdf").write_bytes(got.content)
            out["original"] = f"{tag}.pdf"
    elif ext in ("png", "jpg", "jpeg", "webp"):
        got = c.get(f"/api/knowledge/{item_id}/file")
        if got.status_code == 200:
            (ASSETS_DIR / f"{tag}-original.{ext}").write_bytes(got.content)
            out["original"] = f"{tag}-original.{ext}"

    # Word 内嵌图：从净化过的版式 HTML 里认出附件名（地址形如 /api/knowledge/8/assets/<hash>.jpg）
    html = "".join((p or {}).get("html") or "" for p in pages.values())
    for name in sorted(set(re.findall(
            r"/api/knowledge/\d+/assets/([0-9a-f]+\.(?:png|jpe?g|gif|webp))", html))):
        got = c.get(f"/api/knowledge/{item_id}/assets/{name}")
        if got.status_code != 200:
            print(f"    图 {name} 取不到（{got.status_code}）")
            continue
        flat = f"{tag}-{name}"
        (ASSETS_DIR / flat).write_bytes(got.content)
        out["images"][name] = flat
        print(f"    导出图 {flat}（{len(got.content) // 1024} KB）")
    return out


def _capture_one(c, path: Path, tag: str) -> dict:
    print(f"  [{tag}] {path.name}")
    up = _upload(c, path)
    item_id = int(up["item_id"])
    print(f"    item {item_id} · {up.get('page_count')} 页 · {up.get('ocr_status')}")
    if up.get("ocr_status") == "running":
        _wait_ocr(c, item_id)

    detail = c.get(f"/api/knowledge/{item_id}").json()
    file = detail.get("file") or {}
    pages: dict[str, dict] = {}
    for n in range(1, int(file.get("page_count") or 0) + 1):
        got = c.get(f"/api/knowledge/{item_id}/pages/{n}")
        if got.status_code == 200:
            pages[str(n)] = got.json()
    print(f"    {len(pages)} 页文字 · {len(detail.get('chunks') or [])} 个分块")

    # 整理：演示站上这几条要像「已经整理过的内容」，否则侧栏全是待整理
    org = c.post(f"/api/knowledge/{item_id}/organize")
    if org.status_code in (200, 202):
        task_id = org.json().get("task_id")
        end = time.time() + 240
        while task_id and time.time() < end:
            task = c.get(f"/api/tasks/{task_id}").json()
            if task.get("status") in ("done", "failed"):
                print(f"    整理 {task.get('status')}"
                      f"{'：' + str(task.get('error_msg'))[:80] if task.get('error_msg') else ''}")
                break
            time.sleep(2)
        detail = c.get(f"/api/knowledge/{item_id}").json()
    else:
        print(f"    整理没派上（{org.status_code}），保留待整理状态")

    assets = _export(c, item_id, detail, pages, tag)
    return {"item_id": item_id, "detail": detail, "pages": pages, "assets": assets}


def _capture_exam(c, path: Path) -> dict:
    """试卷：上传 → 规则切题（use_llm=False，不联网）→ 复核写入。"""
    # 标题就取文件名（`commit` 不会改它），所以这里给一个像真的卷名
    shown = "二级Python模拟卷.pdf"
    print(f"  [exam] {path.name} → {shown}")
    up = _upload(c, path, shown)
    file_id = int(up["file_id"])
    if up.get("ocr_status") == "running":
        _wait_ocr(c, int(up["item_id"]))

    parsed = c.post("/api/exams/parse", json={"file_id": file_id, "use_llm": False}).json()
    drafts = parsed.get("drafts") or []
    print(f"    切出 {len(drafts)} 道题（{parsed.get('stats')}）")
    if not drafts:
        raise RuntimeError("一道题都没切出来")
    done = c.post("/api/exams/commit", json={"file_id": file_id, "drafts": drafts})
    if done.status_code >= 400:
        raise RuntimeError(f"写入失败 {done.status_code}：{done.text[:200]}")
    made = done.json()
    print(f"    写入 item {made.get('item_id')}（{made.get('imported')} 题）")

    detail = c.get(f"/api/knowledge/{made['item_id']}").json()
    paper = c.get(f"/api/quiz/paper/{made['item_id']}").json()
    return {"item_id": made["item_id"], "detail": detail, "paper": paper,
            "commit": made}


def _capture_files(out: dict) -> None:
    """真上传三份原件，把结果并进 fixtures（`details` / `pages` / `files` 三个键）。

    `pages` / `files` **重建而不是继承**：原件每次重传，旧的页号映射留着只会指向
    上一次的 item id（跑两遍就多出一批指向不存在内容的页文字）。
    """
    from fastapi.testclient import TestClient

    from app.main import app

    # 先清掉上一次导出的页图与内嵌图（mindmap / page-*.html 是手工放进去的，别动）
    for stale in ASSETS_DIR.glob("pdf-*.jpg"):
        stale.unlink()
    for stale in ASSETS_DIR.glob("docx-*"):
        stale.unlink()
    if (ASSETS_DIR / "pdf.pdf").exists():
        (ASSETS_DIR / "pdf.pdf").unlink()

    pages: dict = {}
    files: dict = {}
    details = dict(out.get("details") or {})

    with TestClient(app) as c:
        for tag, name in (("pdf", "twocol.pdf"), ("docx", "course.docx")):
            src = SAMPLES / name
            if not src.is_file():
                print(f"  缺样本 {src}，跳过")
                continue
            got = _capture_one(c, src, tag)
            details[str(got["item_id"])] = got["detail"]
            pages[str(got["item_id"])] = got["pages"]
            files[tag] = {"item_id": got["item_id"], "assets": got["assets"]}

        exam = SAMPLES / "exam.pdf"
        if exam.is_file():
            got = _capture_exam(c, exam)
            details[str(got["item_id"])] = got["detail"]
            pages[str(got["item_id"])] = {}
            files["exam"] = {"item_id": got["item_id"], "paper": got["paper"],
                             "assets": {"page_images": [], "original": "", "images": {}}}

        # 列表要跟着刷新，否则侧栏看不到刚上传的三条
        out["items"] = c.get("/api/knowledge", params={"page_size": 50}).json()
        out["categories"] = c.get("/api/knowledge/categories").json()
        out["workspaces"] = c.get("/api/workspaces").json()

    out["details"] = details
    out["pages"] = pages
    out["files"] = files


def _project_key() -> str:
    """把项目根的 `LLM_API_KEY` 搬进临时数据目录。

    只有 `--with-files` 要它 —— 上传后的三条内容要真整理一次，否则演示站侧栏全是
    「待整理」。严格模式（`CAIRN_ENV_STRICT=1`）只读数据目录下的 `.env`，所以必须搬。
    **临时目录用完立刻删**；拿不到 Key 就跳过整理，演示站显示「待整理」也不算错。
    """
    env = ROOT / ".env"
    if not env.is_file():
        return ""
    for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("LLM_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="重抓演示站 fixtures.json")
    ap.add_argument("--check", action="store_true", help="只打印形状差异，不写文件")
    ap.add_argument("--with-files", action="store_true",
                    help="真上传 samples 里的 PDF / Word / 试卷（要本机能跑 OCR）")
    args = ap.parse_args()

    fixtures = _load()

    tmp = Path(tempfile.mkdtemp(prefix="cairn-demo-"))
    key = _project_key() if args.with_files else ""
    (tmp / ".env").write_text(
        f"LLM_API_KEY={key}\n" if key else "LLM_API_KEY=sk-demo-capture-not-a-real-key\n",
        encoding="utf-8")
    os.environ["DATA_DIR"] = str(tmp)      # 必须早于 import app
    os.environ["VECTOR_ENABLED"] = "0"     # 演示数据不需要向量
    os.environ["CAIRN_ENV_STRICT"] = "1"
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    if not args.with_files:
        os.environ.setdefault("CAIRN_COMPONENT_MODE", "none")   # 不碰任何组件
    sys.path.insert(0, str(BACKEND))

    try:
        keep = _seed(fixtures)
        fresh = _capture(fixtures, keep)
        if args.with_files:
            print("真上传三类原件")
            if not key:
                print("  没找到 LLM_API_KEY：整理会跳过，演示站显示「待整理」")
            _capture_files(fresh)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    before = set(fixtures["details"]["6"])
    after = set(fresh["details"]["6"])
    print("详情新增字段:", sorted(after - before) or "（无）")
    print("详情消失字段:", sorted(before - after) or "（无）")
    print("条目字段:", sorted(fresh["items"]["items"][0]))
    print("工作区:", [(w["name"], w["item_count"]) for w in fresh["workspaces"]["items"]],
          "未归类", fresh["workspaces"].get("none_count"))
    print("分类计数:", fresh["categories"]["counts"])

    if args.check:
        print("\n--check：没有写文件")
        return 0

    FIXTURES.write_text(
        json.dumps(fresh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n已写入 {FIXTURES.relative_to(ROOT)}（{FIXTURES.stat().st_size // 1024} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
