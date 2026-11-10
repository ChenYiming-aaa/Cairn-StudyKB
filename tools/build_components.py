"""打三个可选组件包（T8.2）。

    cd backend && uv run python ../tools/build_components.py            # 三个全打
    uv run python ../tools/build_components.py --only embed             # 只打一个
    uv run python ../tools/build_components.py --selftest-only          # 只跑已有产物的自检
    uv run python ../tools/build_components.py --no-selftest            # 跳过自检（不推荐）

产出：
- `backend/build/components/dist/cairn-<id>/`：onedir 目录（exe + `_internal/` + `manifest.json`）
- `desktop/release-components/cairn-<id>-<ver>.zip`：**zip 根目录就是 onedir 的内容**
  （解到 `data/components/<id>/` 后 `cairn-<id>.exe` 正好在根上，`components._argv` 靠这个找入口）
- `backend/app/components.json` 里的 `size` / `sha256` 就地回写

**console=True 是硬要求**：组件由主程序用管道驱动，`console=False` 会让 stdout 不可用，
整条协议直接废。主程序自己的 spec 反过来是 `console=False`（用户不该看到黑框），
两份 spec 长得很像，别顺手抄错。窗口用 `CREATE_NO_WINDOW` 隐藏（组件侧看不到黑框）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BUILD = BACKEND / "build" / "components"
OUT = ROOT / "desktop" / "release-components"
MANIFEST = BACKEND / "app" / "components.json"

VERSION = "0.2.0"

# 每个组件只收自己那一套；把别人的重栈排掉，否则一个包能到 600 MB
HEAVY = ["torch", "transformers", "sentence_transformers", "scipy", "sklearn",
         "faster_whisper", "ctranslate2", "av", "onnxruntime", "playwright", "hf_xet"]
COMMON_EXCLUDES = ["tkinter", "matplotlib", "IPython", "jupyter", "pytest", "notebook",
                   "PyQt5", "PySide2", "PySide6"]

COMPONENTS: dict[str, dict] = {
    "embed": {
        "keep": ["torch", "transformers", "sentence_transformers", "scipy", "sklearn",
                 "hf_xet"],
        "datas": ["sentence_transformers"],
        # v0.1.0 踩过的坑：torch.utils.data 在函数里 import torch.distributed，
        # 静态分析看得见但 hook 不一定收全；显式 collect 一次，成本 12 MB。
        "extra": "hiddenimports += collect_submodules('torch.distributed')",
    },
    "asr": {
        "keep": ["faster_whisper", "ctranslate2", "av", "onnxruntime"],
        "datas": ["faster_whisper", "onnxruntime"],
        "extra": "",
    },
    "browser": {
        "keep": ["playwright"],
        # playwright 的 node 驱动（node.exe + package/cli.js）不是 .py，必须显式收
        "datas": ["playwright"],
        "extra": "",
    },
}

SPEC_TEMPLATE = '''# -*- mode: python ; coding: utf-8 -*-
"""组件 {cid} 的打包配置 —— **由 tools/build_components.py 生成，不要手改**。

