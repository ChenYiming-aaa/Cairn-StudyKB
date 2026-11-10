"""给 README 补拍设置窗口的「下载」页截图（M8 T8.7）。

为什么单独一个脚本：`backend/scripts/verify_m7.py --shots` 已经负责那 10 张图，
但它只拍「外观」页；「下载」页是 v0.2.0 才有的界面，塞进 M7 验收脚本会混淆职责。

复用 verify_m7 的三件事，不重复造：
  - 临时数据目录 + `CAIRN_ENV_STRICT=1` 隔离（**不碰你真实的 data.db**）
  - `start_server()` 起进程内后端
  - 1440×900 的 viewport（与现有 10 张图一致）

用法（必须先构建前端，脚本测的是后端吐的 dist）：
    cd frontend && npm run build
    python tools/shots_settings.py                    # 覆盖 docs/images/11-settings-downloads.png
    python tools/shots_settings.py --out data/shots   # 先出到临时目录看效果
    python tools/shots_settings.py --only about       # 只拍「关于」页

「关于」页注意：浏览器里没有 preload，更新区会显示「当前窗口不支持检查更新」；
打包版才有真按钮。所以默认只拍「下载」页。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

import verify_m7 as M7  # noqa: E402  —— 它一 import 就把数据目录隔离好了


def main() -> int:
    out = ROOT / "docs" / "images"
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else "downloads"
    out.mkdir(parents=True, exist_ok=True)

    if not (M7.DIST / "index.html").exists():
        print("× 找不到 frontend/dist/index.html —— 先 cd frontend && npm run build")
        return 2

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("× 没装 playwright —— cd backend && uv add playwright && uv run playwright install chromium")
        return 2

    port = M7.free_port()
    server, base = M7.start_server(port)
    shots: list[str] = []

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge")
            except Exception:
                browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            ctx.add_init_script("try{localStorage.setItem('cairn.setup.dismissed','1')}catch(e){}")
            page = ctx.new_page()

            page.goto(base, wait_until="networkidle")
            page.wait_for_selector(".today-bar", timeout=20_000)
            page.get_by_role("button", name="设置").click()
            page.wait_for_selector("[role='dialog']")

            targets = ["下载"] if only == "downloads" else ["关于"]
            for tab in targets:
                page.get_by_role("tab", name=re.compile(f"^{tab}")).click()
                # 下载页要等 /api/components 回来（三张卡各有 size/sha256），关于页等版本号
                page.wait_for_timeout(1200)
                name = "11-settings-downloads.png" if tab == "下载" else "12-settings-about.png"
                page.screenshot(path=str(out / name))
                shots.append(name)

            page.keyboard.press("Escape")
            browser.close()
    finally:
        server.should_exit = True

    for name in shots:
        size = (out / name).stat().st_size
        print(f"PASS {name}  {size / 1024:.0f} KB  -> {out}")
    print(f"共 {len(shots)} 张（临时数据目录：{M7.TMP}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
