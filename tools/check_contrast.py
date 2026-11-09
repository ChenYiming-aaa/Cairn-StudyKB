#!/usr/bin/env python3
"""主题配色：生成 + 对比度验收（M6 T6.7）。

两种用法：

    python tools/check_contrast.py           # 校验 frontend/src/styles/tokens.css
    python tools/check_contrast.py --write   # 重新生成 tokens.css

为什么生成器与校验器放在一起：6 套 × 2 模式 = 12 组色板、每组二十多个令牌，
手算必错。Part 1 的教训就是「按原规则算 text-3 只有 2.19:1，一套都过不了」。
**改配色只改本文件顶部的 PALETTES 与派生函数，然后 `--write`**，
tokens.css 是产物，不要手改（手改会在下一次 --write 时被覆盖）。

校验的口径来自 `docs/dev/milestones/M6-设置与个性化.md` §3 的硬标准：
  text-1 / text-2 on bg-1 ≥ 4.5     text-3 on bg-1、bg-2 ≥ 3
  on-primary on primary ≥ 4.5       primary-ink on primary-soft ≥ 4.5
  success / warning / danger on bg-1 ≥ 3
  text-1 on mark ≥ 4.5
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "frontend" / "src" / "styles" / "tokens.css"

# ── 六套调色板（唯一真源）────────────────────────────────────
# 取自 dsh-ui-ux-pro-max 的 data/index.json `domains.color`（No. 见注释）；
# paper 是 v0.1.0 的默认主题，保留原手调值，不从调色板库取。
PALETTES = {
    "paper": {
        "label": "纸石绿",
        "source": "v0.1.0 现有 tokens.css",
        "primary": "#3F6F5F",
        "on_primary": "#FFFFFF",
        "accent": "#B8791F",
        "bg": "#F6F5F1",
        "fg": "#23211C",
        "card": "#FFFEFA",
        "muted": "#EFEEE7",
        "muted_fg": "#5C574D",
        "border": "#E2DFD5",
        "destructive": "#B3453A",
    },
    "notes": {
        "label": "暖墨",
        "source": "Notes & Writing App (93)",
        "primary": "#78716C",
        "on_primary": "#FFFFFF",
        "accent": "#D97706",
        "bg": "#FFFBEB",
        "fg": "#0F172A",
        "card": "#FFFFFF",
        "muted": "#F6F6F6",
        "muted_fg": "#475569",
        "border": "#EEEDED",
        "destructive": "#DC2626",
    },
    "chestnut": {
        "label": "栗墨",
        "source": "Diary & Journal App (100)",
        "primary": "#92400E",
        "on_primary": "#FFFFFF",
        "accent": "#6366F1",
        "bg": "#FFFBEB",
        "fg": "#0F172A",
        "card": "#FFFFFF",
        "muted": "#F8F3F0",
        "muted_fg": "#475569",
        "border": "#F1E8E2",
        "destructive": "#DC2626",
    },
    "docs": {
        "label": "石板蓝",
        "source": "Knowledge Base/Documentation (30)",
        "primary": "#475569",
        "on_primary": "#FFFFFF",
        "accent": "#2563EB",
        "bg": "#F8FAFC",
        "fg": "#1E293B",
        "card": "#FFFFFF",
        "muted": "#EAEFF3",
        "muted_fg": "#475569",
        "border": "#E2E8F0",
        "destructive": "#DC2626",
    },
    "study": {
        "label": "学习紫",
        "source": "Flashcard & Study Tool (103)",
        "primary": "#7C3AED",
        "on_primary": "#FFFFFF",
        "accent": "#059669",
        "bg": "#FAF5FF",
        "fg": "#0F172A",
        "card": "#FFFFFF",
        "muted": "#F7F3FD",
        "muted_fg": "#475569",
        "border": "#EFE7FC",
        "destructive": "#DC2626",
    },
    "teal": {
        "label": "效率青",
        "source": "Productivity Tool (16)",
        "primary": "#0D9488",
        "on_primary": "#000000",
        "accent": "#EA580C",
        "bg": "#F0FDFA",
        "fg": "#134E4A",
        "card": "#FFFFFF",
        "muted": "#E8F1F4",
        "muted_fg": "#475569",
        "border": "#99F6E4",
        "destructive": "#DC2626",
    },
}

THEME_ORDER = ("paper", "notes", "chestnut", "docs", "study", "teal")

# 2026-11-09 裁决：警示色统一琥珀（不能是蓝/绿/靛）；成功色除 study 用其 Accent 外统一
FIXED_WARNING = "#B45309"
FIXED_SUCCESS = "#3F8F5F"
FIXED_MARK = "#F59E0B"

DARK_BG_L = (0.12, 0.16, 0.20)      # bg-0 / bg-1 / bg-2
DARK_SAT_CAP = 0.14                 # 深色底饱和度封顶（S-8 第 3 条 / 2026-11-09 裁决）
DARK_TEXT_S = 0.08
DARK_PRIMARY_L = 0.65
DARK_PRIMARY_SAT_CAP = 0.60         # 2026-11-09 裁决：不封顶时 teal 会变成荧光 #5BF1E3
BORDER_SAT_LIMIT = 0.25             # 描边饱和度超过这条就与底色混一半（目前只有 teal 命中）

# 校验用的对比度门槛：令牌名 → (前景, 背景, 最低比)
PAIRS = (
    ("text-1/bg-1", "text-1", "bg-1", 4.5),
    ("text-2/bg-1", "text-2", "bg-1", 4.5),
    ("text-3/bg-1", "text-3", "bg-1", 3.0),
    ("text-3/bg-2", "text-3", "bg-2", 3.0),
    ("on-primary/primary", "on-primary", "primary", 4.5),
    ("primary-ink/primary-soft", "primary-ink", "primary-soft", 4.5),
    ("success/bg-1", "success", "bg-1", 3.0),
    ("warning/bg-1", "warning", "bg-1", 3.0),
    ("danger/bg-1", "danger", "bg-1", 3.0),
    ("text-1/mark", "text-1", "mark", 4.5),
)


# ── 颜色数学 ────────────────────────────────────────────────


def to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raise ValueError(f"不是合法的十六进制颜色：{value}")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(ch))):02X}" for ch in rgb)


def rgb_to_hsl(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (ch / 255 for ch in rgb)
    hi, lo = max(r, g, b), min(r, g, b)
    light = (hi + lo) / 2
    if hi == lo:
        return 0.0, 0.0, light
    delta = hi - lo
    sat = delta / (2 - hi - lo) if light > 0.5 else delta / (hi + lo)
    if hi == r:
        hue = ((g - b) / delta) % 6
    elif hi == g:
        hue = (b - r) / delta + 2
    else:
        hue = (r - g) / delta + 4
    return hue * 60, sat, light


def hsl_to_rgb(hue: float, sat: float, light: float) -> tuple[float, float, float]:
    hue = (hue % 360) / 360
    sat = max(0.0, min(1.0, sat))
    light = max(0.0, min(1.0, light))
    if sat == 0:
        gray = light * 255
        return gray, gray, gray
    q = light * (1 + sat) if light < 0.5 else light + sat - light * sat
    p = 2 * light - q

    def channel(t: float) -> float:
        t = t % 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    return (
        channel(hue + 1 / 3) * 255,
        channel(hue) * 255,
        channel(hue - 1 / 3) * 255,
    )


def mix(base: str, other: str, weight: float) -> str:
    """`weight` 是 other 的占比：0 = 全是 base，1 = 全是 other。"""
    a, b = to_rgb(base), to_rgb(other)
    return to_hex(tuple(a[i] * (1 - weight) + b[i] * weight for i in range(3)))


def hsl(hex_value: str) -> tuple[float, float, float]:
    return rgb_to_hsl(to_rgb(hex_value))


def from_hsl(hue: float, sat: float, light: float) -> str:
    return to_hex(hsl_to_rgb(hue, sat, light))


def luminance(hex_value: str) -> float:
    channels = []
    for ch in to_rgb(hex_value):
        value = ch / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def fade_to_pass(start: str, bg: str, target: float) -> str:
    """把 `start` 往 `bg` 混合到「恰好仍 ≥ target」的最浅/最接近背景的一档。

    `text-3` 用它：固定 45% 实测只有 2.19:1，必须按目标反解比例（S-8 第 1 条）。
    """
    lo, hi = 0.0, 1.0
    best = start
    for _ in range(40):
        mid = (lo + hi) / 2
        candidate = mix(start, bg, mid)
        if contrast(candidate, bg) >= target:
            best, lo = candidate, mid
        else:
            hi = mid
    return best


def darken_until(color: str, bg: str, target: float) -> str:
    """降明度直到对比度达标（用于 `primary-ink`）。"""
    hue, sat, light = hsl(color)
    for _ in range(60):
        if contrast(from_hsl(hue, sat, light), bg) >= target:
            break
        light = max(0.02, light - 0.01)
    return from_hsl(hue, sat, light)


def lift_until(color: str, bg: str, target: float, floor: float = 0.62) -> str:
    """提明度直到对比度达标（用于深色模式下的语义色）。"""
    hue, sat, light = hsl(color)
    light = max(light, floor)
    for _ in range(60):
        if contrast(from_hsl(hue, sat, light), bg) >= target:
            break
        light = min(0.95, light + 0.01)
    return from_hsl(hue, min(sat, 0.88), light)


def lighten_until(color: str, bg: str, target: float) -> str:
    """只提明度（不动色相饱和度）直到对比度达标，用于深色模式的 `primary-ink`。"""
    hue, sat, light = hsl(color)
    for _ in range(60):
        if contrast(from_hsl(hue, sat, light), bg) >= target:
            break
        light = min(0.95, light + 0.005)
    return from_hsl(hue, sat, light)


# ── 派生 ────────────────────────────────────────────────────


def shift_lightness(
    color: str, light: float | None = None, factor: float | None = None,
    sat_cap: float | None = None,
) -> str:
    hue, sat, level = hsl(color)
    if sat_cap is not None:
        sat = min(sat, sat_cap)
    level = light if light is not None else level * (factor or 1.0)
    return from_hsl(hue, sat, level)


def accent_of(tid: str) -> str:
    """`study` 的成功色用调色板 Accent（本身就是绿）；其余统一 3F8F5F。"""
    return PALETTES[tid]["accent"] if tid == "study" else FIXED_SUCCESS


def light_tokens(tid: str) -> dict:
    palette = PALETTES[tid]
    bg0, bg1, bg2 = palette["bg"], palette["card"], palette["muted"]
    primary = palette["primary"]
    success, warning, danger = accent_of(tid), FIXED_WARNING, palette["destructive"]
    text3 = fade_to_pass(palette["muted_fg"], bg2, 3.08)
    soft = mix(bg1, primary, 0.08)
    # 调色板 Border 若是高饱和（teal 的 #99F6E4），直接当描边会扎眼 → 与底色混一半
    border = palette["border"]
    if hsl(border)[1] > BORDER_SAT_LIMIT:
        border = mix(border, bg0, 0.5)
    return {
        "primary": primary,
        "primary-soft": soft,
        "primary-ink": darken_until(primary, soft, 4.5),
        "primary-border": mix(bg1, primary, 0.28),
        "primary-hover": shift_lightness(primary, factor=0.86),
        "on-primary": palette["on_primary"],
        "success": success,
        "success-soft": mix(bg1, success, 0.10),
        "success-border": mix(bg1, success, 0.30),
        "warning": warning,
        "warning-soft": mix(bg1, warning, 0.10),
        "warning-border": mix(bg1, warning, 0.30),
        "danger": danger,
        "danger-soft": mix(bg1, danger, 0.10),
        "danger-border": mix(bg1, danger, 0.30),
        "text-1": palette["fg"],
        "text-2": palette["muted_fg"],
        "text-3": text3,
        "bg-0": bg0,
        "bg-1": bg1,
        "bg-2": bg2,
        "border": border,
        "mark": mix(bg1, FIXED_MARK, 0.32),
        "scrollbar": mix(bg2, palette["fg"], 0.10),
        "scrollbar-hover": mix(bg2, palette["fg"], 0.16),
        "skeleton": mix(bg2, bg1, 0.55),
    }


def dark_tokens(tid: str) -> dict:
    palette = PALETTES[tid]
    # 深色底的色相取**主色**而非 Background：paper/notes/chestnut 的背景色相都是 48°，
    # 照文档字面算出来三套深色底完全一样（#252318），暗色下就分不出主题了。
    hue, sat, _ = hsl(palette["primary"])
    sat = min(sat, DARK_SAT_CAP)
    bg0, bg1, bg2 = (from_hsl(hue, sat, level) for level in DARK_BG_L)
    primary = shift_lightness(
        palette["primary"],
        light=DARK_PRIMARY_L,
        sat_cap=DARK_PRIMARY_SAT_CAP,
    )
    soft = mix(bg1, primary, 0.12)
    success = lift_until(accent_of(tid), bg1, 3.0)
    warning = lift_until(FIXED_WARNING, bg1, 3.0)
    danger = lift_until(palette["destructive"], bg1, 3.0)
    text1 = from_hsl(hue, DARK_TEXT_S, 0.92)
    text2 = from_hsl(hue, DARK_TEXT_S, 0.72)
    text3 = from_hsl(hue, DARK_TEXT_S, 0.54)
    # text-3 若在 bg-2（凹陷面）上不够，继续压明度
    while contrast(text3, bg2) < 3.05:
        _h, _s, level = hsl(text3)
        text3 = from_hsl(_h, _s, max(0.30, level - 0.01))
    on_primary = darken_until(
        shift_lightness(palette["primary"], light=0.12, sat_cap=DARK_PRIMARY_SAT_CAP), primary, 4.5
    )
    return {
        "primary": primary,
        "primary-soft": soft,
        "primary-ink": lighten_until(primary, soft, 4.5),
        "primary-border": mix(bg1, primary, 0.45),
        "primary-hover": shift_lightness(
            palette["primary"], light=0.72, sat_cap=DARK_PRIMARY_SAT_CAP
        ),
        "on-primary": on_primary,
        "success": success,
        "success-soft": mix(bg1, success, 0.16),
        "success-border": mix(bg1, success, 0.34),
        "warning": warning,
        "warning-soft": mix(bg1, warning, 0.16),
        "warning-border": mix(bg1, warning, 0.34),
        "danger": danger,
        "danger-soft": mix(bg1, danger, 0.16),
        "danger-border": mix(bg1, danger, 0.34),
        "text-1": text1,
        "text-2": text2,
        "text-3": text3,
        "bg-0": bg0,
        "bg-1": bg1,
        "bg-2": bg2,
        "border": mix(bg1, "#FFFFFF", 0.10),
        "mark": mix(bg1, FIXED_MARK, 0.24),
        "scrollbar": mix(bg2, "#FFFFFF", 0.12),
        "scrollbar-hover": mix(bg2, "#FFFFFF", 0.20),
        "skeleton": mix(bg2, "#FFFFFF", 0.08),
    }


# ── 渲染 ────────────────────────────────────────────────────

TOKEN_ORDER = (
    "primary", "primary-soft", "primary-ink", "primary-border", "primary-hover", "on-primary",
    "success", "success-soft", "success-border",
    "warning", "warning-soft", "warning-border",
    "danger", "danger-soft", "danger-border",
    "text-1", "text-2", "text-3",
    "bg-0", "bg-1", "bg-2",
    "border", "mark", "scrollbar", "scrollbar-hover", "skeleton",
)
TOKEN_NOTE = {
    "primary-soft": "选中态底色",
    "primary-ink": "主色作文本时用（primary 当底色时对比度不够）",
    "primary-border": "选中/悬停态的描边（比 border 更有指向性）",
    "on-primary": "主色底上的文字（teal 是黑字）",
    "text-3": "弱化文字，已按 ≥3:1 反解混合比例",
    "mark": "搜索命中高亮",
    "scrollbar": "滚动条滑块",
    "skeleton": "骨架屏渐变中间色",
}

HEADER = '''/* Cairn design tokens。

**配色部分是生成物**：`python tools/check_contrast.py --write`。
改配色去改 `tools/check_contrast.py` 的 PALETTES 与派生函数，不要手改本文件——
12 组色板（6 套 × 明暗）手算必错，Part 1 就是这么翻的车（text-3 实际只有 2.19:1）。

结构：
  :root                     间距 / 字号 / 圆角 / 字体 / 版面尺寸 / 阴影
  [data-theme="x"]          浅色配色（6 套）
  [data-theme="x"][data-mode="dark"]  深色配色
  html[data-fs="sm|lg"]     字号三档（默认 md）

任何组件都不许写死颜色，一律引用这里的变量。
*/

'''

ROOT_BLOCK = ''':root {
  /* 间距 */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;

  /* 字号（标准档；`html[data-fs]` 覆盖） */
  --fs-xs: 12px;
  --fs-sm: 13px;
  --fs-md: 14px;
  --fs-lg: 16px;
  --fs-xl: 20px;

  /* 圆角 */
  --radius-sm: 8px;
  --radius-md: 12px;

  /* 行高 */
  --lh-body: 1.6;
  --lh-title: 1.4;

  /* 版面尺寸（--w-* 在 useLayout.js 里运行时改写：折叠时左栏/选择器/配置栏 = --w-rail，列表 = 0；
     这里的默认值只保证脚本未跑前的首帧不缺变量） */
  --w-sidebar: 232px;
  --w-list: 320px;
  --w-picker: 280px;
  --w-config: 300px;
  --w-rail: 44px;
  --h-topbar: 52px;

  /* 阴影（极轻，避免卡片堆叠感） */
  --shadow-sm: 0 1px 2px rgba(35, 33, 28, 0.06);
  --shadow-md: 0 8px 24px rgba(35, 33, 28, 0.12);

  /* 字体 */
  --font-ui: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei",
    "PingFang SC", "Hiragino Sans GB", sans-serif;
  --font-reading: "Songti SC", "Source Han Serif SC", "Noto Serif CJK SC", Georgia, serif;
  --font-mono: "Cascadia Code", "JetBrains Mono", Consolas, "Courier New", monospace;
}
'''

DARK_EXTRA = '''  /* 深色下阴影要更重，否则卡片浮不起来 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.5);
  --shadow-md: 0 8px 24px rgba(0, 0, 0, 0.55);
'''

FONT_TIERS = '''
/* ── 字号三档（设置 → 外观）────────────────────────────── */
html[data-fs="sm"] {
  --fs-xs: 11px;
  --fs-sm: 12px;
  --fs-md: 13px;
  --fs-lg: 15px;
  --fs-xl: 18px;
}

html[data-fs="lg"] {
  --fs-xs: 14px;
  --fs-sm: 15px;
  --fs-md: 16px;
  --fs-lg: 18px;
  --fs-xl: 23px;
}
'''


def render(tokens_by_theme: dict) -> str:
    parts = [HEADER, ROOT_BLOCK]
    for tid in THEME_ORDER:
        palette = PALETTES[tid]
        parts.append(
            f'/* ── {palette["label"]}（{tid}）· 浅色 — {palette["source"]} ── */\n'
            f'[data-theme="{tid}"] {{\n'
        )
        for name in TOKEN_ORDER:
            note = f'  /* {TOKEN_NOTE[name]} */' if name in TOKEN_NOTE else ""
            parts.append(f'  --c-{name}: {tokens_by_theme[(tid, "light")][name]};{note}\n')
        parts.append("}\n\n")
        parts.append(
            f'/* ── {palette["label"]}（{tid}）· 深色 ── */\n'
            f'[data-theme="{tid}"][data-mode="dark"] {{\n'
        )
        for name in TOKEN_ORDER:
            parts.append(f'  --c-{name}: {tokens_by_theme[(tid, "dark")][name]};\n')
        parts.append(DARK_EXTRA)
        parts.append("}\n\n")
    parts.append(FONT_TIERS)
    return "".join(parts)


# ── 校验 ────────────────────────────────────────────────────

BLOCK_RE = re.compile(r'\[data-theme="([a-z]+)"\](?:\[data-mode="dark"\])?\s*\{([^}]*)\}')
VAR_RE = re.compile(r"--c-([a-z0-9-]+)\s*:\s*([^;]+);")


def parse_tokens(text: str) -> dict:
    """把 tokens.css 里 12 个主题块解析成 {(theme, mode): {name: value}}。"""
    found: dict[tuple[str, str], dict[str, str]] = {}
    for match in re.finditer(
        r'\[data-theme="([a-z]+)"\]((?:\[data-mode="dark"\])?)\s*\{(.*?)\n\}',
        text,
        re.S,
    ):
        theme, dark, body = match.group(1), match.group(2), match.group(3)
        mode = "dark" if dark else "light"
        found[(theme, mode)] = {k: v.strip() for k, v in VAR_RE.findall(body)}
    return found


def check(text: str) -> list[str]:
    parsed = parse_tokens(text)
    problems: list[str] = []
    for tid in THEME_ORDER:
        for mode in ("light", "dark"):
            block = parsed.get((tid, mode))
            if not block:
                problems.append(f"{tid}/{mode}: 找不到主题块")
                continue
            for name in TOKEN_ORDER:
                value = block.get(name, "")
                if not value:
                    problems.append(f"{tid}/{mode}: --c-{name} 缺失或为空")
                    continue
                if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
                    problems.append(f"{tid}/{mode}: --c-{name} 不是六位十六进制（{value}）")
            if any(not block.get(n) for n in TOKEN_ORDER):
                continue
            for label, fg, bg, target in PAIRS:
                ratio = contrast(block[fg], block[bg])
                if ratio + 1e-9 < target:
                    problems.append(
                        f"{tid}/{mode}: {label} = {ratio:.2f}:1 < {target}:1"
                    )
    return problems


def main(argv: list[str]) -> int:
    tokens_by_theme = {
        (tid, mode): (light_tokens(tid) if mode == "light" else dark_tokens(tid))
        for tid in THEME_ORDER
        for mode in ("light", "dark")
    }
    if "--write" in argv:
        TOKENS.write_text(render(tokens_by_theme), encoding="utf-8")
        print(f"已写入 {TOKENS.relative_to(ROOT)}")

    text = TOKENS.read_text(encoding="utf-8")
    problems = check(text)
    print(f"{'=' * 58}")
    for tid in THEME_ORDER:
        for mode in ("light", "dark"):
            block = tokens_by_theme[(tid, mode)]
            worst = min(
                (contrast(block[fg], block[bg]), label)
                for label, fg, bg, _t in PAIRS
            )
            print(f"  {tid:9s} {mode:5s}  最低对比度 {worst[0]:.2f}:1（{worst[1]}）")
    print(f"{'=' * 58}")
    if problems:
        print(f"  {len(problems)} 项不达标：")
        for item in problems:
            print(f"    - {item}")
        return 1
    print(f"  6 套 × 明暗 × {len(PAIRS)} 组对比度全部达标")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
