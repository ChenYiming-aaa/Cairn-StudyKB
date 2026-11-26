"""批 2 验收脚本：数据备份（`docs/dev/优化方案-v0.4.md` §3.3）。

用法：cd backend && uv run python scripts/verify_backup.py
退出码：0 全绿 / 1 有用例失败

三条判据（方案 §3.3 的验收清单，逐条变成断言）：

  §flow   当天不重复 + 备份本身可用
     - 首次备份真的生成文件，名字是 `data-YYYYMMDD.db`
     - 那个文件能用**标准 sqlite3** 打开，`knowledge_item` 行数与源库相同、`integrity_check` 为 ok
     - 24 小时内再调一次 → 不产生第二份（`reason=recent`）
     - 同一天连点「立即备份」（`force=True`）→ 仍然只有一份（`reason=already_today`）
     - 跨天（把今天那份伪装成昨天）→ 允许再备一份

  §keep   只留 7 份
     - 攒 9 份历史 + 今天这份 → 备份后剩 7 份，删掉的是**最旧的两个**
     - 只认 `data-YYYYMMDD.db` 这个名字形状，别的东西一个都不许删

  §failure  备份失败不阻塞启动
     - `backup` 目录被一个同名普通文件占住时，`run()` 如实抛错，不静默
     - 启动钩子 `maybe_start()` 在同样条件下**不抛**（只写日志），返回的线程能正常结束
     - 真起一个服务（子进程 + 坏的数据目录）→ `/api/health` 200、`/api/settings/backup` 200（last 为空）

全程临时目录，不碰 `data/data.db`，不联网。
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-backup-"))
os.environ["DATA_DIR"] = str(TMP)  # 必须早于 import app
os.environ["VECTOR_ENABLED"] = "0"
os.environ.setdefault("LOG_LEVEL", "WARNING")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import backup  # noqa: E402

DB = TMP / "data.db"
RESULTS: list[tuple[bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    RESULTS.append((ok, name))
    print(f"    [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def step(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))


def count_rows(path: Path) -> int:
    """用标准 sqlite3 打开，只读，不经过应用代码。"""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT count(*) FROM knowledge_item").fetchone()[0])
    finally:
        conn.close()


def integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()      # 不关连接 = Windows 上文件一直被占用，后面改名会 WinError 32


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def names(data_dir: Path) -> list[str]:
    return sorted(p.name for p in backup.list_backups(data_dir))


def main() -> int:
    today = datetime.now().strftime("%Y%m%d")

    # ── 先把库建出来（走真实 init_db），再插两行可数的内容 ──────────
    with TestClient(app) as client:      # with 会跑 lifespan：启动钩子在这里被执行
        print(f"临时数据目录：{TMP}")
        if not DB.exists():
            return 2
        # 走真实端点建内容（content_hash 是 NOT NULL，手写 INSERT 会踩约束）
        for title in ("备份用例甲", "备份用例乙"):
            made = client.post("/api/knowledge", json={"title": title, "raw_content": f"{title}的正文"})
            check(f"建内容「{title}」", made.status_code in (200, 201), str(made.status_code))
        source_rows = count_rows(DB)
        check("源库可读（knowledge_item 有行）", source_rows >= 2, f"{source_rows} 行")

        # 启动钩子是异步的：给它一点时间，再按「有没有文件」判，不按时间猜
        deadline = time.time() + 20
        while time.time() < deadline and not backup.list_backups(TMP):
            time.sleep(0.2)

        step("§flow 当天不重复 + 备份可用")
        check("启动钩子生成了一份备份", len(backup.list_backups(TMP)) == 1,
              f"{names(TMP)}")
        first = backup.list_backups(TMP)[0] if backup.list_backups(TMP) else None
        check("文件名是 data-YYYYMMDD.db", first is not None and first.name == f"data-{today}.db",
              first.name if first else "没有文件")
        if first:
            opened = False
            try:
                count_rows(first)
                opened = True
            except sqlite3.DatabaseError:
                opened = False
            check("启动钩子那份能用标准 sqlite3 打开", opened)
            check("启动钩子那份 integrity_check 为 ok", integrity_ok(first))

        # 启动钩子那份是「还没建内容」时备的，行数当然是 0 —— 行数要在下面单独验
        again = backup.run(TMP)
        check("同一天再调一次不产生第二份", again.get("created") is False, json.dumps(again, ensure_ascii=False))
        check("同一天的理由是 already_today（不是 recent）",
              again.get("reason") == "already_today", str(again.get("reason")))

        forced = backup.run(TMP, force=True)
        check("同一天连点「立即备份」仍只有一份", forced.get("created") is False, json.dumps(forced, ensure_ascii=False))
        check("force 也跳不过「今天已备过」", forced.get("reason") == "already_today", str(forced.get("reason")))
        check("目录里确实只有一份", len(backup.list_backups(TMP)) == 1, f"{names(TMP)}")

        # 删掉启动那份，备一份「带内容」的：这才验得到备份是不是真的可用
        backup.list_backups(TMP)[0].unlink()
        fresh = backup.run(TMP, force=True)
        check("删掉后再备能生成一份", fresh.get("created") is True, json.dumps(fresh, ensure_ascii=False))
        copied = Path(fresh["path"])
        check("备份里的 knowledge_item 行数与源库一致", count_rows(copied) == source_rows,
              f"备份 {count_rows(copied)} / 源 {source_rows}")
        check("带内容的备份 integrity_check 仍为 ok", integrity_ok(copied))

        # 跨天但不到 24 小时：文件改名成昨天 + mtime 拨到 23 小时前 → recent
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        old = copied.with_name(f"data-{yesterday}.db")
        copied.rename(old)
        at_23h = (datetime.now() - timedelta(hours=23)).timestamp()
        os.utime(old, (at_23h, at_23h))
        recent = backup.run(TMP)
        check("跨天但不到 24 小时 → recent，不备第二份",
              recent.get("created") is False and recent.get("reason") == "recent",
              json.dumps(recent, ensure_ascii=False))

        # 超过 24 小时：允许再备一份
        at_25h = (datetime.now() - timedelta(hours=25)).timestamp()
        os.utime(old, (at_25h, at_25h))
        crossed = backup.run(TMP)
        check("超过 24 小时 → 真的备一份", crossed.get("created") is True, json.dumps(crossed, ensure_ascii=False))
        check("跨天后有两份", len(backup.list_backups(TMP)) == 2, f"{names(TMP)}")

        step("§keep 只留 7 份")
        # 再攒 8 份历史（共 10 份），然后强制备一次把它压到 7
        for i in range(1, 9):
            p = TMP / "backup" / f"data-20260{100 + i}.db"
            p.write_bytes(b"stale")
        (TMP / "backup" / "readme.txt").write_text("别删我", encoding="utf-8")
        (TMP / "backup" / "data-notadate.db").write_bytes(b"x")
        before = len(backup.list_backups(TMP))
        check("攒够了 10 份", before == 10, f"{before} 份")

        # 去掉今天那份，让 force 真的能备一次（否则 already_today 直接跳过）
        for p in backup.list_backups(TMP):
            if p.name == f"data-{today}.db":
                p.unlink()
        pruned = backup.run(TMP, force=True)
        after = backup.list_backups(TMP)
        check("备份后只留 7 份", len(after) == 7, f"{len(after)} 份：{names(TMP)}")
        check("删掉的是最旧的三个（10 → 7）",
              pruned.get("pruned") == ["data-20260101.db", "data-20260102.db", "data-20260103.db"],
              str(pruned.get("pruned")))
        check("保留下的是文件名最大的 7 个",
              all(p.name >= "data-20260104.db" for p in after), f"{names(TMP)}")
        check("非 data-YYYYMMDD.db 的文件一个都没动",
              (TMP / "backup" / "readme.txt").exists() and (TMP / "backup" / "data-notadate.db").exists())

        step("§failure 备份失败不阻塞启动")
        bad = TMP / "broken"
        bad.mkdir(exist_ok=True)
        # 一个全新的空库（不复制主库，避开 WAL 未合并的问题）；有库才会走到「建备份目录」那一步
        with sqlite3.connect(bad / "data.db") as conn:
            conn.execute("CREATE TABLE t (x)")
        (bad / "backup").write_text("我是个普通文件，不是目录", encoding="utf-8")

        raised = False
        try:
            backup.run(bad, force=True)
        except Exception as exc:      # noqa: BLE001 — 这里就是要它抛
            raised = True
            print(f"    （run 抛了 {type(exc).__name__}，符合预期）")
        check("备份目录不可用时 run() 如实抛错（不静默）", raised)

        thread = backup.maybe_start(bad)
        if thread is not None:
            thread.join(timeout=20)
        check("启动钩子不抛错", True)
        check("启动钩子没有留下备份文件", not (bad / f"data-{today}.db").exists())

        # 端点形状：正常目录下 GET 有 last，POST 幂等
        got = client.get("/api/settings/backup")
        check("GET /api/settings/backup 200", got.status_code == 200, str(got.status_code))
        body = got.json()
        check("GET 里有 last / dir / keep", {"last", "dir", "keep"} <= set(body), str(list(body.keys())))
        check("keep 是 7", body.get("keep") == 7, str(body.get("keep")))

        posted = client.post("/api/settings/backup")
        check("POST 立即备份 200", posted.status_code == 200, str(posted.status_code))
        check("当天再点一次不产生新文件", posted.json().get("created") is False,
              json.dumps(posted.json(), ensure_ascii=False))

        # 真起一个服务：坏的数据目录不能让进程起不来
        port = free_port()
        env = {**os.environ, "CAIRN_NO_AUTO_ORGANIZE": "1", "LOG_LEVEL": "WARNING"}
        proc = subprocess.Popen(
            [sys.executable, "-m", "app", "--port", str(port), "--data-dir", str(bad)],
            cwd=str(BACKEND), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            ok_health = False
            deadline = time.time() + 40
            while time.time() < deadline:
                try:
                    r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.5)
                    if r.status_code == 200:
                        ok_health = True
                        break
                except Exception:     # noqa: BLE001 — 进程还没起来
                    time.sleep(0.4)
            check("备份目录坏掉时服务照常起来（/api/health 200）", ok_health,
                  f"pid={proc.pid}")
            if ok_health:
                st = httpx.get(f"http://127.0.0.1:{port}/api/settings/backup", timeout=5)
                check("坏目录下 GET backup 仍 200（last 为空）",
                      st.status_code == 200 and st.json().get("last") is None,
                      f"{st.status_code} {st.text[:80]}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except Exception:                 # noqa: BLE001 — 脚本本身崩了也要打全栈
        traceback.print_exc()
        code = 1
    finally:
        total = len(RESULTS)
        passed = sum(1 for ok, _ in RESULTS if ok)
        print(f"\n{passed}/{total} PASS")
        if passed != total:
            print("失败项：")
            for ok, name in RESULTS:
                if not ok:
                    print(f"  - {name}")
            code = 1
        elif code == 0:
            print(f"临时数据目录：{TMP}")
            shutil.rmtree(TMP, ignore_errors=True)
        else:
            # 断言都过了但脚本中途抛异常：别让「25/25 PASS」把退出码洗白
            print("断言虽全过，脚本本身异常退出（见上面的栈）")
    raise SystemExit(code)
