"""写入 `.env` 的 llm 配置（T5.7 首次引导）。

为什么需要它：装好的 exe 没有 `.env`，让用户"去安装目录里新建一个文本文件、
敲 `LLM_API_KEY=sk-...`、再重启应用"是最容易被放弃的一步。引导页给一个输入框，
后端负责把它落盘到 `%APPDATA%/Cairn/.env`（安装目录只读，绝不能写那里）。

三条硬约束：
1. **绝不回显**：本模块的任何返回值、日志、异常文本里都不出现 Key（总纲 §2 红线 7）。
2. **不破坏别人的行**：`.env` 里可能还有 FFMPEG_DIR / YTDLP_COOKIES 等手工配置，
   走 `python-dotenv` 的 `set_key`，只改指定键，注释与顺序保持原样。
3. **拒绝换行注入**：值里带 `\\r`/`\\n` 会把一行拆成两行，等于允许写任意环境变量。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import set_key

from app.config import get_settings, reload_settings
from app.errors import ApiError

log = logging.getLogger(__name__)

# 允许写的键 → 对应的 Settings 字段。只放行这几个，别的一律不认：
# 这个端点是给"填个 Key 就能用"的普通用户开的，不是通用配置编辑器。
WRITABLE = {
    "llm_api_key": "LLM_API_KEY",
    "llm_base_url": "LLM_BASE_URL",
    "llm_model": "LLM_MODEL",
}


def _clean(name: str, raw: str) -> str:
    value = (raw or "").strip()
    if any(ch in value for ch in "\r\n"):
        raise ApiError("ENV_INVALID_VALUE", f"{name} 不能包含换行", status=400)
    if '"' in value or "'" in value:
        # 引号会被 dotenv 当成包裹符号吃掉，落盘后值就变了；直接拒绝比静默改写诚实
        raise ApiError("ENV_INVALID_VALUE", f"{name} 不能包含引号", status=400)
    return value


def update_llm(updates: dict[str, str]) -> Path:
    """把非空的 `updates` 写进 `.env` 并热加载；返回落盘路径。

    `updates` 的键是请求字段名（`llm_api_key` 等），值为空串表示"不改这一项"。
    """
    pairs: list[tuple[str, str]] = []
    for field, env_key in WRITABLE.items():
        raw = updates.get(field, "")
        if not raw or not raw.strip():
            continue
        value = _clean(field, raw)
        if field == "llm_base_url" and not value.startswith(("http://", "https://")):
            raise ApiError(
                "ENV_INVALID_VALUE", "接口地址必须以 http:// 或 https:// 开头", status=400
            )
        pairs.append((env_key, value))

    if not pairs:
        raise ApiError("ENV_NOTHING_TO_SAVE", "没有需要保存的内容", status=400)

    path = Path(get_settings().env_file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        for env_key, value in pairs:
            # quote_mode="always"：值一律加引号（dotenv 实际写单引号），
            # base_url 里的 `#`、`=` 才不会被当成注释或分隔符
            set_key(str(path), env_key, value, quote_mode="always")
    except OSError as exc:
        log.warning("写 .env 失败：%s", exc)
        raise ApiError(
            "ENV_WRITE_FAILED", "无法写入配置文件", detail=str(exc), status=500
        ) from exc

    # 热加载：os.environ 里可能已经有旧值（启动时 load_dotenv 灌进去的），
    # 不清掉的话 load_settings 会拿到旧 Key —— 用户会看到"填了但还是没配"。
    for env_key, value in pairs:
        os.environ[env_key] = value
    reload_settings()

    # 日志只记"改了哪几项"，不记值（长度都不记：短 Key 的长度也是信息）
    log.info("已更新 .env：%s → %s", ", ".join(k for k, _ in pairs), path)
    return path
