"""T1.4 状态脚本：DB 路径与各表行数 / 环境自检 / 已完成里程碑 / 最近 3 条任务。

用法：
    uv run python scripts/status.py                 # 用配置里的 DB
    uv run python scripts/status.py --db 副本.db    # 验证复制出来的 DB 可正常打开
只读，不建库、不写数据。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT, get_settings  # noqa: E402
from app.db.conn import table_exists  # noqa: E402


def _line(title: str) -> None:
    print(f"\n── {title} " + "─" * max(0, 52 - len(title)))


def _load_vec(conn: sqlite3.Connection) -> bool:
    """尽力装 sqlite-vec；失败只是读不了 chunk_vec 的行数，不影响其余检查。"""
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        return True
    except Exception:
        return False


def _db_section(path: Path) -> None:
    _line("数据库")
    print(f"路径      : {path}")
    if not path.exists():
        print("状态      : 尚未建库（启动一次后端会自动建）")
        return
    print(f"大小      : {path.stat().st_size:,} bytes")
    try:
        # Windows 中文路径必须走 as_uri()，手拼 "file:C:\..." 会解析失败
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
    except (sqlite3.Error, ValueError) as exc:
        print(f"状态      : 打开失败（{type(exc).__name__}）")
        return
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        print(f"user_version : {version}    journal_mode : {journal}")
        # M3：chunk_vec 是 vec0 虚拟表，不装扩展时连 COUNT(*) 都会报
        # "no such module: vec0"。只读连接同样可以装扩展，装不上就标出来。
        vec_loaded = _load_vec(conn)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        print(f"表数量    : {len(tables)}")
        _line("各表行数")
        for name in tables:
            try:
                count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                print(f"  {name:<20} {count:>8,}")
            except sqlite3.Error as exc:
                hint = "需 sqlite-vec 扩展" if name.startswith("chunk_vec") and not vec_loaded \
                    else type(exc).__name__
                print(f"  {name:<20} {'读取失败':>8}  ({hint})")
        print(f"  {'chunk_vec (可选)':<20} {'已启用' if table_exists(conn, 'chunk_vec') else '未启用':>8}")
        _line("最近 3 条任务")
        if table_exists(conn, "agent_task"):
            rows = conn.execute(
                "SELECT id, type, status, progress, error_code, created_at "
                "FROM agent_task ORDER BY created_at DESC LIMIT 3"
            ).fetchall()
            if not rows:
                print("  （无任务）")
            for r in rows:
                print(f"  {r['created_at']}  {r['status']:<8} {r['type']:<18} "
                      f"progress={r['progress']:<3} {r['error_code'] or ''}")
                print(f"    id={r['id']}")
        else:
            print("  agent_task 表不存在")
    finally:
        conn.close()


def _env_section() -> None:
    _line("环境自检")
    cfg = get_settings()
    print(f"  Python          : {sys.version.split()[0]}（要求 3.12）")
    print(f"  SQLite          : {sqlite3.sqlite_version}（要求 >= 3.34，trigram 前提）")
    # trigram 可用性实测
    try:
        probe = sqlite3.connect(":memory:")
        probe.execute(
            "CREATE VIRTUAL TABLE t USING fts5(content, tokenize='trigram')"
        )
        probe.close()
        trigram = "可用"
    except sqlite3.Error:
        trigram = "不可用"
    print(f"  FTS5 trigram    : {trigram}")
    print(f"  uv              : {shutil.which('uv') or '未找到'}")
    print(f"  Node            : {shutil.which('node') or '未找到'}")
    # ffmpeg 优先按 FFMPEG_DIR 解析（从 IDE/Electron 启动时 PATH 可能不含它，M2 §7）
    for name, configured in (("ffmpeg", cfg.ffmpeg_exe), ("ffprobe", cfg.ffprobe_exe)):
        found = configured or shutil.which(name)
        source = "FFMPEG_DIR" if configured else "PATH"
        print(f"  {name:<15} : {found or '未找到（M2 需要）'}"
              + (f"（来自 {source}）" if found else ""))
    print(f"  LLM Key         : {'已配置' if cfg.has_llm_key else '未配置'}（值不显示）")
    print(f"  LLM model       : {cfg.llm_model}")
    print(f"  LLM endpoint    : {cfg.chat_completions_url}")


def _milestone_section() -> None:
    _line("已完成里程碑")
    try:
        out = subprocess.run(
            ["git", "tag", "-l", "m*-done"], cwd=ROOT,
            capture_output=True, text=True, timeout=10, check=False,
        )
        tags = [t.strip() for t in out.stdout.splitlines() if t.strip()]
        if tags:
            for t in tags:
                print(f"  {t}")
        else:
            print("  无（还没有任何 m*-done 标签）")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  无法读取 git tag（{type(exc).__name__}）")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cairn 状态自检（只读）")
    parser.add_argument("--db", type=Path, default=None, help="指定要检查的 DB 文件")
    args = parser.parse_args()
    cfg = get_settings()
    path = args.db if args.db is not None else cfg.db_path

    print("=" * 60)
    print("  Cairn · 状态自检")
    print("=" * 60)
    print(f"数据目录  : {cfg.data_dir}")
    print(f"监听端口  : {cfg.port}")
    _db_section(Path(path))
    _env_section()
    _milestone_section()
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