和主程序 `cairn-backend.spec` 的两处刻意差异：
1. `console=True`：组件靠 stdout 走协议，windowed 会让 stdout 变 None；
2. excludes 只排"别人家的重栈"，自己那一套必须完整收进来。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
hiddenimports = []
{datas}
{extra}
a = Analysis(
    [r'{entry}'],
    pathex=[r'{backend}', r'{components_dir}'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes={excludes},
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='cairn-{cid}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,          # 协议要 stdout，不能关
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='cairn-{cid}')
'''


def log(msg: str) -> None:
    print(msg, flush=True)


def write_spec(cid: str) -> Path:
    cfg = COMPONENTS[cid]
    spec_dir = BUILD / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    datas = "\n".join(
        f"datas += collect_data_files({pkg!r})" for pkg in cfg["datas"]
    ) or "# 没有额外数据文件"
    excludes = COMMON_EXCLUDES + [p for p in HEAVY if p not in cfg["keep"]]
    text = SPEC_TEMPLATE.format(
        cid=cid,
        entry=BACKEND / "components" / cid / "entry.py",
        backend=BACKEND,
        components_dir=BACKEND / "components",
        datas=datas,
        extra=cfg["extra"] or "# 无额外 hiddenimports",
        excludes=repr(excludes),
    )
    path = spec_dir / f"cairn-{cid}.spec"
    path.write_text(text, encoding="utf-8")
    return path


def build(cid: str) -> Path:
    spec = write_spec(cid)
    dist = BUILD / "dist"
    work = BUILD / "work" / cid
    log(f"\n=== 打包组件 {cid} ===")
    started = time.time()
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm",
           "--distpath", str(dist), "--workpath", str(work), str(spec)]
    proc = subprocess.run(cmd, cwd=str(BACKEND))
    if proc.returncode != 0:
        raise SystemExit(f"PyInstaller 失败（exit {proc.returncode}），见上面的输出")
    out = dist / f"cairn-{cid}"
    if not (out / f"cairn-{cid}.exe").exists():
        raise SystemExit(f"没找到产物 {out / f'cairn-{cid}.exe'}")
    log(f"  完成，用时 {time.time() - started:.0f}s，解包 {dir_size(out) / 1e6:.0f} MB")
    return out


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def write_manifest(cid: str, out: Path) -> None:
    """`components.installed_version()` 读的就是这个文件。"""
    (out / "manifest.json").write_text(json.dumps({
        "id": cid,
        "version": VERSION,
        "min_app_version": "0.2.0",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def selftest(cid: str, out: Path) -> None:
    """起 exe 跑 `--selftest`：握手 + 一次最小任务。打包最容易坏的就是这一步。"""
    exe = out / f"cairn-{cid}.exe"
    env = dict(os.environ)
    env.setdefault("CAIRN_MODELS_DIR", str(ROOT / "data" / "models"))
    env.setdefault("CAIRN_BROWSER_CHANNEL", "msedge")
    log(f"  自检 {exe.name} …")
    proc = subprocess.run([str(exe), "--selftest"], env=env, timeout=900)
    if proc.returncode != 0:
        raise SystemExit(f"× 组件 {cid} 自检失败（exit {proc.returncode}）")


def zip_and_hash(cid: str, out: Path) -> tuple[Path, int, str]:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"cairn-{cid}-{VERSION}.zip"
    if target.exists():
        target.unlink()
    log(f"  压缩 → {target.name}")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(out).as_posix())
    digest = hashlib.sha256()
    with open(target, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    size = target.stat().st_size
    log(f"  {size / 1e6:.0f} MB，sha256={digest.hexdigest()[:16]}…")
    return target, size, digest.hexdigest()


def update_manifest_json(results: dict[str, tuple[int, str]]) -> None:
    """把 zip 的真实体积与 sha256 回写进随主包发布的清单。"""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in data.get("components", []):
        cid = entry.get("id")
        if cid in results:
            size, sha = results[cid]
            entry["size"] = size
            entry["sha256"] = sha
            entry["asset"] = f"cairn-{cid}-{VERSION}.zip"
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    log(f"\n清单已更新：{MANIFEST.relative_to(ROOT)}")


def main() -> int:
    args = sys.argv[1:]
    only = args[args.index("--only") + 1] if "--only" in args else None
    ids = [only] if only else list(COMPONENTS)
    for cid in ids:
        if cid not in COMPONENTS:
            raise SystemExit(f"不认识的组件：{cid}（可选 {list(COMPONENTS)}）")

    results: dict[str, tuple[int, str]] = {}
    for cid in ids:
        out = BUILD / "dist" / f"cairn-{cid}"
        if "--selftest-only" not in args:
            out = build(cid)
            write_manifest(cid, out)
        elif not out.exists():
            raise SystemExit(f"{out} 不存在，先跑一次完整构建")
        if "--no-selftest" not in args:
            selftest(cid, out)
        target, size, sha = zip_and_hash(cid, out)
        results[cid] = (size, sha)
        log(f"  产物：{target}")

    if len(results) == len(COMPONENTS):
        update_manifest_json(results)
    else:
        log("\n只打了一部分，清单未回写（size/sha256 要三个齐了才一致）")
    shutil.rmtree(BUILD / "work", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
