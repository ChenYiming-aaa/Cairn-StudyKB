"""健康检查与版本元数据（接口契约 §2：`GET /api/health`、`GET /api/version`）。"""
from __future__ import annotations

from fastapi import APIRouter

from app import version as version_meta

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict:
    # 裁决：以接口契约为准，带 version；M1 §5 DoD 已同步改一致
    return {"status": "ok", "version": version_meta.VERSION}


@router.get("/api/version")
def version() -> dict:
    """更新器的比较基准（T8.5 用）。

    `commit` / `built_at` 由构建时写进 `app/_build_info.py` 再随包带走；源码直跑没有
    这个文件，就如实回 `null` —— 不在这里现算（打包后没有 `.git` 目录），
    否则"版本号"和"实际二进制"会各说各话。见 `app/version.py` 顶部。
    """
    return version_meta.info()
