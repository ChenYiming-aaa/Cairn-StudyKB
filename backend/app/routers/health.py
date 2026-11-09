"""健康检查与版本元数据（接口契约 §2：`GET /api/health`、`GET /api/version`）。"""
from __future__ import annotations

import os

from fastapi import APIRouter

from app import __version__

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict:
    # 裁决：以接口契约为准，带 version；M1 §5 DoD 已同步改一致
    return {"status": "ok", "version": __version__}


@router.get("/api/version")
def version() -> dict:
    """更新器的比较基准（T8.5 用）。

    `commit` / `built_at` 由构建时注入环境变量；拿不到就是 `null` ——
    不在这里现算（`git rev-parse` 在打包后没有 .git 目录），否则"版本号"和
    "实际二进制"会各说各话。
    """
    return {
        "version": __version__,
        "commit": (os.environ.get("CAIRN_COMMIT") or "").strip() or None,
        "built_at": (os.environ.get("CAIRN_BUILT_AT") or "").strip() or None,
    }
