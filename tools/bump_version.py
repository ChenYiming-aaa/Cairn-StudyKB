#!/usr/bin/env python3
"""版本号统一改写（T8.6）。

四处对外版本号 + 一处运行时镜像 + README 首屏徽标，一次改完：

    backend/pyproject.toml     打包元数据（uv / PyInstaller 读它）
    backend/app/version.py     运行时真源（冻结包里读不到 pyproject，见该文件顶部注释）
    frontend/package.json      界面包
    desktop/package.json       Electron 包 —— **安装包文件名与更新器比较基准都取它**
    README.md                  首屏徽标 `version-X.Y.Z`（用户第一眼看到的版本，
                               2026-11-26 才纳入检查 —— 之前它停在 0.3.4 而代码已 0.3.7）

用法：

    python tools/bump_version.py --to 0.2.0     # 五处一起改
    python tools/bump_version.py --to 0.3.0-alpha.1   # 预发布版（npm 能装、更新器认得）
    python tools/bump_version.py --check        # 五处必须一致，不一致 exit 1
    python tools/bump_version.py                # 只看现状

`backend/uv.lock` 里也有一份项目版本，但它**不归这里管**：`uv run` / `uv lock` 看到
`pyproject.toml` 变了会自己重写，手动改反而会被覆盖。

为什么不用正则全文件替换：`package.json` 里还有 `min_app_version` 之类的字符串，
手写正则很容易把 `"0.2.0"` 改成别的东西；这里只动**第一次出现的 `version` 字段**，
其余字节原样保留（不改格式、不重排键）。README 同理 —— 正文里那些「当前版本（v0.3.7）」
是历史叙述，不归这里改，只动徽标那一个 `badge/version-X.Y.Z-green.svg`。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / 'backend' / 'pyproject.toml'
APP_VERSION = ROOT / 'backend' / 'app' / 'version.py'
FRONTEND_PKG = ROOT / 'frontend' / 'package.json'
DESKTOP_PKG = ROOT / 'desktop' / 'package.json'
README = ROOT / 'README.md'

# README 首屏徽标：`https://img.shields.io/badge/version-0.3.7-green.svg`。
# 版本段非贪婪吃到 `-green.svg` 为止：预发布版是 `0.3.0-alpha.1`，
# 写成 `\d+\.\d+\.\d+` 只会抓到 `0.3.0`，然后每跑一次 `--to` 就把 `-alpha.1` 漏在外面。
README_BADGE = re.compile(r'badge/version-([0-9][0-9A-Za-z.\-]*?)-green\.svg')

# 允许预发布后缀（`0.3.0-alpha.1`）：`desktop/semver.js` 本来就按「同号正式版 > 预发布」比，
# 但这里以前只收三段式，发布预发布版得手改四个文件。后缀的字符集按 semver 的
# `[0-9A-Za-z-]` 点分段写，故意放窄一点 —— 版本号里出现斜杠/空格会让打包产物名变成非法路径。
SEMVER = re.compile(r'^\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$')


def _read_pyproject() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding='utf-8'), re.MULTILINE)
    return m.group(1) if m else ''


def _read_app_version() -> str:
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', APP_VERSION.read_text(encoding='utf-8'), re.MULTILINE)
    return m.group(1) if m else ''


def _read_pkg(path: Path) -> str:
    return str(json.loads(path.read_text(encoding='utf-8')).get('version', ''))


def _read_readme_badge() -> str:
    """README 首屏徽标里的版本。没有徽标（或格式变了）就回空串，让 `--check` 报红。"""
    m = README_BADGE.search(README.read_text(encoding='utf-8'))
    return m.group(1) if m else ''


def snapshot() -> dict[str, str]:
    """五处现值。任何一处读不出来都记成空串，交给调用方判断。"""
    return {
        'backend/pyproject.toml': _read_pyproject(),
        'backend/app/version.py': _read_app_version(),
        'frontend/package.json': _read_pkg(FRONTEND_PKG),
        'desktop/package.json': _read_pkg(DESKTOP_PKG),
        'README.md（徽标）': _read_readme_badge(),
    }


def _write(pattern: str, path: Path, new: str) -> bool:
    text = path.read_text(encoding='utf-8')
    # 三段：前缀 / 旧值 / 收尾标点。三个捕获组缺一不可 —— 漏掉 group(3) 会把
    # `"0.1.0"` 变成 `"0.1.90.1.0`（2026-11-10 第一次跑就踩了，四处文件同时坏）
    replaced, n = re.subn(pattern, lambda m: m.group(1) + new + m.group(3), text, count=1, flags=re.MULTILINE)
    if n != 1:
        return False
    if replaced != text:
        path.write_text(replaced, encoding='utf-8')
    return True


def apply(new: str) -> int:
    ok = [
        _write(r'^(version\s*=\s*")([^"]+)(")', PYPROJECT, new),
        _write(r'^(VERSION\s*=\s*")([^"]+)(")', APP_VERSION, new),
        _write(r'^(\s*"version"\s*:\s*")([^"]+)(")', FRONTEND_PKG, new),
        _write(r'^(\s*"version"\s*:\s*")([^"]+)(")', DESKTOP_PKG, new),
        _write(r'(badge/version-)([0-9][0-9A-Za-z.\-]*?)(-green\.svg)', README, new),
    ]
    for path, applied in zip(snapshot().keys(), ok):
        print(('  写入 ' if applied else '  未命中 ') + path)
    return 0 if all(ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description='统一改写五处版本号')
    ap.add_argument('--to', help='目标版本，如 0.2.0')
    ap.add_argument('--check', action='store_true', help='只校验五处一致')
    args = ap.parse_args()

    if args.to:
        if not SEMVER.match(args.to):
            print(f'✗ 版本号要写成 X.Y.Z 或 X.Y.Z-预发布，收到 {args.to!r}')
            return 2
        before = snapshot()
        print(f'版本 {before["backend/pyproject.toml"] or "?"} → {args.to}')
        code = apply(args.to)
        if code:
            return code

    snap = snapshot()
    width = max(len(k) for k in snap)
    for k, v in snap.items():
        print(f'  {k.ljust(width)}  {v or "(未读到)"}')

    values = set(snap.values())
    if '' in values:
        print('✗ 有一处读不到版本号')
        return 1
    if len(values) > 1:
        print('✗ 五处版本号不一致 —— 用 --to 改一次')
        return 1
    print(f'✓ 五处一致：{values.pop()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
