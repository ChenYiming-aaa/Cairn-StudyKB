"""检索端点（T3.1 / T3.4）：`GET /api/search`。

形状见接口契约 §3。除了契约里的字段，额外给 `content`：
前端「原文命中」要拿它去原文里定位段落（点来源卡片跳转用），
只给 snippet 的话跳不准。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import retriever

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search")
def search(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    # 空查询不报错：前端清空输入框时会打一发空请求，422 会在界面上闪红
    if not q.strip():
        return {"items": [], "total": 0, "fallback": "none", "match_type": "none"}

    result = retriever.hybrid(q, top=limit)
    items = [
        {
            "chunk_id": item["chunk_id"],
            "item_id": item["item_id"],
            "item_title": item["item_title"],
            "snippet": item["snippet"],
            "content": item["content"],
            "source": item["source"],
            "match_type": item["match_type"],
        }
        for item in result["items"]
    ]
    return {
        "items": items,
        "total": len(items),
        "fallback": result["fallback"],
        "match_type": result["match_type"],
    }
