"""全库补向量（T3.3）。首次启用向量检索、或换了 embedding 模型之后跑一次。

    uv run python scripts/backfill_embed.py             # 补齐所有缺向量的 chunk
    uv run python scripts/backfill_embed.py --stats     # 只看进度，不跑模型

补向量是幂等的：只处理 chunk_vec 里没有的 chunk，重复跑不会重复写。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, setup_logging  # noqa: E402
from app.db.migrate import init_db  # noqa: E402
from app.services import embedder  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", action="store_true", help="只打印向量覆盖率")
    args = parser.parse_args()

    cfg = get_settings()
    setup_logging(cfg)
    init_db()

    conn = embedder.connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        have = embedder.count_vectors(conn)
    finally:
        conn.close()

    print(f"chunk 总数 {total}，已有向量 {have}，缺 {max(0, total - have)}")
    if args.stats:
        return 0
    if not embedder.vec_available():
        print("sqlite-vec 不可用（或 VECTOR_ENABLED=0）：无法建向量索引，跳过")
        return 1
    if total == have:
        print("已全部补齐，无需处理")
        return 0

    if not embedder.model_ready():
        print(f"模型未下载，首次加载会从 {cfg.models_dir / 'embedding'} 拉取（约 100MB）")
    started = time.monotonic()
    done = 0
    while True:
        result = embedder.run({})
        wrote = result.get("indexed") or 0
        done += wrote
        print(f"  本轮写入 {wrote} 条，累计 {done}")
        if wrote == 0:
            break
    print(f"完成：{done} 条，用时 {time.monotonic() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
