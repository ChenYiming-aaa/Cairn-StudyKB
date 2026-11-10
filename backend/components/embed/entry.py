"""向量组件 worker（T8.2：真 bge 推理）。

协议语义里有两条只能由组件实现，主程序不掺和：

1. **查询加前缀、文档不加**（bge 的用法约定，M3 §1 约束 3）——主程序只传
   `kind=query|doc`，前缀在这里加。换模型时只改这个文件。
2. **模型缓存目录由主程序传**（`cache_dir`）。模型不进组件包（数据契约 §10），
   和主程序共用 `<数据目录>/models/embedding`，这样"没装组件时装过的模型"装上组件后
   立刻能用，反过来卸载组件也不删模型。

**失败必须响**：模型加载不了就回错误码，绝不退化成"假向量"。假向量写进 `chunk_vec`
会污染整个索引 —— 症状是问答永远答偏，而且查不出原因。唯一允许假向量的情况是
`CAIRN_EMBED_STUB=1`（只为在没有模型/没有网络的机器上验协议形状）。
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _protocol import OpError, main  # noqa: E402

VERSION = "0.2.0"
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
STUB_DIM = 512
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
BATCH_SIZE = 32

_model = None
_model_key: tuple[str, str] | None = None
_lock = threading.Lock()


# ── 模型位置 ────────────────────────────────────────────
def _default_cache() -> Path:
    """主程序没传 cache_dir 时的兜底（自检/手工起进程时走这里）。

    顺序与 `app/config.py` 一致：`CAIRN_MODELS_DIR` → `%APPDATA%/Cairn/models`。
    组件里**不能** import `app.config`（那是主程序的东西），所以只能自己推。
    """
    configured = os.environ.get("CAIRN_MODELS_DIR", "").strip()
    if configured:
        base = Path(configured)
    else:
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / "Cairn" / "models"
    return base / "embedding"


def _stub_vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (seed * ((STUB_DIM // len(seed)) + 1))[:STUB_DIM]
    vals = [(b - 127.5) / 127.5 for b in raw]
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [round(v / norm, 6) for v in vals]


# ── 载入 ────────────────────────────────────────────────
def _load(model_name: str, cache_dir: Path):
    """懒加载常驻。首次会从 HF_ENDPOINT（镜像，环境变量由主程序透传）下载约 90 MB。"""
    global _model, _model_key
    with _lock:
        key = (model_name, str(cache_dir))
        if _model is not None and _model_key == key:
            return _model
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(model_name, cache_folder=str(cache_dir),
                                         device="cpu")
        except Exception as exc:  # noqa: BLE001 - 缺 torch / 缺模型 / DLL 加载失败都在这里
            _model, _model_key = None, None
            raise OpError(
                "EMBED_MODEL_FAIL",
                f"向量模型加载失败（{type(exc).__name__}: {str(exc)[:160]}）",
            ) from exc
        _model_key = key
        return _model


def _encode_stub(texts: list[str], kind: str) -> dict:
    prepared = [QUERY_PREFIX + t for t in texts] if kind == "query" else texts
    return {"vectors": [_stub_vector(t) for t in prepared], "dim": STUB_DIM, "model": "stub"}


# ── 主入口 ──────────────────────────────────────────────
def encode(req: dict, progress) -> dict:
    texts = [t for t in (req.get("texts") or []) if isinstance(t, str) and t.strip()]
    kind = req.get("kind") or "doc"
    if kind not in ("doc", "query"):
        raise OpError("COMPONENT_BAD_OP", f"kind 只能是 doc/query，收到 {kind!r}")
    if not texts:
        return {"vectors": [], "dim": 0, "model": ""}

    if os.environ.get("CAIRN_EMBED_STUB") == "1":
        progress(50)
        return _encode_stub(texts, kind)

    model_name = str(req.get("model") or DEFAULT_MODEL)
    cache_dir = Path(req.get("cache_dir") or _default_cache())

    progress(10)
    model = _load(model_name, cache_dir)
    progress(30)

    prepared = [QUERY_PREFIX + t for t in texts] if kind == "query" else texts
    try:
        matrix = model.encode(prepared, batch_size=BATCH_SIZE,
                              normalize_embeddings=True, show_progress_bar=False)
    except Exception as exc:  # noqa: BLE001
        raise OpError("EMBED_FAILED", f"编码失败（{type(exc).__name__}: {str(exc)[:160]}）") from exc

    vectors = [[round(float(x), 6) for x in row] for row in matrix]
    progress(100)
    return {"vectors": vectors, "dim": len(vectors[0]) if vectors else 0, "model": model_name}


# ── 自检 ────────────────────────────────────────────────
def _expect(reply: dict) -> tuple[bool, str]:
    vectors = reply.get("vectors") or []
    if not reply.get("ok") or len(vectors) != 1 or not vectors[0]:
        return False, f"回包形状不对：{str(reply)[:160]}"
    norm = math.sqrt(sum(v * v for v in vectors[0]))
    dim = len(vectors[0])
    # 维度不写死 512：换模型时这条自检不该假失败，但"向量长度与自报 dim 一致"要在
    if reply.get("dim") != dim:
        return False, f"dim 与实际长度不符：{reply.get('dim')} vs {dim}"
    if abs(norm - 1.0) > 1e-2:
        return False, f"向量没有归一化（|v|={norm:.4f}）"
    return True, f"encode ok：1 × {dim} 维，|v|={norm:.4f}，model={reply.get('model')}"


if __name__ == "__main__":
    sys.exit(main(
        "embed", VERSION, {"encode": encode},
        sample={"op": "encode", "kind": "doc", "texts": ["自检文本"]},
        expect=_expect,
    ))
