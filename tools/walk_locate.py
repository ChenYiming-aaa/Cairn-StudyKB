#!/usr/bin/env python3
"""真样本走查：引用落页（chunk → 第几页）在**真识别 + 真切块**上成立吗（T11.4 收尾）。

**为什么不能只靠 verify_m11**：`§locate` 的页文字是我摆好的，页码是「我按想象构造的世界」。
真文档的麻烦全在排版里 —— 每页页脚印同一句图注、讲义有「课堂笔记」重述页、
代码里同一行 `txt=open('data.txt',...)` 在两道题里各出现一次。这些都不会出现在夹具里，
而 2026-11-14 的第一版 `locate` 正是被它们打败的：10 页讲义 25 块里 2 块落错页。

**它验三件事**

1. **整段落页**：不带 `q` 时，落的那一页必须是「这段字主要在的那一页」，
   而且要比第二像的那页胜出 3 倍以上（否则就是含糊，用户看到的是半句）。
   ⚠️ 判据不能写成「最早出现的那一页」—— 讲义每页页脚都有同一句图注，
   最早出现那页常常只对上 40 来个字，第一轮走查就是被这个假判据误导的。
2. **跨页块**：一个 chunk 头在一页、尾在另一页时，带 `q`（用户真正在找的那句）要翻到句尾那页。
3. **命中段**：接口回的 `matched` 必须真能在它说那一页的文字里找到（标黄才不会标空）。

用法（需要识别组件，10 页双栏讲义实测约 60 秒）：
    python tools/walk_locate.py                       # 默认 samples/python/twocol.pdf
    python tools/walk_locate.py --sample java/exam.pdf
    python tools/walk_locate.py --keep                # 留着临时数据目录看现场

退出码：0 通过 / 1 有落错页 / 2 环境不满足（缺样本或缺识别组件）。

**借 verify_m11 的启动脚手架**：验真样本也要一个一次性后端 + 临时数据目录，
那套 `DATA_DIR` / 端口 / 上传 / 等识别已经写在那儿了。这里 import 它就是为了不写第二份，
所以本脚本必须在 `backend/scripts/` 能被 import 的位置跑（`sys.path` 已处理）。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "scripts"))

import verify_m11 as V  # noqa: E402  它会把 DATA_DIR 指到临时目录并 import app

from app.db.conn import get_conn  # noqa: E402


def squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def cover(page_flat: str, chunk_flat: str) -> int:
    """这一页从 chunk **开头**起能连续对上多少字（前缀可匹配是单调的，二分即可）。"""
    lo, hi = 0, len(chunk_flat)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if page_flat.find(chunk_flat[:mid]) >= 0:
            lo = mid
        else:
            hi = mid - 1
    return lo


def page_of(needle: str, pages: dict[int, str]) -> int | None:
    """最早出现 `needle` 的那一页（只在「跨页块」里用来判断头尾不在同一页）。"""
    key = squash(needle)
    if len(key) < 12:
        return None
    for no in sorted(pages):
        if key in pages[no]:
            return no
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="真样本走查：引用落页对不对")
    ap.add_argument("--sample", default="python/twocol.pdf", help="samples/ 下的相对路径")
    ap.add_argument("--keep", action="store_true", help="留着临时数据目录")
    args = ap.parse_args()

    src = ROOT / "samples" / args.sample
    if not src.is_file():
        print(f"× 缺样本 {src}（见 samples/README.md 怎么生成）")
        return 2

    started = time.time()
    up = V.post_file(src)
    item = int(up["item_id"])
    print(f"上传 {args.sample} → item={item}，等识别 …")
    got = V.wait_done(item, timeout=1800)
    total = int(got.get("total_pages") or 0)
    print(f"识别 {got.get('status')} · {total} 页 · {time.time() - started:.0f}s")
    if got.get("status") != "done" or total < 3:
        print("× 识别没跑完（或页数太少），走查没有意义；缺识别组件时是这条")
        return 2

    pages: dict[int, str] = {}
    for no in range(1, total + 1):
        body = V.get_json(f"api/knowledge/{item}/pages/{no}")
        pages[no] = squash(body.get("text") or "")
    print("每页字数：" + ", ".join(f"p{no}:{len(t)}" for no, t in pages.items()))
    thin = [no for no, t in pages.items() if len(t) < 50]
    if thin:
        print(f"× 有页几乎没读出字（{thin}），后面的结论不可信")
        return 1

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content FROM chunk WHERE item_id=? AND source='raw' ORDER BY position",
            (item,),
        ).fetchall()
    chunks = [(int(r["id"]), squash(str(r["content"] or ""))) for r in rows]
    print(f"切出 {len(chunks)} 块\n")

    # ① 整段落页：必须落在「这段字主要在的那一页」，且明确胜出
    weak: list[str] = []
    judged = 0
    for cid, key in chunks:
        scores = sorted(((cover(t, key), no) for no, t in pages.items()), reverse=True)
        (best, best_page), (second, second_page) = scores[0], scores[1]
        if best < 40:
            continue          # 这段字在每页都只出现几十字，没有「主体页」可言
        judged += 1
        landed = V.get_json(f"api/knowledge/{item}/locate?chunk_id={cid}").get("page_no")
        if landed != best_page or best < second * 3:
            weak.append(f"块 {cid}：应落第 {best_page} 页（对上 {best} 字），"
                        f"实际第 {landed} 页；第二像的是第 {second_page} 页（{second} 字）")
    print(f"① 整段落页：{judged} 块有明确主体页，落错/胜出不足 3 倍 {len(weak)} 处")
    for line in weak[:10]:
        print("    " + line)

    # ② 跨页块：带 q 要翻到句尾那一页
    cross_bad: list[str] = []
    crossed = 0
    for cid, key in chunks:
        head, tail = page_of(key[:30], pages), page_of(key[-30:], pages)
        if head is None or tail is None or tail == head:
            continue
        crossed += 1
        hint = key[-40:]
        got_json = V.get_json(
            f"api/knowledge/{item}/locate?chunk_id={cid}&q={V.urllib.parse.quote(hint)}")
        if got_json.get("page_no") != tail:
            cross_bad.append(f"块 {cid}：头在第 {head} 页、尾在第 {tail} 页，"
                             f"带 q 却落到第 {got_json.get('page_no')} 页（q={hint[:20]}）")
    print(f"② 跨页块：{crossed} 块，带 q 落错 {len(cross_bad)} 处")
    for line in cross_bad[:10]:
        print("    " + line)

    # ③ 命中段必须真在那页里
    found = 0
    for cid, _ in chunks:
        got_json = V.get_json(f"api/knowledge/{item}/locate?chunk_id={cid}")
        no, matched = got_json.get("page_no"), got_json.get("matched") or ""
        if no and matched and squash(matched)[:12] in pages[no]:
            found += 1
    print(f"③ 命中段能在该页文字里找到：{found}/{len(chunks)}")

    fails = len(weak) + len(cross_bad) + (0 if found == len(chunks) else 1)
    print("\n" + ("真样本走查通过" if not fails else f"真样本走查有 {fails} 处问题"))
    if not args.keep:
        shutil.rmtree(V.TMP, ignore_errors=True)
    else:
        print(f"临时数据目录：{V.TMP}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
