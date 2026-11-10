"""向量组件 worker（T8.0 **空实现**：只证明协议，不做真推理）。

T8.2 会把这里换成 `sentence_transformers` + bge 模型；在那之前它给的是**确定性假向量**
（同样文本 → 同样向量，单位长度，512 维），足以断言"请求出去、响应回来、形状对、可复现"。

协议语义里有一条只能由组件实现：**查询加前缀、文档不加**（bge 的用法约定，M3 §1 约束 3）。
主程序只传 `kind=query|doc`，前缀在组件里加 —— 换模型时改一处，调用方不用动。
"""
from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _protocol import OpError, main  # noqa: E402

VERSION = "0.2.0"
DIM = 512
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def _vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (seed * ((DIM // len(seed)) + 1))[:DIM]
    vals = [(b - 127.5) / 127.5 for b in raw]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [round(v / norm, 6) for v in vals]


def encode(req: dict, progress) -> dict:
    texts = [t for t in (req.get("texts") or []) if isinstance(t, str) and t.strip()]
    if not texts:
        return {"vectors": [], "dim": DIM, "model": "stub"}
    kind = req.get("kind") or "doc"
    if kind not in ("doc", "query"):
        raise OpError("COMPONENT_BAD_OP", f"kind 只能是 doc/query，收到 {kind!r}")
    prepared = [QUERY_PREFIX + t for t in texts] if kind == "query" else texts
    progress(50)
    return {"vectors": [_vector(t) for t in prepared], "dim": DIM, "model": "stub"}


def _expect(reply: dict) -> tuple[bool, str]:
    vectors = reply.get("vectors") or []
    if not reply.get("ok") or len(vectors) != 1 or len(vectors[0]) != DIM:
        return False, f"回包形状不对：{str(reply)[:120]}"
    norm = math.sqrt(sum(v * v for v in vectors[0]))
    if abs(norm - 1.0) > 1e-3:
        return False, f"向量没有归一化（|v|={norm:.4f}）"
    return True, f"encode ok：1 × {DIM} 维，|v|={norm:.4f}"


if __name__ == "__main__":
    sys.exit(main(
        "embed", VERSION, {"encode": encode},
        sample={"op": "encode", "kind": "doc", "texts": ["自检文本"]},
        expect=_expect,
    ))
