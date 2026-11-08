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

from app.paths import install_root, is_frozen


def _appdata_dir() -> Path:
    """`%APPDATA%/Cairn` —— 打包后的默认数据目录。

    M5 §1 约束 4：数据目录必须是这里，**不是安装目录**（否则卸载即丢数据，
    装在 `Program Files` 下还写不进去）。Electron 会显式传 `--data-dir`，
    这个函数只是"万一没传"时的兜底，兜底也绝不能落回安装目录。
    """
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "Cairn"


if is_frozen():
    # 冻结后 `__file__` 是 `<_MEIPASS>/app/config.py` 这种假路径，
    # 原来的 parents[2] 会指到 `_internal/` 的上一层，只读资源全部读不到（M5 §6.4）。
    ROOT = install_root()
    DATA_ROOT = _appdata_dir()
    # 安装目录只读，`.env` 必须落在数据目录（T5.7 的首次引导会往这里写 Key）
    ENV_FILE = DATA_ROOT / ".env"
else:
    ROOT = Path(__file__).resolve().parents[2]
    DATA_ROOT = ROOT / "data"
    # 源码下 `.env` 在项目根，与 M1 起的口径一致，不能挪进 data/
    ENV_FILE = ROOT / ".env"

_LOG_MARKER = "cairn"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    log_file: Path
    # `.env` 的实际位置：显式指定了数据目录时跟着它走，否则用布局默认值
    # （源码 = 项目根，安装包 = %APPDATA%/Cairn）。T5.7 的引导页写的就是它。
    env_file: Path
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
    # 需要登录才能拿字幕的站点（B 站、会员视频）：给 Netscape 格式 cookies.txt 的路径。
    # 留空则该站点按未登录处理，自动退回语音识别。
    # 留空时登录助手会写到 data/cookies.txt，这个字段就是"改写到别处"的开关。
    ytdlp_cookies: str = ""
    # 浏览器渲染（2026-11-06）：知乎这类站点对 httpx 一律返回 403 空壳，
    # 只有真实浏览器拿得到正文。channel 复用本机已装的 Edge/Chrome，避免再下 Chromium；
    # 置空则用 playwright 自带的那份（需先 playwright install chromium）。
    browser_channel: str = "msedge"
    browser_headless: bool = True
    # M3：向量检索总开关。T3.5 DoD 要求「关掉向量问答仍正常返回」，
    # 置 0 后检索只走 FTS/LIKE，前端提示"向量不可用，已降级"。
    vector_enabled: bool = True
    # bge-small-zh-v1.5 缓存在 data/models/embedding（与 env_probe.check_embedding 同一目录，
    # 否则设置页会永远显示"未下载"）
    embed_model: str = "BAAI/bge-small-zh-v1.5"
    # 全文一路零命中时，向量结果的 L2 距离必须 ≤ 此值才算命中（否则判「库里没有」，
    # 直接 no_result 不调模型 —— 契约 §api/ask 要求检索为空不得调 LLM）。
    # 1.05 来自实测分布：库内语义查询 0.958 能过，库外问题 1.10–1.17 被挡。
    # 只作全文零命中时的门槛：全文有命中就不再卡向量（「番茄钟」这类库内问题距离 1.169）。
    vector_min_distance: float = 1.05

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

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
        """按 FFMPEG_DIR 拼绝对路径；没配或文件不存在返回 None，调用方回落 PATH。

        冻结后多一条兜底：安装包会把 ffmpeg 放在 `resources/ffmpeg/`（总纲 §9：
        不能依赖系统 PATH，用户的机器上大概率没有）。没配 FFMPEG_DIR 时先看那里，
        再回落 PATH —— 用户自己在 `.env` 里配的仍然优先。
        """
        exe_name = f"{name}.exe" if os.name == "nt" else name
        if self.ffmpeg_dir.strip():
            exe = Path(self.ffmpeg_dir.strip()) / exe_name
            return exe if exe.exists() else None
        if is_frozen():
            bundled = install_root().parent / "ffmpeg" / exe_name
            return bundled if bundled.exists() else None
        return None

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


