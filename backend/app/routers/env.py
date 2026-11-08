"""环境自检端点（T2.5 / T5.7）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/api/env/check` | 只读自检：ffmpeg / whisper / embedding / sqlite-vec / Key |
| POST | `/api/env/key`   | 首次引导：把 llm 配置写进 `.env` 并热加载 |

自检逻辑全在 `services/env_probe.py`，写 `.env` 全在 `services/env_store.py`。
这里只做参数校验与返回形状 —— 两个能力都被引导页与 `scripts/env_check.py` 复用，
逻辑一旦分叉，用户在页面上看到的和脚本里看到的就会不一致。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.env_probe import check_all
from app.services.env_store import update_llm

router = APIRouter(prefix="/api/env", tags=["env"])


class KeyBody(BaseModel):
    """三项都可选；空串 = 不改这一项（不是"清空"）。"""

    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""


@router.get("/check")
def env_check() -> dict:
    return check_all()


@router.post("/key")
def save_key(body: KeyBody) -> dict:
    """保存 llm 配置到 `.env` 并热加载，返回保存后的完整自检结果。

    返回里只有 `env_file` 这一个路径，**不含任何 Key 内容**（总纲 §2 红线 7）；
    前端因此不需要二次请求就能把状态刷成绿的。
    """
    path = update_llm(body.model_dump())
    return {"saved": True, "env_file": str(path), "check": check_all()}
