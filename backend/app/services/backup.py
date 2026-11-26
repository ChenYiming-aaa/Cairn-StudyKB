"""数据备份（优化方案 v0.4 §3.3）。

为什么是 `VACUUM INTO` 而不是复制文件：
- 库可能是 WAL 模式，直接 copy `data.db` 会漏掉 `-wal` 里已提交、还没 checkpoint 的数据；
- `VACUUM INTO` 走一致性快照，产出的是一份已整理、无空洞的干净库（也顺带压体积）。

三条硬规则（都来自方案 §3.3 的验收清单）：
1. **失败只记日志，绝不阻塞启动** —— 备份是保险，不是启动的前置条件；
2. **同一天只留一份**：文件名 `data-YYYYMMDD.db`。`VACUUM INTO` 的目标已存在会直接报错，
   所以必须先判存在，不能靠捕获异常（那样「今天备过」看起来和「备份坏了」一样）；
3. **只保留最近 7 份，且只删自己命名的文件** —— 用户往 backup/ 里放别的东西，一个都不许动。

失败现场不留残骸：`VACUUM INTO` 中途失败时把目标文件删掉，避免一份看起来像备份的空库。
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("cairn")

KEEP = 7                     # 保留份数（一天最多一份 → 最近 7 天）
INTERVAL_HOURS = 24          # 自动备份的最小间隔
DIRNAME = "backup"
NAME_RE = re.compile(r"^data-(\d{8})\.db$")


def backup_dir(data_dir: Path | str) -> Path:
    return Path(data_dir) / DIRNAME


def list_backups(data_dir: Path | str) -> list[Path]:
    """按文件名（= 日期）升序。只认 `data-YYYYMMDD.db`，别的东西不进这个列表。"""
    folder = backup_dir(data_dir)
    if not folder.is_dir():
        return []
    items = [p for p in folder.iterdir() if p.is_file() and NAME_RE.match(p.name)]
    return sorted(items, key=lambda p: p.name)


def latest(data_dir: Path | str) -> dict | None:
    items = list_backups(data_dir)
    if not items:
        return None
    path = items[-1]
    st = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size": st.st_size,
        # 用 mtime 而不是文件名推时间：跨天不备份时两者会差一天
        "at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
    }


def status(data_dir: Path | str) -> dict:
    return {
        "last": latest(data_dir),
        "dir": str(backup_dir(data_dir)),
        "keep": KEEP,
        "interval_hours": INTERVAL_HOURS,
    }


def prune(data_dir: Path | str, keep: int = KEEP) -> list[str]:
    """删掉超出 keep 份的最旧备份，返回被删的文件名（也是给日志与验收看的证据）。"""
    items = list_backups(data_dir)
    if keep <= 0:
        return []
    dropped = items[:-keep] if len(items) > keep else []
    names: list[str] = []
    for path in dropped:
        try:
            path.unlink()
            names.append(path.name)
        except OSError as exc:            # 删不掉就留着，下次再删，不影响这次备份
            log.warning("旧备份删不掉（留着下次再试）：%s — %s", path.name, exc)
    return names


def _sql_path(path: Path) -> str:
    """SQLite 字符串字面量：路径里可能有单引号（Windows 用户名并不罕见）。"""
    return "'" + str(path).replace("'", "''") + "'"


def run(data_dir: Path | str, force: bool = False) -> dict:
    """备一份。`force=True` 只跳过「24 小时」这条门槛，**不跳过「今天已备过」**。

    返回 `{created, reason, ...}`：
      - `created=True`：真的生成了新文件（`path` / `size` / `pruned`）
      - `created=False`：`reason` ∈ `already_today` / `recent` / `no_db`
    目录建不出来、`VACUUM INTO` 失败等**真错误一律抛出去**，由调用方决定「记日志还是回给界面」——
    这里不吞异常，否则「备份坏了」会永远显示成「今天已经备过」。
    """
    data_dir = Path(data_dir)
    source = data_dir / "data.db"
    if not source.exists():
        return {"created": False, "reason": "no_db", "last": None}

    target = backup_dir(data_dir) / f"data-{datetime.now():%Y%m%d}.db"
    if target.exists():
        return {"created": False, "reason": "already_today", "last": latest(data_dir)}

    last = latest(data_dir)
    if not force and last:
        age_hours = (datetime.now().timestamp() - Path(last["path"]).stat().st_mtime) / 3600
        if age_hours < INTERVAL_HOURS:
            return {"created": False, "reason": "recent", "last": last}

    # backup 若是同名普通文件，这里会抛 —— 正是「目录不可用」该有的表现
    backup_dir(data_dir).mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(source), timeout=10)
    try:
        conn.execute(f"VACUUM INTO {_sql_path(target)}")
    except Exception:
        target.unlink(missing_ok=True)     # 别留半份，看起来像可用备份的空库最危险
        raise
    finally:
        conn.close()

    pruned = prune(data_dir)
    size = target.stat().st_size
    log.info("已备份数据库：%s（%.1f MB）%s", target.name, size / 1e6,
             f"，清理 {len(pruned)} 份旧备份" if pruned else "")
    return {
        "created": True,
        "reason": "created",
        "path": str(target),
        "size": size,
        "pruned": pruned,
        "last": latest(data_dir),
    }


def _worker(data_dir: Path | str) -> None:
    try:
        result = run(data_dir)
        if not result.get("created") and result.get("reason") not in ("already_today", "recent"):
            log.info("启动备份跳过：%s", result.get("reason"))
    except Exception as exc:                # noqa: BLE001 — 备份失败绝不能把启动带下去
        log.warning("这次备份没做成（不影响使用）：%s", exc, exc_info=True)


def maybe_start(data_dir: Path | str) -> threading.Thread:
    """启动钩子：后台线程备一份，立刻返回。

    线程是 daemon：进程退出不等它；反过来它也绝不阻塞启动。
    """
    thread = threading.Thread(target=_worker, args=(data_dir,), name="cairn-backup", daemon=True)
    thread.start()
    return thread
