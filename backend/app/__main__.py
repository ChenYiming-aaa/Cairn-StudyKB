"""`python -m app` 入口。

只做一件事：把 config 解析出的 host/port 交给 uvicorn。
存在理由：Electron 主进程要 spawn 后端并传 --port（ADR-013 端口随机探测 +
ADR-016 HTTP 轮询握手），`uvicorn app.main:app` 那条 CLI 不适合被当子进程调，
而 `python -m app` 是将来 PyInstaller 入口的同一个形状（ADR-014 的 --onedir）。
命令行优先级仍由 config._cli_overrides 负责，这里不重复解析。
"""
from __future__ import annotations

import uvicorn

from app.config import get_settings
from app.main import app


def main() -> None:
    cfg = get_settings()
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level=cfg.log_level.lower())


if __name__ == "__main__":
    main()
