"""Cairn 后端入口。

T1.1 / T1.2：CORS、按天滚动日志、启动时打印实际数据目录与端口。
T1.3 / T1.6：启动时建库并清理残留任务。
本次端点范围（用户裁决）：knowledge 5 个 + health + tasks 2 个。
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import force_utf8_stdio, get_settings, setup_logging
from app.db.migrate import init_db
from app.errors import ApiError, api_error_handler
from app.paths import install_root, is_frozen
from app.routers import (
    ask, auth, env, exams, files, health, html, ingest, knowledge, quiz, review, search,
    session, settings, stats, tasks, workspaces,
)
# 下载中心（M8 T8.3）：路由模块名与 services.components 撞，导入时改名
from app.routers import components as components_api
from app.db.repo import sessions as sessions_repo
from app.services import browser, components, ingest_file
from app.services import files as file_store
from app.services.tasks import recover_stale_tasks, shutdown
from app.services.transcriber import clear_tmp

log = logging.getLogger("cairn")


def _close_stale_sessions() -> None:
    """启动清理：把放了太久还 active 的计时收掉。失败不影响启动。"""
    from app.db.conn import get_conn

    conn = get_conn()
    try:
        with conn:
            closed = sessions_repo.abandon_stale(conn)
        if closed:
            log.info("已关闭 %s 个超时计时（>%s 小时）", closed, sessions_repo.STALE_HOURS)
    except Exception as exc:              # noqa: BLE001 - 启动清理不该拖垮服务
        log.warning("清理超时计时失败：%s", exc)
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    cfg = get_settings()
    # 先修编码再打日志：否则下面每一行中文在 shell.log 里都是乱码（见 force_utf8_stdio）
    force_utf8_stdio()
    setup_logging(cfg)
    init_db()
    recover_stale_tasks()
    # T9.6：识别是线程任务，被 kill 时来不及写状态。启动时看到 running 一定是上次没跑完，
    # 不拨回 pending 的话界面永远转圈、重识别还会被判「正在跑」
    ingest_file.reset_stale()
    # M5 §6.2：忘了关的番茄钟不许一直 running（>4 小时按计划时长封顶后标 abandoned）
    _close_stale_sessions()
    # M2 §7：上次转录中断留下的临时音频不许攒着，启动即清
    if (cleared := clear_tmp()):
        log.info("已清理 %s 个残留临时目录", cleared)
    # T9.3：上传到一半崩溃留下的 .part 同样不许攒着（原件目录不碰，只清临时目录）
    if (stale := file_store.clear_tmp()):
        log.info("已清理 %s 个残留的上传临时文件", stale)
    # T1.2：启动时打印实际数据目录与端口（只打印路径，不打印任何 Key）
    print(f"[Cairn] 数据目录 = {cfg.data_dir}")
    print(f"[Cairn] 数据库   = {cfg.db_path}")
    print(f"[Cairn] 监听端口 = {cfg.port}")
    print(f"[Cairn] LLM Key  = {'已配置' if cfg.has_llm_key else '未配置'}")
    log.info("Cairn 启动完成，数据目录=%s，端口=%s", cfg.data_dir, cfg.port)
    try:
        yield
    finally:
        # 先让登录线程收手，再关线程池：否则退出时可能留下一个孤立的浏览器窗口
        browser.shutdown()
        shutdown()
        # M8 D3：组件进程必须跟着死。留着孤儿 exe 会锁住 components/<id>/，
        # 卸载时 Windows 删不掉（v0.1.0 的 app.asar 就是这么被锁过的）
        components.stop_all()


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
app.include_router(settings.router)
app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(files.router)
app.include_router(workspaces.router)
app.include_router(knowledge.router)
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(html.router)
app.include_router(exams.router)
app.include_router(quiz.router)
app.include_router(review.router)
app.include_router(session.router)
app.include_router(stats.router)
app.include_router(tasks.router)
app.include_router(components_api.router)


# ── 前端静态产物：让页面与 /api 同源（Electron 壳用，dev 仍走 5173）──────────
# 为什么要同源：Electron 里若用 file:// 加载 index.html，页面 origin 是 null，
# 而后端 CORS 白名单只有 http://localhost:5173 / 127.0.0.1:5173，API 会被浏览器拦。
# 解法是让后端自己吐页面，而不是放宽 CORS（白名单一行没动）。
#
# 两条硬约束：
# 1) 只挂 /assets 与 /，**绝不用 app.mount("/", StaticFiles(html=True))**——那会把
#    未匹配的 /api 路径也返回 index.html，接口调试直接变成"永远 200 但内容是 HTML"。
# 2) 必须条件挂载：dist 不存在（dev 没 build / 没装前端）就整段跳过，否则后端启动即报错。
WEB_DIR = Path(
    os.environ.get("CAIRN_WEB_DIR")
    or str(
        # 冻结后 `__file__` 指向 `_internal/` 里的假路径，不能再靠 parents[n] 硬算。
        # onedir 布局是 `<安装目录>/resources/backend/cairn-backend.exe`，
        # 页面在 `<安装目录>/resources/web`。Electron 会显式传 CAIRN_WEB_DIR，
        # 这里只是没人传时的合理兜底。
        (install_root().parent / "web")
        if is_frozen()
        else (Path(__file__).resolve().parents[2] / "frontend" / "dist")
    )
)

if (WEB_DIR / "index.html").exists():
    # vite 产物在 assets/ 下；单独判一次目录，避免 dist 是半成品时 StaticFiles 抛错
    if (WEB_DIR / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def _index() -> FileResponse:
        # 前端路由是 hash 模式，深链接不会打到后端，这里只需要给首页
        return FileResponse(WEB_DIR / "index.html")

    # 根目录下的零散静态文件（页签图标、品牌标）。只放行**白名单里的名字**：
    # 用 `GET /{name}` 通配会把未登记的 /api 路径兜成文件响应，
    # 正是上面约束 1 要避免的事（`/api/nope` 必须还是 404 JSON）。
    def _serve_root_file(name: str):
        def _handler() -> FileResponse:
            return FileResponse(WEB_DIR / name)

        return _handler

    # theme-boot.js 是 T6.7 的首屏防白闪脚本（index.html 在挂载前同步引用），
    # 漏掉它 → 桌面版里脚本加载不到，每次启动刷一条 404，防白闪形同虚设
    for _name in ("favicon.ico", "logo.svg", "apple-touch-icon.png", "robots.txt", "theme-boot.js"):
        if (WEB_DIR / _name).is_file():
            app.get(f"/{_name}", include_in_schema=False, name=f"web-{_name}")(
                _serve_root_file(_name)
            )

