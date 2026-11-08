"""T2.5 环境自检脚本：与 `GET /api/env/check` 共用 `services/env_probe.py`。

用法：
    uv run python scripts/env_check.py            # 人读表格
    uv run python scripts/env_check.py --json     # 机读（verify_m2.py 用）
    uv run python scripts/env_check.py --strict   # 有任何一项不通就 exit 1
只读：不起服务、不建库、不加载模型。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.env_probe import check_all  # noqa: E402

LABELS = {
    "ffmpeg": "ffmpeg / ffprobe",
    "whisper": "whisper 模型",
    "embedding": "embedding 模型",
    "sqlite_vec": "sqlite-vec",
    "llm": "LLM Key",
}
# 这两项不通就算阻塞（网页采集不受影响，但视频采集跑不了）
BLOCKING = ("ffmpeg", "llm")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cairn 环境自检（只读）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--strict", action="store_true", help="阻塞项不通时 exit 1")
    args = parser.parse_args()

    result = check_all()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("  Cairn · 环境自检")
        print("=" * 60)
        for key, item in result.items():
            if not isinstance(item, dict):
                # `env_file` 这类附加信息不是检查项，表格里单独打印
                continue
            mark = "OK  " if item.get("ok") else "FAIL"
            print(f"  [{mark}] {LABELS.get(key, key):<16} {item.get('detail', '')}")
            if not item.get("ok"):
                if item.get("code"):
                    print(f"          code : {item['code']}")
                if item.get("hint"):
                    print(f"          hint : {item['hint']}")
        if result.get("env_file"):
            print(f"  .env 位置：{result['env_file']}")
        print()

    if args.strict and any(not result[k].get("ok") for k in BLOCKING):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
