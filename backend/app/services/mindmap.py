"""T3.7 思维导图：structured_note 的标题层级 → 树 → 纯 Python 手写 SVG。

为什么自己写（ADR-017）：学习页要单文件离线可开，前端 JS 库（markmap/mermaid/d3）
内联不进去；后端出 SVG 后既能给条目详情当图片，也能直接塞进导出 HTML。

为什么不留缓存（ADR-019）：笔记随时可能改，"图和笔记对不上"是最伤信任的 bug，
而几十个节点的生成成本只有 2–5ms。

输出约束（M3 §1 第 8–10 条）：零依赖、文字必须 XML 转义、不许出现 `<script>` 与外链。
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

# ── 版式（M3 §6.6）────────────────────────────────────────
# 每层的 x 位置由「上一层最宽节点 + 层间距」递推，而不是固定 层级×200：
# 笔记里出现长标题时（22 字 × 13px ≈ 310px），固定 200 会让下一层压在上一个框上。
NODE_H = 28          # 节点高
LEVEL_GAP = 64       # 相邻两层的水平留白
SIBLING_GAP = 8      # 同级子树间距
PAD = 16             # 画布留白
MAX_DEPTH = 4        # 超过 4 级的折叠掉（导图是概览，不是全文）
MAX_CHILDREN = 8     # 单个节点最多 8 个孩子，多出来的折成一条提示
TEXT_LIMIT = 24      # 超过 24 字符截为 22 + …
MIN_W = 64

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

# 四档配色写死 hex：导出 HTML 要自带颜色，不能靠 CSS 变量
_PALETTE = {
    "light": {
        0: ("#1D9E75", "#14624A", "#FFFFFF"),
        1: ("#E1F5EE", "#1D9E75", "#104E3A"),
        2: ("#EAF1FA", "#6E9BD8", "#22354F"),
        3: ("#FDF3E3", "#C79A4B", "#5C4114"),
        4: ("#F1EEE6", "#B3AA98", "#4A4439"),
    },
    "dark": {
        0: ("#2E8B6F", "#59C0A0", "#F2FBF7"),
        1: ("#1B3B32", "#59C0A0", "#CFEDE2"),
        2: ("#1E2C3F", "#6E9BD8", "#D6E4F7"),
        3: ("#3A2E18", "#C79A4B", "#F0E1C6"),
        4: ("#2E2B25", "#8C8577", "#DDD8CC"),
    },
}

_FONT = "'Microsoft YaHei','PingFang SC','Hiragino Sans GB',system-ui,sans-serif"


@dataclass
class Node:
    text: str
    children: list["Node"] = field(default_factory=list)


def _char_width(ch: str) -> float:
    """中文全角 13px、其余 7.2px。宁可算宽——留白不影响观感，重叠才是灾难。"""
    return 13.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 7.2


def node_width(text: str) -> int:
    return max(MIN_W, int(sum(_char_width(c) for c in text) + 24))


def clip(text: str) -> str:
    """折掉多余空白，超长截断。截断在渲染前做，宽度估算才准。"""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= TEXT_LIMIT else flat[: TEXT_LIMIT - 2] + "…"


def parse_tree(note: str | None, fallback_title: str, fallback_points=None) -> Node:
    """把 Markdown 标题层级读成树。

    第一个 `#` 挂在根**下面**而不是取代根：条目标题本来就在根上，
    否则笔记里那个 `# 间隔重复` 会把「条目标题」顶掉（M3 §6.6 的注意事项）。
    没有任何标题时退化成 根 = 条目标题，一级子节点 = key_points（最多 8 条）。
    """
    root = Node(clip(fallback_title) or "未命名条目")
    stack: list[tuple[int, Node]] = [(0, root)]

    for line in (note or "").splitlines():
        m = _HEADING.match(line)
        if not m:
            continue
        level, text = len(m.group(1)), clip(m.group(2))
        if not text:
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        node = Node(text)
        stack[-1][1].children.append(node)
        stack.append((level, node))

    if not root.children:
        points = [clip(p) for p in (fallback_points or []) if (p or "").strip()]
        root.children = [Node(p) for p in points[:8]]

    return _fold(root)


def _fold(node: Node, depth: int = 0) -> Node:
    """深度截到 MAX_DEPTH，孩子截到 MAX_CHILDREN，多出来的折成一条明示的提示。

    先建全树再剪枝，比在解析时判断简单；剪枝时留一条「…另 N 节」，
    用户才知道导图少东西，而不是以为笔记只有这么多。
    """
    if depth >= MAX_DEPTH:
        return Node(node.text)
    kept = [_fold(child, depth + 1) for child in node.children[:MAX_CHILDREN]]
    hidden = len(node.children) - len(kept)
    if hidden > 0:
        kept.append(Node(f"…另 {hidden} 节"))
    return Node(node.text, kept)


def layout(root: Node) -> tuple[list[tuple[Node, int, int, int, int]], int, int]:
    """四步布局（M3 §6.6）：后序定高度 → 前序定父节点 y → 定 x → 最后算 viewBox。

    返回 [(node, x, y中心, width, depth)], 画布宽, 画布高。
    """
    raw: list[tuple[Node, int, int, int]] = []  # (node, y中心, width, depth)
    cursor = 0.0

    def walk(node: Node, depth: int) -> int:
        nonlocal cursor
        if not node.children:
            y = cursor + NODE_H / 2
            cursor += NODE_H + SIBLING_GAP
        else:
            centers = [walk(child, depth + 1) for child in node.children]
            y = (centers[0] + centers[-1]) / 2
        raw.append((node, int(round(y)), node_width(node.text), depth))
        return y

    walk(root, 0)

    # 每一层的 x = 前面所有层「最宽节点 + 间距」的累加
    widest: dict[int, int] = {}
    for _, _, w, depth in raw:
        widest[depth] = max(widest.get(depth, 0), w)
    offset: dict[int, int] = {0: 0}
    for depth in range(1, max(widest) + 1):
        offset[depth] = offset[depth - 1] + widest[depth - 1] + LEVEL_GAP

    placed = [(node, offset[depth], y, w, depth) for node, y, w, depth in raw]
    right = max((x + w for _, x, _, w, _ in placed), default=0)
    bottom = max((y + NODE_H / 2 for _, _, y, _, _ in placed), default=NODE_H)
    return placed, int(right), int(bottom)


def _text(text: str) -> str:
    return html.escape(text, quote=True)


def render_svg(root: Node, theme: str = "light") -> str:
    """输出一段自包含 SVG（不含 <script>、不含外链）。"""
    colors = _PALETTE.get(theme, _PALETTE["light"])
    placed, width, bottom = layout(root)
    # 同一次布局里同时要「父→子」连线，所以先按对象建索引
    box = {id(node): (x, y, w) for node, x, y, w, _ in placed}

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width + PAD * 2}" '
        f'height="{bottom + PAD * 2}" viewBox="0 0 {width + PAD * 2} {bottom + PAD * 2}" '
        'font-family="' + _FONT + '">'
    )
    parts.append(f'<g transform="translate({PAD},{PAD})">')

    # 先画线再画框：线头被框盖住，衔接处不会露出毛刺
    pull = LEVEL_GAP / 2
    for node, x, y, w, depth in placed:
        for child in node.children:
            cx, cy, _ = box[id(child)]
            parts.append(
                f'<path d="M {x + w} {y} C {x + w + pull:.0f} {y}, {cx - pull:.0f} {cy}, '
                f'{cx} {cy}" fill="none" stroke="{colors[min(depth + 1, 4)][1]}" '
                'stroke-width="1.2"/>'
            )

    for node, x, y, w, depth in placed:
        fill, stroke, text_color = colors[min(depth, 4)]
        top = y - NODE_H / 2
        parts.append(
            f'<g><rect x="{x}" y="{top:.0f}" width="{w}" height="{NODE_H}" rx="8" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>'
            f'<text x="{x + 12}" y="{y}" fill="{text_color}" font-size="13" '
            f'dominant-baseline="central" xml:space="preserve">{_text(node.text)}</text></g>'
        )

    parts.append("</g></svg>")
    return "".join(parts)


def render_item_svg(
    title: str, note: str | None, key_points: list[str] | None = None, theme: str = "light"
) -> str:
    """条目 → SVG 的唯一入口：路由与 HTML 渲染都走它，保证两处图形完全一致。"""
    return render_svg(parse_tree(note, title, key_points or []), theme)
