"""动效 token 落地的浏览器实测。

读的是**构建产物**里那份 CSS，不是源码 —— 只证明源码写对了没有意义。
要证的是三件事：
1. 七个 --dur-* / --ease-* 在 :root 上都解析出非空值（拼错会静默变 0s）；
2. 关键组件的 transition-duration / timing-function 与收敛目标一致；
3. 深色主题下 PDF 页的阴影不再是 6%（--shadow-1 那条缺陷已修）。

用法：先 `cd frontend && npm run build`，再在仓库根跑
`uv run --project backend python tools/check_motion_tokens.py`。
读的是构建产物里的 CSS —— 源码写对不等于产物对，压缩会把 150ms 写成 .15s，
所以断言按数值比，不按字面量比。

注意：`::-webkit-progress-value` 这类 UA 伪元素取不到计算样式，所以原生 `.meter`
的填充过渡不在这里断言，它的正确性靠 verify_m7 与人工看。
"""
import glob
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
css = sorted(glob.glob(str(ROOT / "frontend" / "dist" / "assets" / "index-*.css")))
if not css:
    sys.exit("找不到构建产物 CSS，先跑 npm run build")
CSS_TEXT = Path(css[-1]).read_text(encoding="utf-8")

HTML = """<!doctype html><html data-theme="paper" data-mode="%s"><head><style>%s</style></head>
<body>
  <button class="btn" id="btn">按钮</button>
  <input class="input" id="input">
  <div class="pg" id="pg" style="width:80px;height:60px"></div>
  <div class="progress-bar" id="bar"><i></i></div>
</body></html>"""

# 只补测具自己的东西，进度条/按钮一律用产物里的真实规则 —— 复制一份定义会让断言失去意义
EXTRA = """
.pg { box-shadow: var(--shadow-sm); }
"""

PROBES = [
    ("--dur-fast", "--dur-fast"),
    ("--dur-overlay", "--dur-overlay"),
    ("--dur-enter", "--dur-enter"),
    ("--dur-progress", "--dur-progress"),
    ("--dur-slow", "--dur-slow"),
    ("--ease-out", "--ease-out"),
    ("--ease-linear", "--ease-linear"),
    ("--overlay-scrim", "--overlay-scrim"),
    ("--overlay-scrim-soft", "--overlay-scrim-soft"),
]


