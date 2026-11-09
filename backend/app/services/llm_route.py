"""LLM 路由解析（M6 T6.3 / ADR-026）。

v0.1.0 的请求体是「一套全局配置」拼出来的：`model` 来自 `.env`，`reasoning_effort` **无条件**
塞进去。接非 DeepSeek 服务时这个字段会让大多数网关直接 400，而且整理想用便宜模型、
问答想用强模型根本做不到。

本模块只做一件事：`resolve(agent)` 把「这次调用该用谁」算清楚 —— provider、base_url、key、
model、effort、要不要发 `reasoning_effort`。**Key 只在内存里，repr 里没有**（红线 7）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import env_value, get_settings
from app.services import prefs


@dataclass(frozen=True)
class Profile:
    """一次 LLM 调用的完整身份。不可变：`chat_stream` 中途不会换模型。"""

    agent: str
    provider: str
    label: str
    model: str
    effort: str
    supports_effort: bool
    base_url: str
    api_key: str = field(default="", repr=False)  # repr=False：异常栈里也不出现

    @property
    def has_key(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


def _key_for(provider: str, key_env: str) -> str:
    """按 provider 的 `key_env` 取 Key。

    走 `config.env_value`（本轮解析出的环境快照）而不是直接读 `os.environ`：
    严格模式下 `.env` 的值刻意没写进进程环境（S-3），只认 `os.environ` 会「配了却说没配」。
    再看 `Settings` 的快照 —— 后者是 v0.1.0 的唯一来源，留着是为了「只配过
    `LLM_API_KEY` 的老用户升级后不用重新填」。
    """
    cfg = get_settings()
    if key_env:
        value = env_value(key_env).strip()
        if value:
            return value
    if provider == "deepseek":
        return (cfg.llm_api_key or "").strip()
    return ""


def key_for(provider: str) -> str:
    """取某 provider 的 Key（**只在本进程内用于请求头/探测，绝不返回给前端**）。"""
    conf = prefs.provider(provider)
    return _key_for(provider, str(conf.get("key_env") or ""))


def resolve(agent: str = "default") -> Profile:
    """解析某个任务实际使用的 profile（解析顺序见 ADR-026）。"""
    base = prefs.get_task_profile(agent)
    return Profile(
        agent=agent,
        provider=base["provider"],
        label=base["label"],
        model=base["model"],
        effort=base["effort"],
        supports_effort=base["supports_effort"],
        base_url=base["base_url"],
        api_key=_key_for(base["provider"], base["key_env"]),
    )


def payload(
    messages: list[dict], profile: Profile, *, json_mode: bool, stream: bool,
    max_tokens: int = 4096,
) -> dict:
    """请求体。

    `reasoning_effort` **只在 provider 声明支持时出现**；`effort == "none"` 时同样整条不带
    （发 `"none"` 有些服务也认，有些服务 400 —— 少发一个字段比重试便宜）。
    """
    body: dict[str, Any] = {
        "model": profile.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if profile.supports_effort and profile.effort in ("low", "medium", "high"):
        body["reasoning_effort"] = profile.effort
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body
