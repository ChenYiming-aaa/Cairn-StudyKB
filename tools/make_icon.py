"""生成 Cairn 的应用图标（一条命令产出 ico / png / svg 三份）。

设计：墨绿圆角方块 + 四块叠石 —— cairn 本义就是"路标石堆"，堆叠本身就表示
"一层层垒起来的知识"。刻意只用纯色块，因为 16×16 的任务栏图标才是真实考验：
渐变色、细描边在这个尺寸下全糊成一团，只有"深底 + 亮块"的结构能认出来。

用法（系统 Python 需装 Pillow；刻意不加进后端依赖，图标不是运行期需求）：

    python tools/make_icon.py

产物：
    desktop/build/icon.ico      多尺寸（16/24/32/48/64/128/256），electron-builder 与 NSIS 用
    desktop/build/icon.png      512×512，dev 模式下 BrowserWindow 的窗口图标
    frontend/public/favicon.ico 16/32/48，浏览器页签
    frontend/public/logo.svg    同几何的矢量版，界面里当品牌标用

几何全部取自下面的常量，SVG 与位图因此不会漂移 —— 想调形状只改这里。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

BG_TOP = (69, 120, 106)      # #45786a
BG_BOTTOM = (53, 89, 77)     # #35594d
SHADOW = (33, 58, 50)
SHADOW_ALPHA = 88

# (中心 x, 中心 y, 宽, 高, 圆角系数, 旋转角度, 填充色) —— 全是相对画布的比例，从下往上画。
# 圆角系数 = 圆角半径 / 高度：0.5 是纯胶囊（太像进度条），0.40 才是"被水磨圆的石头"。
# 每块给 ±2~4° 的旋转和一点横向错位，堆叠才自然 —— 全对齐会读成"信号强度"图标。
STONES = [
    (0.500, 0.730, 0.660, 0.185, 0.42, -1.8, (237, 230, 213)),
    (0.517, 0.560, 0.520, 0.165, 0.46, 2.6, (226, 217, 194)),
    (0.487, 0.400, 0.400, 0.145, 0.44, -3.2, (243, 237, 224)),
    (0.505, 0.255, 0.245, 0.115, 0.48, 2.0, (236, 229, 211)),
]

RADIUS = 0.225   # 圆角半径 / 画布边长（macOS 风格的 squircle 感，Windows 上也不违和）
SS = 4           # 超采样倍数：先画大再缩，边缘才没有锯齿
MASTER = 1024    # 主图边长，所有尺寸都从它缩


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """纯 Pillow 画竖直渐变：逐行填色，比引 numpy 省一个依赖。"""
    img = Image.new("RGB", (1, size), top)
    px = img.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return img.resize((size, size), Image.NEAREST)


def _stone_mask(big: int, w: float, h: float, rf: float, angle: float) -> Image.Image:
    """单块石头的 alpha 蒙版（已旋转）。只算一次，阴影和石头本体复用它。"""
    lw = max(2, round(w * big))
    lh = max(2, round(h * big))
    pad = max(2, round(0.02 * big))          # 旋转后四角会超出去，留一圈余量
    layer = Image.new("L", (lw + 2 * pad, lh + 2 * pad), 0)
    ImageDraw.Draw(layer).rounded_rectangle(
        (pad, pad, pad + lw - 1, pad + lh - 1), radius=round(rf * lh), fill=255
    )
    return layer.rotate(angle, resample=Image.BICUBIC, expand=True)


def _paste(canvas: Image.Image, mask: Image.Image, cx: float, cy: float,
           color: tuple, alpha: int = 255) -> None:
    """按蒙版把一块纯色贴到画布上（Pillow 的 alpha_composite 自带正确混合）。"""
    layer = Image.new("RGBA", mask.size, color + (255,))
    layer.putalpha(mask if alpha >= 255 else mask.point(lambda v: v * alpha // 255))
    canvas.alpha_composite(layer, dest=(round(cx - mask.width / 2), round(cy - mask.height / 2)))


def render(size: int = MASTER) -> Image.Image:
    """画出带透明圆角的成品图（RGBA）。"""
    big = size * SS
    canvas = _vertical_gradient(big, BG_TOP, BG_BOTTOM).convert("RGBA")

    # 圆角遮罩：先画白圆角矩形，再把它的 alpha 套到背景上
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=round(RADIUS * big), fill=255
    )
    canvas.putalpha(mask)

    for cx, cy, w, h, rf, angle, color in STONES:
        stone = _stone_mask(big, w, h, rf, angle)
        # 每块石头先垫一层下沉的暗影，堆叠关系才立得住（16px 下就靠它分层）
        _paste(canvas, stone, cx * big, cy * big + 0.012 * big, SHADOW, SHADOW_ALPHA)
        _paste(canvas, stone, cx * big, cy * big, color)

    return canvas.resize((size, size), Image.LANCZOS)


def build_svg() -> str:
    """同几何的矢量版。坐标按 viewBox 56 直接算，避免手抄比例出错。"""
    box = 56
    r_bg = RADIUS * box
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 56" width="56" height="56"'
        ' role="img" aria-label="Cairn">',
        "<defs>",
        '<linearGradient id="cairn-bg" x1="0" y1="0" x2="0" y2="1">',
        f'<stop offset="0" stop-color="#{BG_TOP[0]:02x}{BG_TOP[1]:02x}{BG_TOP[2]:02x}"/>',
        f'<stop offset="1" stop-color="#{BG_BOTTOM[0]:02x}{BG_BOTTOM[1]:02x}{BG_BOTTOM[2]:02x}"/>',
        "</linearGradient>",
        "</defs>",
        f'<rect width="56" height="56" rx="{r_bg:.2f}" fill="url(#cairn-bg)"/>',
    ]
    for cx, cy, w, h, rf, angle, color in STONES:
        x = (cx - w / 2) * box
        y = (cy - h / 2) * box
        rotate = f' transform="rotate({angle:g} {cx * box:.2f} {cy * box:.2f})"'
        hexcolor = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
        parts.append(f"<g{rotate}>")
        parts.append(
            f'<rect x="{x:.2f}" y="{y + 0.012 * box:.2f}" width="{w * box:.2f}"'
            f' height="{h * box:.2f}" rx="{rf * h * box:.2f}" fill="rgba(33,58,50,0.35)"/>'
        )
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w * box:.2f}"'
            f' height="{h * box:.2f}" rx="{rf * h * box:.2f}" fill="{hexcolor}"/>'
        )
        parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> int:
    master = render(MASTER)
    written: list[tuple[Path, str]] = []

    ico_main = ROOT / "desktop" / "build" / "icon.ico"
    ico_main.parent.mkdir(parents=True, exist_ok=True)
    master.save(ico_main, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    written.append((ico_main, f"{ico_main.stat().st_size / 1024:.1f} KB"))

    png_main = ROOT / "desktop" / "build" / "icon.png"
    master.resize((512, 512), Image.LANCZOS).save(png_main, optimize=True)
    written.append((png_main, f"{png_main.stat().st_size / 1024:.1f} KB"))

    public = ROOT / "frontend" / "public"
    public.mkdir(parents=True, exist_ok=True)
    favicon = public / "favicon.ico"
    master.save(favicon, sizes=[(16, 16), (32, 32), (48, 48)])
    written.append((favicon, f"{favicon.stat().st_size / 1024:.1f} KB"))

    logo = public / "logo.svg"
    logo.write_text(build_svg(), encoding="utf-8")
    written.append((logo, f"{logo.stat().st_size} B"))

    for path, size in written:
        print(f"  {path.relative_to(ROOT)}  {size}")
    # 自证：把 ico 读回来，确认真的是多尺寸而不是一个尺寸改后缀
    with Image.open(ico_main) as probe:
        frames = getattr(probe, "n_frames", 1)
        print(f"icon.ico 内含 {frames} 个尺寸，最大 {probe.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