def run(pw):
    try:
        browser = pw.chromium.launch(channel="msedge")
    except Exception:
        browser = pw.chromium.launch()
    failed = []
    for mode in ("light", "dark"):
        page = browser.new_page()
        page.set_content(HTML % (mode, CSS_TEXT + EXTRA))
        data = page.evaluate(
            """(probes) => {
                const root = getComputedStyle(document.documentElement);
                const out = {tokens: {}, parts: {}};
                for (const p of probes) out.tokens[p] = root.getPropertyValue(p).trim();
                const q = (sel) => {
                    const el = document.querySelector(sel);
                    return el ? getComputedStyle(el) : null;
                };
                const btn = q('#btn'), input = q('#input'), bar = q('#bar i'), pg = q('#pg');
                out.parts.btnDur = btn.transitionDuration;
                out.parts.btnFn = btn.transitionTimingFunction;
                out.parts.inputDur = input.transitionDuration;
                out.parts.barDur = bar.transitionDuration;
                out.parts.barFn = bar.transitionTimingFunction;
                out.parts.barH = q('#bar').height;
                out.parts.pgShadow = pg.boxShadow;

                // 主题切换抑制帧：挂上 .theming 后过渡必须整体消失
                document.documentElement.classList.add('theming');
                out.parts.themingBtnDur = q('#btn').transitionDuration;
                document.documentElement.classList.remove('theming');
                out.parts.afterThemingBtnDur = q('#btn').transitionDuration;
                return out;
            }""",
            [p[1] for p in PROBES],
        )
        print(f"\n=== mode={mode} ===")
        for name, val in data["tokens"].items():
            print(f"  {name:<16} = {val!r}")
            if not val:
                failed.append(f"{mode}: {name} 解析为空")
        for k, v in data["parts"].items():
            print(f"  {k:<16} = {v}")

        # 断言：token 必须是真实时间值。
        # 不能按源码字面量比 —— 构建产物会把 150ms 压成 .15s，所以统一换算成 ms 再比数字。
        def to_ms(v):
            v = v.strip()
            if v.endswith("ms"):
                return float(v[:-2])
            if v.endswith("s"):
                return float(v[:-1]) * 1000
            raise ValueError(f"不是时间值: {v!r}")

        expect = {
            "--dur-fast": 150, "--dur-overlay": 140, "--dur-enter": 180,
            "--dur-progress": 200, "--dur-slow": 350,
        }
        for name, want in expect.items():
            got = data["tokens"][name]
            try:
                if to_ms(got) != want:
                    failed.append(f"{mode}: {name} 期望 {want}ms，实际 {got!r}")
            except ValueError as e:
                failed.append(f"{mode}: {name} {e}")

        # 遮罩是颜色，不参与时间断言；alpha 按数值比（压缩会把 0.42 写成 .42）
        for name, want in (("--overlay-scrim", 0.42), ("--overlay-scrim-soft", 0.32)):
            val = data["tokens"][name]
            alpha = val.rsplit("/", 1)[-1].strip(" )") if "/" in val else ""
            try:
                if abs(float(alpha) - want) > 1e-6:
                    failed.append(f"{mode}: {name} 的 alpha 应为 {want} -> {val!r}")
            except ValueError:
                failed.append(f"{mode}: {name} 没解析成颜色 -> {val!r}")

        # 断言：消费者算出来的值。.btn 同时过渡三个属性，所以是逗号列表，取第一个即可。
        def first(s):
            return s.split(",")[0].strip()

        if to_ms(first(data["parts"]["btnDur"])) != 150:
            failed.append(f"{mode}: .btn 时长 {data['parts']['btnDur']}")
        # v0.5 起按钮悬停反馈统一走 --ease-out（减速收尾）；改造前是 UA 默认的 `ease`。
        # 这里仍按精确值比，不是放宽成「有缓动就行」。
        if first(data["parts"]["btnFn"]) != "ease-out":
            failed.append(f"{mode}: .btn 缓动 {data['parts']['btnFn']}")
        if to_ms(data["parts"]["inputDur"]) != 150:
            failed.append(f"{mode}: .input 时长 {data['parts']['inputDur']}")
        if to_ms(data["parts"]["barDur"]) != 200:
            failed.append(f"{mode}: 进度条时长 {data['parts']['barDur']}")
        if data["parts"]["barFn"] != "ease-out":
            failed.append(f"{mode}: 进度条缓动 {data['parts']['barFn']}")
        if data["parts"]["barH"] != "4px":
            failed.append(f"{mode}: 进度条高度 {data['parts']['barH']}（应为统一的 4px）")
        if data["parts"]["themingBtnDur"] != "0s":
            failed.append(f"{mode}: .theming 下过渡没被禁掉 -> {data['parts']['themingBtnDur']}")
        if data["parts"]["afterThemingBtnDur"] == "0s":
            failed.append(f"{mode}: 移除 .theming 后过渡没恢复")

        # 断言：深色下阴影强度。浅色 0.06 / 深色 0.5（修复前恒为 0.06）
        shadow = data["parts"]["pgShadow"]
        if mode == "dark":
            if "0.5" not in shadow:
                failed.append(f"dark: PDF 页阴影仍是 {shadow}（--shadow-1 未真正修复）")
        else:
            if "0.06" not in shadow:
                failed.append(f"light: PDF 页阴影 {shadow}")

        page.close()
    browser.close()
    return failed


with sync_playwright() as pw:
    fails = run(pw)

print("\n" + "=" * 60)
if fails:
    for f in fails:
        print("FAIL", f)
    sys.exit(1)
print("全部断言通过")