def _truthy(raw: str) -> bool:
    """环境变量里的布尔：只有明确的假值才算假，其余（含默认的 "1"）为真。"""
    return (raw or "").strip().lower() not in ("", "0", "false", "no", "off")


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
    cli = _cli_overrides(argv)

    # ── 第一步：先定数据目录 ────────────────────────────────
    # 只依赖命令行与系统环境，**不依赖 `.env`** —— 因为 `.env` 的位置接下来要由它决定。
    # 源码下 DATA_ROOT = 项目根/data，冻结后 = %APPDATA%/Cairn。
    explicit_data = "data_dir" in cli or bool(os.environ.get("DATA_DIR", "").strip())
    raw_data = cli.get("data_dir") or os.environ.get("DATA_DIR") or str(DATA_ROOT)
    data_dir = Path(raw_data).expanduser()
    if not data_dir.is_absolute():
        # 相对路径按 DATA_ROOT 的父目录解析：源码下就是项目根（与原行为一致），
        # 冻结后就是 %APPDATA%（不会落到安装目录）
        data_dir = (DATA_ROOT.parent / data_dir).resolve()

    # ── 第二步：`.env` 跟着数据目录走 ───────────────────────
    # 显式传了 --data-dir/DATA_DIR（Electron 打包后就是这么起的，测试也这么起）时，
    # `.env` 落在那个目录里；没传时用布局默认值（源码 = 项目根）。
    # 这条规则保证"另一个数据目录"不会把 Key 写进默认那一份 `.env`。
    env_file = (data_dir / ".env") if explicit_data else ENV_FILE

    load_dotenv(env_file, override=False)
    if env_file != ENV_FILE:
        # 兜底：显式换了数据目录时，再把布局默认的 `.env`（源码下 = 项目根）补进来。
        # `override=False` 只填空缺，绝不会盖掉数据目录里已有的值；
        # 冻结版 ROOT 是安装目录、没有 `.env`，这一步自然不生效。
        # 没有它，「换个临时数据目录跑验收」就拿不到开发用的 Key / FFMPEG_DIR。
        load_dotenv(ENV_FILE, override=False)
    env = dict(os.environ)

    def pick(env_key: str, default: str) -> str:
        for cli_key, mapped in _CLI_TO_ENV.items():
            if mapped == env_key and cli_key in cli:
                return cli[cli_key]
        return env.get(env_key, default)

    return Settings(
        data_dir=data_dir,
        db_path=data_dir / "data.db",
        log_file=data_dir / "logs" / "app.log",
        env_file=env_file,
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
        ytdlp_cookies=pick("YTDLP_COOKIES", ""),
        browser_channel=pick("BROWSER_CHANNEL", "msedge"),
        browser_headless=_truthy(env.get("BROWSER_HEADLESS", "1")),
        vector_enabled=_truthy(env.get("VECTOR_ENABLED", "1")),
        embed_model=pick("EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
        vector_min_distance=float(pick("VECTOR_MIN_DISTANCE", "1.05")),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reload_settings() -> Settings:
    """丢掉缓存重新读一遍（T5.7：引导页写完 `.env` 后要立刻生效，不能要求重启）。

    只影响读配置的地方；已经建好的数据库连接、已经起的线程不受影响 ——
    这个端点只改 llm 的 Key/地址/模型，本来就不需要重连任何东西。
    """
    global _settings
    _settings = None
    return get_settings()


def force_utf8_stdio() -> None:
    """把 stdout/stderr 强制成 UTF-8（有 stream 时；幂等）。

    为什么必须显式做：Electron 用管道接住后端输出、再按 **UTF-8** 写进 `shell.log`，
    而 Python 在"输出到管道"时默认跟随系统 ANSI 代码页（中文机器 = cp936），
    于是 shell.log 里每一行中文都是乱码 —— 而它正是用户报障时唯一能提供的东西。
    `PYTHONIOENCODING` / `PYTHONUTF8` 在冻结的 windowed exe 上实测不生效（2026-11-08），
    只能自己 reconfigure。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 已经关了/不是 TextIOWrapper：不是致命问题，别在启动路径上抛
            pass


def setup_logging(settings: Settings | None = None) -> None:
    """按天滚动到 data/logs/app.log；有控制台时才同时输出到控制台。幂等。"""
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

    console = None
    # windowed exe 在**没有**父进程接管 stdout 时 `sys.stdout` 是 None，
    # StreamHandler(None) 会在每次 emit 时抛 "Logging error —— 没有 stream"。
    # 有 stdout（源码运行、或 Electron 用管道接管时）就照常双写，方便现场排障。
    if sys.stdout is not None:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        console._cairn_marker = True  # type: ignore[attr-defined]

    root.addHandler(file_handler)
    if console is not None:
        root.addHandler(console)
    root.setLevel(level)
