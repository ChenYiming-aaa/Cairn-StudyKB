"""Cairn 后端入口。

T1.1 / T1.2：CORS、按天滚动日志、启动时打印实际数据目录与端口。
T1.3 / T1.6：启动时建库并清理残留任务。
本次端点范围（用户裁决）：knowledge 5 个 + health + tasks 2 个。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings, setup_logging
from app.db.migrate import init_db
from app.errors import ApiError, api_error_handler
from app.routers import env, health, ingest, knowledge, tasks
from app.services.tasks import recover_stale_tasks, shutdown
from app.services.transcriber import clear_tmp

log = logging.getLogger("cairn")


@asynccontextmanager
async def lifespan(_: FastAPI):
    cfg = get_settings()
    setup_logging(cfg)
    init_db()
    recover_stale_tasks()
    # M2 §7：上次转录中断留下的临时音频不许攒着，启动即清
    if (cleared := clear_tmp()):
        log.info("已清理 %s 个残留临时目录", cleared)
    # T1.2：启动时打印实际数据目录与端口（只打印路径，不打印任何 Key）
    print(f"[Cairn] 数据目录 = {cfg.data_dir}")
    print(f"[Cairn] 数据库   = {cfg.db_path}")
    print(f"[Cairn] 监听端口 = {cfg.port}")
    print(f"[Cairn] LLM Key  = {'已配置' if cfg.has_llm_key else '未配置'}")
    log.info("Cairn 启动完成，数据目录=%s，端口=%s", cfg.data_dir, cfg.port)
    try:
        yield
    finally:
        shutdown()


app = FastAPI(title="Cairn", version="0.1.0", lifespan=lifespan)

# M1 §6.8：开发期精确白名单，不写 allow_origins=["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ApiError, api_error_handler)
app.include_router(health.router)
app.include_router(env.router)
app.include_router(ingest.router)
app.include_router(knowledge.router)
app.include_router(tasks.router)
