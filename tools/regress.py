#!/usr/bin/env python3
"""
一条命令跑完全部验收脚本（T9.12）

**为什么要有这个**：九个脚本各自的用法都写着「cd backend && uv run python scripts/verify_mN.py」，
但没人会在提交前手动敲九遍 —— 结果是只跑当下改的那个，跨里程碑回归（比如改配置加载把 m1 弄挂）
要等到下一轮才发现。这里把「跑全部」变成一条命令。

用法：
    python tools/regress.py            # m1 → m9 全跑
    python tools/regress.py --from 9   # 从 m9 开始（改完 M9 只补这一段）
    python tools/regress.py --only 7,9 # 只跑 m7 和 m9
    python tools/regress.py --list     # 只列将要跑哪些，不执行
    python tools/regress.py --keep-going   # 有 FAIL 也接着跑完（定位多处回归用）

脚本列表**靠扫目录**得出（`backend/scripts/verify_m<N>.py`），不写死 m1..m9：
M10 / M11 加了脚本自然会被带上，不用回来改这里。

退出码：0 全绿；1 有 FAIL；2 没 FAIL 但有环境不满足（脚本自己退 2）
        —— 2 与 0 必须分开：干净机上缺识别组件是正常事，不能让它冒充「全绿」。

子脚本的退出码含义（九个脚本统一约定）：0 全绿 / 1 用例失败 / 2 环境不满足。
**1 就停**（第一个红的往往就是根因，后面那些红是它带出来的）；
**2 不停**（缺组件是环境问题，不该掩盖后面真正的回归），但最后汇总里记一笔。

单脚本输出**边跑边打**，同时留最后 30 行 —— 失败时把尾巴再打一遍，
省得往上翻几千行找那个 FAIL。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
DIST = ROOT / "frontend" / "dist"
TAIL = 30                     # 失败时重播的行数
DEFAULT_TIMEOUT = 3600        # 单个脚本最多一小时（m9 全量实测 20 分钟出头）

_RESULT = re.compile(r"(\d+)/(\d+)\s*(?:PASS|通过)")   # m1/m5/m6 是「结果：57/57 通过」，别锚行首


def die(msg: str) -> None:
    print(msg)
    raise SystemExit(1)


def pick_python() -> Path:
    """选跑子脚本的解释器。

    优先 `backend/.venv` 里的那个：验收脚本 import 的是 `app.*`，
    依赖（fastapi / playwright / pypdfium2）都装在那里面，拿系统 python 跑会 ImportError。
    """
    for cand in (
        BACKEND / ".venv" / "Scripts" / "python.exe",   # Windows
        BACKEND / ".venv" / "bin" / "python",           # macOS / Linux
    ):
        if cand.is_file():
            return cand
    # 走到这里说明正用系统 python 或 conda 环境跑本脚本，那就沿用它
    return Path(sys.executable)


def discover() -> list[tuple[int, Path]]:
    """扫出所有 `verify_m<N>.py`，按里程碑号排序（不是按字典序，m10 得排在 m9 后面）。"""
    found: list[tuple[int, Path]] = []
    for p in SCRIPTS.glob("verify_m*.py"):
        m = re.fullmatch(r"verify_m(\d+)\.py", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found)


def parse_args() -> dict:
    opts = {"from": None, "to": None, "only": None, "list": False,
            "keep_going": False, "timeout": DEFAULT_TIMEOUT}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print(__doc__)
            raise SystemExit(0)
        elif a == "--from":
            opts["from"] = int(argv[i + 1]); i += 2
        elif a == "--to":
            opts["to"] = int(argv[i + 1]); i += 2
        elif a == "--only":
            opts["only"] = {int(x) for x in argv[i + 1].replace(" ", ",").split(",") if x}
            i += 2
        elif a == "--list":
            opts["list"] = True; i += 1
        elif a == "--keep-going":
            opts["keep_going"] = True; i += 1
        elif a == "--timeout":
            opts["timeout"] = int(argv[i + 1]); i += 2
        else:
            die(f"不认识的参数：{a}（--help 看用法）")
    return opts


def select(all_scripts: list[tuple[int, Path]], opts: dict) -> list[tuple[int, Path]]:
    picked = all_scripts
    if opts["only"]:
        picked = [(n, p) for n, p in picked if n in opts["only"]]
    else:
        if opts["from"] is not None:
            picked = [(n, p) for n, p in picked if n >= opts["from"]]
        if opts["to"] is not None:
            picked = [(n, p) for n, p in picked if n <= opts["to"]]
    return picked


def dist_is_stale() -> str:
    """`frontend/dist` 比 `frontend/src` 旧就给一句提醒。

    m7 验的是**构建产物**（后端吐的 dist），改了 `.vue` 没重新 build 就跑，
    文案与布局的结论全是旧的 —— 这种「绿灯假象」比红灯更贵。
    """
    src = ROOT / "frontend" / "src"
    index = DIST / "index.html"
    if not index.is_file() or not src.is_dir():
        return ""
    built = index.stat().st_mtime
    newest = 0.0
    for p in src.rglob("*"):
        try:
            if p.is_file() and p.suffix in (".vue", ".js", ".css", ".json"):
                newest = max(newest, p.stat().st_mtime)
        except OSError:
            continue
    if newest > built:
        return "frontend/dist 比 frontend/src 旧：m7 验的是旧构建，先 cd frontend && npm run build"
    return ""


def run_one(milestone: int, script: Path, python: Path, timeout: int) -> tuple[str, int, list[str], float]:
    """跑一个脚本，边跑边打。返回 (状态, 退出码, 输出尾巴, 耗时秒)。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 子脚本自己会打桩 / 用临时数据目录，父进程的 DATA_DIR 不能漏进去
    for key in ("DATA_DIR", "CAIRN_ENV_STRICT", "VECTOR_ENABLED", "CAIRN_COMPONENT_MODE"):
        env.pop(key, None)

    started = time.time()
    tail: deque[str] = deque(maxlen=TAIL)
    try:
        proc = subprocess.Popen(
            [str(python), str(script)],
            cwd=str(BACKEND),                   # 脚本里的相对路径按「cd backend」约定写
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        return "FAIL", 1, [f"起不来：{exc}"], 0.0

    state = {"timed_out": False}

    def _kill() -> None:
        # Windows 上 kill 掉的进程退出码也是 1，跟「用例失败」撞在一起，
        # 所以超时得自己记一笔，不能只看退出码。
        state["timed_out"] = True
        proc.kill()

    killer = threading.Timer(timeout, _kill)
    killer.start()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            print(line, flush=True)
            tail.append(line)
        code = proc.wait()
    except KeyboardInterrupt:
        proc.kill()
        proc.wait()
        raise
    finally:
        killer.cancel()

    elapsed = time.time() - started
    if state["timed_out"]:
        tail.append(f"（超过 {timeout}s 被判超时，进程已杀）")
        return "TIMEOUT", code, list(tail), elapsed
    if code == 0:
        return "PASS", 0, list(tail), elapsed
    if code == 2:
        return "SKIP", 2, list(tail), elapsed
    return "FAIL", code, list(tail), elapsed


def main() -> int:
    opts = parse_args()
    scripts = discover()
    if not scripts:
        die(f"没找到任何验收脚本：{SCRIPTS / 'verify_m*.py'}")
    picked = select(scripts, opts)
    if not picked:
        die("筛选后一个脚本都不剩，检查 --from / --to / --only")

    python = pick_python()

    if opts["list"]:
        print(f"解释器：{python}")
        for n, p in picked:
            print(f"  m{n:<3} {p.relative_to(ROOT).as_posix()}")
        return 0

    warn = dist_is_stale()
    if warn:
        print(f"[WARN] {warn}\n")

    print(f"回归范围：{len(picked)} 个脚本  m{picked[0][0]} → m{picked[-1][0]}")
    print(f"解释器：{python}")
    print(f"工作目录：{BACKEND}\n")

    results: list[tuple[int, str, int, float, str]] = []   # (里程碑, 状态, 码, 耗时, 计数)
    began = time.time()

    for n, script in picked:
        print("=" * 68)
        print(f"▶ m{n}  {script.name}")
        print("=" * 68, flush=True)
        status, code, tail, elapsed = run_one(n, script, python, opts["timeout"])

        m = _RESULT.search("\n".join(tail))
        count = f"{m.group(1)}/{m.group(2)}" if m else ("—" if status != "PASS" else "?")
        results.append((n, status, code, elapsed, count))

        if status in ("FAIL", "TIMEOUT"):
            print(f"\n✗ m{n} {status}（退出码 {code}，{elapsed:.0f}s）—— 该脚本最后 {len(tail)} 行：")
            for line in tail:
                print(f"  | {line}")
            if not opts["keep_going"]:
                break            # 第一个红的往往就是根因
        elif status == "SKIP":
            print(f"\n! m{n} 环境不满足（退出码 2，{elapsed:.0f}s）—— 继续跑后面的")
        else:
            print(f"\n✓ m{n} PASS  {count}  {elapsed:.0f}s")
        print(flush=True)

    total = time.time() - began
    print("=" * 68)
    print("回归汇总")
    print("=" * 68)
    for n, status, code, elapsed, count in results:
        mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "!", "TIMEOUT": "✗"}[status]
        print(f"  {mark} m{n:<3} {status:<7} {count:>8}  {elapsed:6.0f}s")

    ran = {n for n, *_ in results}
    missed = [n for n, _ in picked if n not in ran]
    if missed:
        print(f"  未跑：m{', m'.join(str(x) for x in missed)}（前面有 FAIL，按约定停下）")

    failed = [n for n, s, *_ in results if s in ("FAIL", "TIMEOUT")]
    skipped = [n for n, s, *_ in results if s == "SKIP"]
    print(f"\n合计 {len(results)} 个脚本，用时 {total / 60:.1f} 分钟")

    if failed:
        print(f"有 FAIL：m{', m'.join(str(x) for x in failed)}")
        return 1
    if missed:
        print("有脚本没跑到，不算全绿")
        return 1
    if skipped:
        print(f"环境不满足：m{', m'.join(str(x) for x in skipped)}（不算全绿，但也不是用例失败）")
        if warn:
            print(f"另有提醒：{warn}")
        return 2
    if warn:
        print(f"全部通过，但注意：{warn}")
    else:
        print("全部通过")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n中断")
        raise SystemExit(130)
