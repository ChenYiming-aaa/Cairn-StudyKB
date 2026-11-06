"""环境自检端点（T2.5）：`GET /api/env/check`。逻辑全在 `services/env_probe.py`。"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.env_probe import check_all

router = APIRouter(prefix="/api/env", tags=["env"])


@router.get("/check")
def env_check() -> dict:
    return check_all()
