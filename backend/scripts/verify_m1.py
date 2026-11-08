"""T1.11 验收脚本：一次跑完 M1 §5 DoD 的机器可验部分。

用法：cd backend && uv run python scripts/verify_m1.py [--keep]
退出码：0 全绿 / 1 有用例失败 / 2 未配置 LLM Key（整理链路无法验证）

「残留」口径（2026-11-06 用户裁决）：DoD 说的 chunk_fts 无残留，指 SQL 查得到的东西——
主虚拟表按 rowid 查不到、按 MATCH 搜不到。影子表 chunk_fts_data 里还留着几个字节的明文 term
不算残留，只打印不判失败；因此也不必在删除路径执行 optimize 去直接动 chunk_fts（数据契约 §6）。

全程使用临时 DATA_DIR，不碰 data/data.db，末尾清理。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import replace
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-"))
os.environ["DATA_DIR"] = str(TMP)  # 必须早于 import app：get_settings() 首次调用即缓存
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

import app.config as config_mod  # noqa: E402
import app.db.conn as conn_mod  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import knowledge as knowledge_router  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures_m1 import TEXTS  # noqa: E402

DB = TMP / "data.db"
MARKER = "验收补充段落"
RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((ok, name))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


def sql(query: str, args: tuple = ()) -> list:
    with sqlite3.connect(DB, timeout=10) as conn:
        return conn.execute(query, args).fetchall()


def wait_task(client: TestClient, task_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task.get("status") in ("done", "failed"):
            return task
        time.sleep(0.5)
    return {"status": "timeout", "error_code": "TASK_TIMEOUT"}


def step_build_and_create(client: TestClient) -> list[dict]:
    step("1/8 建库与健康检查")
    health = client.get("/api/health")
    payload = health.json()
    check("GET /api/health 200", health.status_code == 200, str(payload))
    check("status=ok 且带 version",
          payload.get("status") == "ok" and bool(payload.get("version")), payload.get("version", ""))
    check("/docs 可打开", client.get("/docs").status_code == 200)
    from app.db.migrate import SCHEMA_VERSION

    check(f"已建库 user_version={SCHEMA_VERSION}",
          sql("PRAGMA user_version")[0][0] == SCHEMA_VERSION)
    check("journal_mode=WAL", str(sql("PRAGMA journal_mode")[0][0]).lower() == "wal")
    tables = {r[0] for r in sql("SELECT name FROM sqlite_master WHERE type='table'")}
    need = {"knowledge_item", "chunk", "chunk_fts", "agent_task", "llm_call_log", "ask_log"}
    check("关键表齐全", need <= tables, f"缺 {sorted(need - tables)}" if need - tables else "")

    step("2/8 造 3 条（自动切块）")
    created: list[dict] = []
    for title, body in TEXTS:
        resp = client.post("/api/knowledge", json={"title": title, "raw_content": body})
        item = resp.json()
        created.append(item)
        check(f"创建「{title}」201/pending/chunk>1",
              resp.status_code == 201 and item.get("status") == "pending" and item.get("chunk_count", 0) > 1,
              f"status={item.get('status')} chunk={item.get('chunk_count')} 文本 {len(body)} 字")
    check("raw chunk 已落库", sql("SELECT COUNT(*) FROM chunk WHERE source='raw'")[0][0] >= 6)
    return created


def step_organize(client: TestClient, created: list[dict]) -> None:
    step("3/8 整理（真实 LLM 调用）")
    resp = client.post(f"/api/knowledge/{created[0]['id']}/organize")
    check("POST /{id}/organize 202", resp.status_code == 202, str(resp.json()))
    task = wait_task(client, resp.json().get("task_id", ""))
    check("单条整理任务 done", task.get("status") == "done", task.get("error_code") or "")

    resp = client.post("/api/knowledge/organize-pending")
    batch = resp.json()
    check("organize-pending 命中剩余 2 条", resp.status_code == 200 and batch.get("total") == 2,
          f"total={batch.get('total')}")
    for queued in batch.get("items", []):
        task = wait_task(client, queued["task_id"])
        check(f"条目 {queued['item_id']} 整理 done", task.get("status") == "done",
              task.get("error_code") or "")

    for item in created:
        detail = client.get(f"/api/knowledge/{item['id']}").json()
        filled = (detail["status"] == "ready" and detail["summary"].strip()
                  and len(detail["key_points"]) >= 2 and detail["structured_note"].strip()
                  and (detail["category"] or "").strip() and detail["tags"])
        check(f"条目 {item['id']} 五字段非空且 ready", filled,
              f"category={detail['category']} tags={len(detail['tags'])} points={len(detail['key_points'])}")
        check(f"条目 {item['id']} 标题由 AI 重写且 ≤20 字",
              0 < len(detail["title"]) <= 20 and "\n" not in detail["title"],
              f"{len(detail['title'])} 字：{detail['title']}")
        note_chunks = [c for c in detail["chunks"] if c["source"] == "note"]
        check(f"条目 {item['id']} 产出 note chunk 且 note_edited=0",
              len(note_chunks) > 0 and detail["note_edited"] == 0,
              f"note chunk {len(note_chunks)}，note_edited={detail['note_edited']}")


def step_edit_note(client: TestClient, item_id: int) -> None:
    step("4/8 改笔记 → 断言 chunk 重建")
    before = client.get(f"/api/knowledge/{item_id}").json()
    old_ids = {c["id"] for c in before["chunks"] if c["source"] == "note"}
    new_note = before["structured_note"] + f"\n\n## 我的补充\n\n{MARKER}：这一段由验收脚本追加，用来验证重建。\n"
    resp = client.patch(f"/api/knowledge/{item_id}", json={"structured_note": new_note})
    body = resp.json()
    check("PATCH 200 且 note_edited=1", resp.status_code == 200 and body.get("note_edited") == 1, str(body))

    after = client.get(f"/api/knowledge/{item_id}").json()
    new_ids = {c["id"] for c in after["chunks"] if c["source"] == "note"}
    check("刷新后笔记内容仍在", MARKER in after["structured_note"])
    check("note chunk 数量 > 0（SQL 查证）",
          sql("SELECT COUNT(*) FROM chunk WHERE item_id=? AND source='note'", (item_id,))[0][0] > 0)
    check("旧 note chunk 已删除", old_ids.isdisjoint(new_ids), f"旧 {len(old_ids)} 新 {len(new_ids)}")
    check("新笔记已进 chunk", any(MARKER in c["content"] for c in after["chunks"]))
    hits = sql("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH ?", (MARKER,))[0][0]
    check("FTS 能搜到新笔记", hits > 0, f"{hits} 命中")

    renamed = "验收手改过的标题"
    resp = client.patch(f"/api/knowledge/{item_id}", json={"title": renamed})
    current = client.get(f"/api/knowledge/{item_id}").json()["title"]
    check("PATCH 标题生效且刷新后仍在", resp.status_code == 200 and current == renamed, current)
    resp = client.patch(f"/api/knowledge/{item_id}", json={"title": "标" * 21})
    check("PATCH 标题超 20 字被拒（422）", resp.status_code == 422, f"{resp.status_code}")


def step_filters(client: TestClient, item_id: int) -> None:
    step("5/8 分类 / 标题搜索 / 标签筛选")
    detail = client.get(f"/api/knowledge/{item_id}").json()
    category, tag = detail["category"], detail["tags"][0]
    listed = client.get("/api/knowledge", params={"category": category}).json()
    check(f"category={category} 过滤生效",
          listed["total"] >= 1 and all(i["category"] == category for i in listed["items"]),
          f"total={listed['total']}")
    expected = sql("SELECT COUNT(*) FROM knowledge_item WHERE category=?", (category,))[0][0]
    check("分类计数与 SQL 一致", listed["total"] == expected, f"API {listed['total']} / SQL {expected}")
    keyword = detail["title"][:4]
    found = client.get("/api/knowledge", params={"q": keyword}).json()
    check(f"标题搜索 q={keyword} 命中", any(i["id"] == item_id for i in found["items"]),
          f"total={found['total']}")
    tagged = client.get("/api/knowledge", params={"tag": tag, "page_size": 100}).json()
    check(f"tag={tag} 命中", any(i["id"] == item_id for i in tagged["items"]), f"total={tagged['total']}")

    # 分类树聚合端点（M1 补丁遗留项：之前只有 e2e 覆盖，后端没断言）
    tree = client.get("/api/knowledge/categories")
    payload = tree.json() if tree.status_code == 200 else {}
    check("GET /api/knowledge/categories 200", tree.status_code == 200, str(tree.status_code))
    node = next((c for c in payload.get("categories", []) if c["name"] == category), None)
    check(f"分类树里 {category} 的计数与过滤 total 一致",
          node is not None and node["count"] == listed["total"],
          f"tree {node and node['count']} / list {listed['total']}")
    all_items = client.get("/api/knowledge", params={"page_size": 1}).json()
    check("分类树 counts.total 与列表 total 一致",
          payload.get("counts", {}).get("total") == all_items["total"],
          f"tree {payload.get('counts', {}).get('total')} / list {all_items['total']}")


def unique_phrase(item_id: int) -> str:
    """从待删条目的 raw chunk 里挑一段 8 字窗口，且其他条目都不含这段文字。

    直接用「间隔重复」这类词会误判：另外两篇里也有同样四个字，MATCH 命中属于真实内容，
    不是残留。所以探针必须只存在于待删条目里。
    """
    text = sql("SELECT content FROM chunk WHERE item_id=? AND source='raw' ORDER BY position",
               (item_id,))[0][0]
    others = [r[0] for r in sql("SELECT content FROM chunk WHERE item_id<>?", (item_id,))]
    for i in range(0, len(text) - 8):
        candidate = text[i:i + 8]
        if "\n" not in candidate and all(candidate not in other for other in others):
            return candidate
    return text[:8]


def step_delete(client: TestClient, item_id: int) -> None:
    step("6/8 删条目 → 查残留（只认 SQL 可查询）")
    chunk_ids = [r[0] for r in sql("SELECT id FROM chunk WHERE item_id=?", (item_id,))]
    probe = unique_phrase(item_id)
    check("删除前该条目有 chunk", len(chunk_ids) > 0, f"{len(chunk_ids)} 块")
    check("探针文字删除前可搜到",
          sql("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH ?", (probe,))[0][0] > 0, probe)
    resp = client.delete(f"/api/knowledge/{item_id}")
    check("DELETE 200", resp.status_code == 200, str(resp.json()))
    left_chunk = sql("SELECT COUNT(*) FROM chunk WHERE item_id=?", (item_id,))[0][0]
    left_index = sum(sql("SELECT COUNT(*) FROM chunk_fts WHERE rowid=?", (cid,))[0][0] for cid in chunk_ids)
    left_match = sql("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH ?", (probe,))[0][0]
    check("chunk 无残留", left_chunk == 0, f"{left_chunk} 行")
    check("chunk_fts 按 rowid 查无残留", left_index == 0, f"{left_index} 行")
    check("chunk_fts 按 MATCH 查无残留", left_match == 0, f"探针「{probe}」{left_match} 命中")
    shadow = sql("SELECT COALESCE(SUM(length(block)),0) FROM chunk_fts_data")[0][0]
    print(f"    [INFO] chunk_fts_data 里还有 {shadow} 字节明文 term（裁决：不计入残留）")
    for item in client.get("/api/knowledge", params={"page_size": 100}).json()["items"]:
        client.delete(f"/api/knowledge/{item['id']}")
    total_chunk, total_fts = sql("SELECT COUNT(*) FROM chunk")[0][0], sql("SELECT COUNT(*) FROM chunk_fts")[0][0]
    check("清空后 chunk 与 chunk_fts 均为 0", total_chunk == 0 and total_fts == 0,
          f"chunk={total_chunk} fts={total_fts}")


def step_no_key(client: TestClient) -> None:
    step("7/8 未配置 Key → LLM_NO_KEY，服务不崩")
    real = config_mod.get_settings
    knowledge_router.get_settings = lambda: replace(real(), llm_api_key="")
    try:
        probe = client.post("/api/knowledge", json={
            "title": "无 Key 探针", "raw_content": "这是一条用于验证未配置 Key 时整理行为的探针文本。",
        }).json()
        # 只数 organize 任务：向量索引任务（index_embed）由后台按需派发，
        # 拿全表总数做前后对比会被它干扰，断言就成了随机红。（2026-11-08 修 M1 遗留 1）
        queued_before = sql("SELECT COUNT(*) FROM agent_task WHERE type='organize'")[0][0]
        resp = client.post(f"/api/knowledge/{probe['id']}/organize")
        err = resp.json().get("error", {})
        check("整理返回 400 LLM_NO_KEY", resp.status_code == 400 and err.get("code") == "LLM_NO_KEY",
              f"{resp.status_code} {err.get('code')}")
        check("失败后服务仍健康", client.get("/api/health").json().get("status") == "ok")
        queued_after = sql("SELECT COUNT(*) FROM agent_task WHERE type='organize'")[0][0]
        check("未留下注定失败的任务（无 Key 时不派发 organize）",
              queued_after == queued_before, f"organize 任务 {queued_before} → {queued_after}")
        doomed = sql("SELECT COUNT(*) FROM agent_task WHERE error_code='LLM_NO_KEY'")[0][0]
        check("没有记着 LLM_NO_KEY 的失败任务", doomed == 0, f"{doomed} 条")
        client.delete(f"/api/knowledge/{probe['id']}")
    finally:
        knowledge_router.get_settings = real


def step_copy_db() -> None:
    step("8/8 data.db 整文件复制 → status.py 可打开")
    with sqlite3.connect(DB, timeout=10) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    copy = TMP / "copy.db"
    shutil.copy(DB, copy)
    proc = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "status.py"), "--db", str(copy)],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
    )
    check("status.py --db 退出码 0", proc.returncode == 0, (proc.stderr or proc.stdout)[-160:])
    check("复制品读到表结构", "knowledge_item" in proc.stdout)


def cleanup(keep: bool) -> None:
    if keep:
        print(f"\n临时数据目录已保留：{TMP}")
        return
    if conn_mod._keepalive is not None:
        conn_mod._keepalive.close()
        conn_mod._keepalive = None
    shutil.rmtree(TMP, ignore_errors=True)


def main() -> int:
    keep = "--keep" in sys.argv[1:]
    print("=" * 62)
    print("  Cairn · M1 验收（T1.11）")
    print("=" * 62)
    print(f"临时数据目录：{TMP}")
    if not config_mod.get_settings().has_llm_key:
        print("\n未配置 LLM_API_KEY：整理链路无法验证，先补 .env 再重跑。")
        cleanup(keep)
        return 2

    aborted = ""
    try:
        with TestClient(app) as client:
            created = step_build_and_create(client)
            step_organize(client, created)
            step_edit_note(client, created[0]["id"])
            step_filters(client, created[0]["id"])
            step_delete(client, created[0]["id"])
            step_no_key(client)
            step_copy_db()
    except Exception as exc:  # 任何未捕获异常都算验收失败，不能静默
        aborted = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
    finally:
        cleanup(keep)

    passed = sum(1 for ok, _ in RESULTS if ok)
    failed = [name for ok, name in RESULTS if not ok]
    print("\n" + "=" * 62)
    print(f"  结果：{passed}/{len(RESULTS)} PASS")
    if aborted:
        print(f"  中断：{aborted}")
    for name in failed:
        print(f"    - 失败：{name}")
    print("=" * 62)
    return 0 if not aborted and not failed and RESULTS else 1


if __name__ == "__main__":
    sys.exit(main())
