"""健康检查（接口契约 §2：GET /api/health）。"""
from __future__ import annotations

from fastapi import APIRouter

from app import __version__

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict:
    # 裁决：以接口契约为准，带 version；M1 §5 DoD 已同步改一致
    return {"status": "ok", "version": __version__}
