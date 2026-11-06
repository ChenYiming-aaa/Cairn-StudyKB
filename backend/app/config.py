"""配置与日志。优先级：命令行 > .env（含系统环境变量） > 默认。

约束：LLM API Key 只从 .env 读（M1 §1 约束 5），不提供命令行覆盖，
也不出现在日志、异常栈、repr 里（总纲 §2 红线 7）。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"

_LOG_MARKER = "cairn"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    log_file: Path
    host: str = "127.0.0.1"
    port: int = 8756
    log_level: str = "INFO"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = field(default="", repr=False)
    llm_model: str = "deepseek-flash"
    llm_effort: str = "low"
    llm_timeout: int = 120
    # 本机 ffmpeg 在 Anaconda 下，从 IDE/Electron 启动时 PATH 未必包含它（M2 §7 排障表），
    # 因此显式给一个目录，M2 的转录一律优先用它拼出的绝对路径。
    ffmpeg_dir: str = ""

    @property
    def has_llm_key(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def ffmpeg_exe(self) -> Path | None:
        return self._tool("ffmpeg")

    @property
    def ffprobe_exe(self) -> Path | None:
        return self._tool("ffprobe")

    def _tool(self, name: str) -> Path | None:
        """按 FFMPEG_DIR 拼绝对路径；没配或文件不存在返回 None，调用方回落 PATH。"""
        if not self.ffmpeg_dir.strip():
            return None
        exe = Path(self.ffmpeg_dir.strip()) / (f"{name}.exe" if os.name == "nt" else name)
        return exe if exe.exists() else None

    @property
    def chat_completions_url(self) -> str:
        # M1 §6.11：DeepSeek 的 base_url 不带 /v1，拼接前 rstrip('/')
        return self.llm_base_url.rstrip("/") + "/chat/completions"


def _cli_overrides(argv: list[str] | None = None) -> dict[str, str]:
    """只取本项目关心的参数；uvicorn 的其余参数交给 parse_known_args 忽略。"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--data-dir")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--log-level")
    parser.add_argument("--llm-base-url")
    parser.add_argument("--llm-model")
    parser.add_argument("--llm-effort")
    parser.add_argument("--ffmpeg-dir")
    known, _ = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    return {k: str(v) for k, v in vars(known).items() if v is not None}


_CLI_TO_ENV = {
    "data_dir": "DATA_DIR",
    "host": "HOST",
    "port": "PORT",
    "log_level": "LOG_LEVEL",
    "llm_base_url": "LLM_BASE_URL",
    "llm_model": "LLM_MODEL",
    "llm_effort": "LLM_EFFORT",
    "ffmpeg_dir": "FFMPEG_DIR",
}


def load_settings(argv: list[str] | None = None) -> Settings:
    load_dotenv(ENV_FILE, override=False)
    cli = _cli_overrides(argv)
    env = dict(os.environ)

    def pick(env_key: str, default: str) -> str:
        for cli_key, mapped in _CLI_TO_ENV.items():
            if mapped == env_key and cli_key in cli:
                return cli[cli_key]
        return env.get(env_key, default)

    root_data = ROOT / "data"
    data_dir = Path(pick("DATA_DIR", str(root_data))).expanduser()
    if not data_dir.is_absolute():
        data_dir = (ROOT / data_dir).resolve()

    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "data.db",
        log_file=data_dir / "logs" / "app.log",
        host=pick("HOST", "127.0.0.1"),
        port=int(pick("PORT", "8756")),
        log_level=pick("LOG_LEVEL", "INFO").upper(),
        llm_base_url=pick("LLM_BASE_URL", "https://api.deepseek.com"),
        # Key 只允许来自 .env / 系统环境变量，刻意不接命令行
        llm_api_key=env.get("LLM_API_KEY", ""),
        llm_model=pick("LLM_MODEL", "deepseek-flash"),
        llm_effort=pick("LLM_EFFORT", "low"),
        llm_timeout=int(pick("LLM_TIMEOUT", "120")),
        ffmpeg_dir=pick("FFMPEG_DIR", ""),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def setup_logging(settings: Settings | None = None) -> None:
    """按天滚动到 data/logs/app.log，同时输出到控制台。幂等。"""
    cfg = settings or get_settings()
    root = logging.getLogger()
    if any(getattr(h, "_cairn_marker", False) for h in root.handlers):
        return

    cfg.log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    level = getattr(logging, cfg.log_level, logging.INFO)

    file_handler = TimedRotatingFileHandler(
        cfg.log_file, when="midnight", backupCount=14, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler._cairn_marker = True  # type: ignore[attr-defined]

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console._cairn_marker = True  # type: ignore[attr-defined]

    root.addHandler(file_handler)
    root.addHandler(console)
    root.setLevel(level)
