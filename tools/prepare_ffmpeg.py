"""把 ffmpeg 的整套二进制复制进桌面端打包目录（T5.6）。

为什么必须自己带（总纲 §9 已记的坑）：
本机 ffmpeg 来自 Anaconda（`D:\\Anaconda3\\Library\\bin`），它是个**共享库构建**——
`ffmpeg.exe` 只有 350KB，真正的编解码器在 `avcodec-58.dll` 这七个 DLL 里。
只复制 exe 到别的机器上一定跑不起来；而依赖系统 PATH 等于要求用户自己装 Anaconda。

产物落在 `desktop/resources/ffmpeg/`，electron-builder 用 `extraResources` 把它搬到
`<安装目录>/resources/ffmpeg/`，后端 `config._tool()` 在冻结时默认就去那里找。

用法：
    python tools/prepare_ffmpeg.py                 # 自动从 FFMPEG_DIR / PATH 找
    python tools/prepare_ffmpeg.py --src D:/Anaconda3/Library/bin
    python tools/prepare_ffmpeg.py --check-only    # 只检查目标目录是否可用
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "desktop" / "resources" / "ffmpeg"

EXES = ("ffmpeg.exe", "ffprobe.exe") if os.name == "nt" else ("ffmpeg", "ffprobe")
# conda-forge / gyan 两种布局都覆盖：名字带版本号，故用前缀匹配
DLL_PATTERNS = (
    r"^av(codec|format|util|filter|device)-\d+\.dll$",
    r"^sw(resample|scale)-\d+\.dll$",
    r"^postproc-\d+\.dll$",
)


def find_src(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("FFMPEG_DIR", "").strip()
    if env:
        return Path(env)
    found = shutil.which("ffmpeg")
    if found:
        return Path(found).resolve().parent
    raise SystemExit("找不到 ffmpeg：请设 FFMPEG_DIR，或用 --src 指定目录")


def collect(src: Path) -> list[Path]:
    if not src.is_dir():
        raise SystemExit(f"源目录不存在：{src}")
    files: list[Path] = []
    for name in EXES:
        p = src / name
        if not p.exists():
            raise SystemExit(f"缺 {name}：{src}")
        files.append(p)
    if os.name == "nt":
        for p in src.iterdir():
            if p.is_file() and any(re.match(pat, p.name, re.I) for pat in DLL_PATTERNS):
                files.append(p)
    return files


def verify(dest: Path) -> None:
    """用**干净的 PATH** 跑一次，确保拷出来的这套自己就够了。"""
    exe = dest / EXES[0]
    if not exe.exists():
        raise SystemExit(f"验证失败：{exe} 不存在")
    # 只留系统目录，剥掉 Anaconda 的 Library\bin —— 否则会误用源目录里的 DLL 而"假通过"
    safe_path = os.pathsep.join(
        p for p in (os.environ.get("SystemRoot", r"C:\Windows"),) if p
    )
    safe_path = f"{safe_path}\\System32;{safe_path}"
    env = {**os.environ, "PATH": safe_path}
    try:
        r = subprocess.run(
            [str(exe), "-version"], capture_output=True, text=True, timeout=30, env=env
        )
    except OSError as exc:
        raise SystemExit(f"验证失败：无法执行（多半缺 DLL）→ {exc}") from exc
    if r.returncode != 0:
        raise SystemExit(f"验证失败：退出码 {r.returncode}\n{r.stderr[:800]}")
    first = (r.stdout or "").splitlines()[0] if r.stdout else "(无输出)"
    print(f"  ✓ 干净 PATH 下可执行：{first[:90]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="ffmpeg 所在目录（含 ffmpeg.exe 与 av*.dll）")
    ap.add_argument("--dest", default=str(DEST))
    ap.add_argument("--check-only", action="store_true", help="只验证已有产物，不复制")
    args = ap.parse_args()

    dest = Path(args.dest)
    if args.check_only:
        verify(dest)
        return 0

    src = find_src(args.src)
    files = collect(src)
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    for f in files:
        shutil.copy2(f, dest / f.name)
        total += f.stat().st_size
    print(f"已复制 {len(files)} 个文件 → {dest}（{total / 1024 / 1024:.1f} MB）")
    for f in sorted(files, key=lambda p: p.name):
        print(f"  {f.name:<22} {f.stat().st_size / 1024 / 1024:>7.1f} MB")
    verify(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
