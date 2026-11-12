"""行框 → 阅读顺序（T9.6 的验收核心）：**纯函数，不碰数据库、不碰文件**。

**为什么必须自己排序**：识别引擎只给每行文字的外接框，**不给阅读顺序**。
双栏页按 y 排出来是「左1 → 右1 → 左2 → 右2」交错的（2026-11-12 实测，必现），
直接喂给 chunker 会得到一堆语义断裂的句子 —— 检索和整理都会被带坏。

判据来自实测的版式特征（四组 40 页样本 + exam/scan 共 90 余页跑出来的）：

- **双栏**：两侧各 ≥2 行（**只探到页码那一行不算**，那种页其实右栏是空的）、
  且**左列右边界 ≤ 右列左边界 + 容差**（真的不重叠）。容差取 `max(8px, 页宽 2%)`：
  实测同一栏内个别行框会越过栏边界十几像素（python 第 7 页 gap=-19），按最大值判会误退化成单栏。
- 边界用 **P90 / P10** 而不是 max/min：一张 60 行的页里有一两个断线框，不该决定整页的版式。
- 横跨整页的行（通栏标题 / 通栏表格）不参与边界计算 —— 它天然与另一栏重叠，
  参与进去会把整页误判成单栏，然后左右交错（比不判列更糟）。
- **单栏**：按 y 中心聚成行（相邻行差 < 0.6 × 中位行高视为同一行），行内按 x0 排。

阈值都是「实测版式 + 样本回归」定的，改之前先跑 `samples/*/twocol.pdf` 四组。
"""
from __future__ import annotations

import re
from statistics import median

# 中西文混排：CJK 与全角标点两侧不该补空格（补了会变成「线性 表」这种分词噪音）
_CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]")

COLUMN_MIN_LINES = 2     # 每侧至少几行才算"有过一栏"（只有页码的那种页不算双栏）
COLUMN_TOL_PX = 8.0      # 允许的重叠量下限（px）
COLUMN_TOL_RATIO = 0.02  # 按页宽的相对容差：大页面行框噪声也大
SPAN_RATIO = 0.7         # 宽度超过页宽这个比例的行算"横跨整页"
ROW_TOLERANCE = 0.6      # 同一行的 y 中心容差（倍中位行高）


def _percentile(values: list[float], q: float) -> float:
    """线性插值分位数（不引 numpy：这里只是给版式判据用）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _edges(line: dict) -> tuple[float, float, float, float]:
    """行框的四条边。box 是 4 个点（左上/右上/右下/左下），个别引擎会给 5 个点闭合框。"""
    box = line.get("box") or []
    xs = [float(p[0]) for p in box if len(p) >= 2]
    ys = [float(p[1]) for p in box if len(p) >= 2]
    if not xs or not ys:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _center_y(line: dict) -> float:
    x0, y0, x1, y1 = _edges(line)
    return (y0 + y1) / 2


def _center_x(line: dict) -> float:
    x0, _, x1, _ = _edges(line)
    return (x0 + x1) / 2


def _height(line: dict) -> float:
    _, y0, _, y1 = _edges(line)
    return max(0.0, y1 - y0)


def _join_fragments(parts: list[str]) -> str:
    """同一视觉行里的几段文字拼起来：两侧有汉字就不补空格。"""
    out = ""
    for part in parts:
        if not out:
            out = part
            continue
        if _CJK.match(out[-1]) or _CJK.match(part[0]):
            out += part
        else:
            out += " " + part
    return out


def _cluster_rows(lines: list[dict]) -> list[str]:
    """单栏（或某一栏内部）：按 y 聚行，行内按 x 拼。"""
    if not lines:
        return []
    tol = max(1.0, ROW_TOLERANCE * median([_height(ln) for ln in lines] or [1.0]))
    rows: list[dict] = []
    for line in sorted(lines, key=_center_y):
        y = _center_y(line)
        if rows and abs(y - rows[-1]["y"]) <= tol:
            row = rows[-1]
            row["items"].append(line)
            row["y"] = (row["y"] * (len(row["items"]) - 1) + y) / len(row["items"])
        else:
            rows.append({"y": y, "items": [line]})
    out: list[str] = []
    for row in rows:
        parts = [str(ln.get("text") or "").strip()
                 for ln in sorted(row["items"], key=lambda l: _edges(l)[0])]
        merged = _join_fragments([p for p in parts if p])
        if merged:
            out.append(merged)
    return out


def _is_two_column(left: list[dict], right: list[dict], page_width: float) -> bool:
    if len(left) < COLUMN_MIN_LINES or len(right) < COLUMN_MIN_LINES:
        return False
    span_limit = SPAN_RATIO * page_width
    left_edge = [ln for ln in left if _edges(ln)[2] - _edges(ln)[0] <= span_limit]
    right_edge = [ln for ln in right if _edges(ln)[2] - _edges(ln)[0] <= span_limit]
    if len(left_edge) < COLUMN_MIN_LINES or len(right_edge) < COLUMN_MIN_LINES:
        return False
    tol = max(COLUMN_TOL_PX, COLUMN_TOL_RATIO * page_width)
    left_right_edge = _percentile([_edges(ln)[2] for ln in left_edge], 0.9)
    right_left_edge = _percentile([_edges(ln)[0] for ln in right_edge], 0.1)
    return left_right_edge <= right_left_edge + tol


def order_lines(lines: list[dict], page_width: float) -> list[str]:
    """把行框排成从上到下、**先整栏左再整栏右**的文本行。

    `page_width` 是页图宽度（px），用来决定中线；给 0 时退化成单栏处理
    （宁可顺序一般，也不要凭空猜分栏）。
    """
    items = [ln for ln in lines if str(ln.get("text") or "").strip()]
    if not items:
        return []

    if page_width and page_width > 0:
        mid = page_width / 2
        left = [ln for ln in items if _center_x(ln) < mid]
        right = [ln for ln in items if _center_x(ln) >= mid]
        if _is_two_column(left, right, page_width):
            return _cluster_rows(left) + _cluster_rows(right)

    return _cluster_rows(items)


def avg_conf(lines: list[dict]) -> float:
    """页级平均置信度（一位小数）。没有行就是 0.0 —— 前端据此标「这页没认出文字」。"""
    scores = [float(ln.get("conf") or 0.0) for ln in lines if ln.get("text")]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def low_conf_lines(lines: list[dict], threshold: float = 0.85) -> int:
    """置信度低于阈值的行数（T9.10 页头提示「这页可能有错」用）。"""
    return sum(1 for ln in lines if ln.get("text") and float(ln.get("conf") or 0) < threshold)
