#!/usr/bin/env python
"""用本机已安装的代码签名证书打包 Windows 安装包。

为什么需要这个脚本：electron-builder 26 只支持用环境变量指定 pfx（`WIN_CSC_LINK`），
而云签名（Certum SimplySign / 硬件令牌）的私钥导不出来，只能按「证书主题名」从
Windows 证书库里挑。主题名必须写进配置，又不能写死提交——没有证书的机器上会直接报
`No code signing certificate configured`，把正常打包也弄坏。

所以这里在打包前生成一份临时配置（gitignored），打完删掉。

用法：
    python tools/build_signed.py            # 自动找证书 → 打包 → 验签
    python tools/build_signed.py --list     # 只看本机有哪些代码签名证书

前提：
    backend 已用 pyinstaller 出过 onedir（否则 extraResources 指向空目录）
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP = ROOT / "desktop"
TEMP_CONFIG = DESKTOP / "electron-builder.sign.json"
SIGNTOOL_GLOBS = [
    r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe",
    r"C:\Program Files\Windows Kits\10\bin\*\x64\signtool.exe",
]


def find_signtool() -> Path | None:
    for pattern in SIGNTOOL_GLOBS:
        hits = sorted(Path(pattern.split("*")[0]).glob("*/x64/signtool.exe"))
        if hits:
            return hits[-1]  # 版本号排序，取最新的
    return shutil.which("signtool") and Path(shutil.which("signtool"))


def list_certs() -> list[dict]:
    """读出 CurrentUser\\My 里所有代码签名证书。"""
    ps = (
        "Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert -ErrorAction SilentlyContinue | "
        "ForEach-Object { $_.Subject + '||' + $_.Thumbprint + '||' + "
        "$_.NotAfter.ToString('yyyy-MM-dd') }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"读取证书库失败：{exc}")
        return []

    certs = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("||")]
        if len(parts) == 3 and parts[0]:
            certs.append({"subject": parts[0], "thumbprint": parts[1], "not_after": parts[2]})
    return certs


def pick_cert() -> dict | None:
    certs = list_certs()
    if not certs:
        return None
    if len(certs) > 1:
        print("本机有多张代码签名证书，用第一张（要换请删掉多余的，或改这个脚本）：")
        for c in certs:
            print(f"  - {c['subject']}  到期 {c['not_after']}")
    return certs[0]


def build_config(cert: dict) -> dict:
    pkg = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    build = json.loads(json.dumps(pkg["build"]))  # 深拷一份，别改到原对象
    win = build.setdefault("win", {})
    win["signtoolOptions"] = {
        "certificateSubjectName": cert["subject"],
        "signingHashAlgorithms": ["sha256"],
        # Certum 的 RFC3161 时间戳服务；换别家证书改这里
        "rfc3161TimeStampServer": "http://time.certum.pl",
    }
    return build


def run(cmd: list[str], cwd: Path) -> int:
    print(f"\n$ {' '.join(cmd)}  (cwd={cwd})")
    return subprocess.call(cmd, cwd=str(cwd))


def verify(installer: Path, signtool: Path) -> bool:
    print(f"\n=== 验签 {installer.name} ===")
    code = subprocess.call([str(signtool), "verify", "/pa", "/v", str(installer)])
    return code == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列证书")
    args = ap.parse_args()

    if args.list:
        certs = list_certs()
        if not certs:
            print("本机没有代码签名证书。")
            print("Certum SimplySign 激活后证书会出现在「个人」证书库里。")
            return 0
        for c in certs:
            print(f"{c['not_after']}  {c['thumbprint']}  {c['subject']}")
        return 0

    signtool = find_signtool()
    if signtool is None:
        print("找不到 signtool.exe（需要 Windows SDK）。")
        return 2
    print(f"signtool: {signtool}")

    cert = pick_cert()
    if cert is None:
        print("\n本机没有代码签名证书，无法签名。")
        print("买 Certum 开源证书并激活 SimplySign 之后再跑这个脚本：")
        print("  1. https://certum.store/code-signing.html → Open Source Code Signing in the Cloud")
        print("  2. 按邮件指引装 SimplySign Desktop，用收到的激活码登录")
        print("  3. 证书出现在证书库后，重跑本脚本")
        print("\n没有证书也应能正常打包（不带签名）——用 `npm run dist`。")
        return 1

    print(f"使用证书: {cert['subject']}（到期 {cert['not_after']}）")

    # ffmpeg 准备工作与 npm run dist 一致
    if (ROOT / "tools" / "prepare_ffmpeg.py").exists():
        code = run([sys.executable, "..\\tools\\prepare_ffmpeg.py"], DESKTOP)
        if code != 0:
            print("prepare_ffmpeg 失败，中止。")
            return code

    TEMP_CONFIG.write_text(
        json.dumps(build_config(cert), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"临时配置已写入 {TEMP_CONFIG.name}（gitignored）")
    try:
        code = run(
            ["npx", "electron-builder", "--win", "nsis", "--publish", "never",
             "--config", TEMP_CONFIG.name],
            DESKTOP,
        )
    finally:
        TEMP_CONFIG.unlink(missing_ok=True)

    if code != 0:
        print(f"打包失败，退出码 {code}")
        return code

    pkg = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    installer = DESKTOP / "release" / f"Cairn-{pkg['version']}-setup.exe"
    if not installer.exists():
        print(f"没找到产物 {installer}")
        return 3
    return 0 if verify(installer, signtool) else 4


if __name__ == "__main__":
    sys.exit(main())
