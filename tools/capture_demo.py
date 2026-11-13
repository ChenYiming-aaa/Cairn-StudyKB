#!/usr/bin/env python
"""重抓在线演示站的 `frontend/src/demo/fixtures.json`（发版前跑一次）。

**为什么需要它**：演示站（github.io）没有后端，`frontend/src/demo/index.js` 把
「真后端曾经返回过的响应」当数据源。M9 改了 `knowledge_item` 的形状（多 `kind` /
`workspace_id`）、详情多一个 `file`，还新加了 `/api/workspaces` —— 旧 fixture 里没有这些，
演示站左栏的「工作区」段会因为接口不存在而弹一句跟它无关的报错。

**怎么保证不是编的**：不手写假响应。把旧 fixture 里那 6 条内容（标题 / 正文 / 笔记 /
分块 id / 时间）原样灌进一个临时库，再用**真后端**把 GET 响应重新抓一遍。分块 id 不变，
所以问答来源与复习题里的 `item_id` / `chunk_id` 仍然指得着，其余段（任务、问答、复习、
学习页、统计）的形状 M9 没动，保持原样。

用法：
    python tools/capture_demo.py           # 抓并覆盖 fixtures.json
    python tools/capture_demo.py --check   # 只打印新形状与差异，不写文件
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
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


def _seed(fixtures: dict) -> None:
    """把旧 fixture 的 6 条内容灌进临时库（id 原样，别的表还指着它们）。"""
    from app.db.migrate import get_conn, init_db

    init_db()
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
                item_id = int(key)
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


def _capture(fixtures: dict) -> dict:
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
            resp = c.get(f"/api/knowledge/{key}")
            details[key] = resp.json()
        out["details"] = details
    out["captured_at"] = datetime.now(timezone.utc).isoformat()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="重抓演示站 fixtures.json")
    ap.add_argument("--check", action="store_true", help="只打印形状差异，不写文件")
    args = ap.parse_args()

    fixtures = _load()

    tmp = Path(tempfile.mkdtemp(prefix="cairn-demo-"))
    (tmp / ".env").write_text("LLM_API_KEY=sk-demo-capture-not-a-real-key\n", encoding="utf-8")
    os.environ["DATA_DIR"] = str(tmp)      # 必须早于 import app
    os.environ["VECTOR_ENABLED"] = "0"     # 演示数据不需要向量
    os.environ["CAIRN_ENV_STRICT"] = "1"
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    os.environ.setdefault("CAIRN_COMPONENT_MODE", "none")   # 不碰任何组件
    sys.path.insert(0, str(BACKEND))

    try:
        _seed(fixtures)
        fresh = _capture(fixtures)
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
