"""LLM 客户端（OpenAI 兼容 HTTP，不绑厂商 SDK）。

调用规范见 M1 §6.11 / ADR-021，路由规则见 ADR-026：
- POST `{base_url}/chat/completions`，base_url 拼接前 rstrip('/')
- 只取 message.content，丢弃 reasoning_content
- 结构化输出带 response_format=json_object
- `reasoning_effort` 只在 provider 声明 supports_effort 时发送；被 400 拒绝时自动去掉重试一次
- 每次调用写 llm_call_log（含 reasoning_tokens，ADR-022），`model` 记**实际使用的**那个
- API Key 只从 `.env` 读，绝不进日志、异常栈、前端（总纲红线 7）
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Iterator

import httpx

from app.config import get_settings
from app.db.conn import get_conn
from app.db.repo.items import now_iso
from app.services import llm_route
from app.services.llm_route import Profile

log = logging.getLogger(__name__)

RETRY_DELAYS = (1, 3)  # 失败重试 2 次，1s / 3s 退避
# 402 欠费、429 限流：对用户是同一件事（先去充值/等额度），前端提示与排障路径一致，
# 所以归到同一个码。其余 4xx/5xx 仍走 LLM_HTTP_ERROR（M4 §7）。
QUOTA_STATUS = frozenset({402, 429})


class LLMError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def _safe_detail(exc: Exception) -> str:
    """只保留异常类型与状态码，绝不带上请求头 / Key。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def error_from(exc: Exception) -> LLMError:
    """把底层异常归一成对外错误码（M4 §7 要求区分超时与额度）。

    - `httpx.TimeoutException`（含读/连接/写超时）→ `LLM_TIMEOUT`
    - HTTP 402 / 429 → `LLM_QUOTA`
    - 其余（5xx、连接失败、坏响应）→ `LLM_HTTP_ERROR`

    批改与出题都靠这个码决定用户看到什么：简答批改遇 `LLM_TIMEOUT` / `LLM_QUOTA`
    一律落「待人工判断」，而不是判错（M4 §1 约束 3）。
    """
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("LLM_TIMEOUT", "模型响应超时，请稍后重试", "timeout")
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in QUOTA_STATUS:
        return LLMError("LLM_QUOTA", "模型额度不足或触发限流，请检查账户余额后重试",
                        f"HTTP {status}")
    return LLMError("LLM_HTTP_ERROR", "LLM 调用失败", _safe_detail(exc))


def no_key_error(profile: Profile) -> LLMError:
    """缺 Key 的提示必须指明是哪个 provider：双 provider 下只说「没配 Key」没法自查。"""
    return LLMError(
        "LLM_NO_KEY",
        f"未配置 {profile.label} 的 API Key：打开设置 → 模型，填入后立即生效",
        f"provider={profile.provider}",
    )


def _headers(profile: Profile) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {profile.api_key.strip()}",
        "Content-Type": "application/json",
    }


def _effort_rejected(resp: httpx.Response, body: dict, *, stream: bool = False) -> bool:
    """服务对 `reasoning_effort` 明确表示不支持时才返回 True（400 且错误体点名字段）。"""
    if "reasoning_effort" not in body or resp.status_code != 400:
        return False
    try:
        if stream:
            resp.read()   # 流式响应体默认没读，不先读就拿不到错误文本
        text = (resp.text or "").lower()
    except Exception:  # noqa: BLE001 - 读不到错误体就当作"不是这个原因"
        return False
    return "reasoning_effort" in text or "unsupported" in text


def _strip_effort(body: dict) -> dict:
    return {k: v for k, v in body.items() if k != "reasoning_effort"}


def _usage(data: dict) -> tuple[int | None, int | None, int | None]:
    usage = data.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return (
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        details.get("reasoning_tokens"),
    )


def _write_log(
    *, agent: str, model: str, ok: bool, duration_ms: int,
    prompt_tokens: int | None = None, completion_tokens: int | None = None,
    reasoning_tokens: int | None = None, error_msg: str | None = None,
) -> None:
    """写 `llm_call_log`。`model` 是**本次实际用的**模型（T6.3 前记的是全局配置，会失真）。"""
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                """INSERT INTO llm_call_log
                   (agent, model, prompt_tokens, completion_tokens, reasoning_tokens,
                    duration_ms, ok, error_msg, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent, model, prompt_tokens, completion_tokens,
                 reasoning_tokens, duration_ms, 1 if ok else 0, error_msg, now_iso()),
            )
    except Exception as exc:
        # 日志写失败不能让业务调用崩，但也绝不静默（红线 8）
        log.error("llm_call_log 写入失败：%s", type(exc).__name__)
    finally:
        conn.close()


def chat(
    messages: list[dict], *, agent: str = "default", json_mode: bool = False,
    timeout: int | None = None,
) -> str:
    """非流式调用，返回 message.content。失败重试 2 次（1s/3s 退避）。

    `timeout`：单次覆盖 `LLM_TIMEOUT`。简答批改刻意用更短的 60s（M4 §6.4），
    靠超时把「批改服务不可用」变成待人工判断，而不是让用户干等 120s。
    """
    cfg = get_settings()
    profile = llm_route.resolve(agent)
    if not profile.has_key:
        _write_log(agent=agent, model=profile.model, ok=False, duration_ms=0,
                   error_msg="LLM_NO_KEY")
        raise no_key_error(profile)

    body = llm_route.payload(messages, profile, json_mode=json_mode, stream=False)
    log.info("LLM 调用 agent=%s provider=%s model=%s effort=%s",
             agent, profile.provider, profile.model,
             body.get("reasoning_effort") or "none")
    started = time.monotonic()
    last: LLMError | None = None
    retry_effort = True

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with httpx.Client(timeout=timeout or cfg.llm_timeout) as client:
                resp = client.post(profile.url, headers=_headers(profile), json=body)
                if retry_effort and _effort_rejected(resp, body):
                    # 只去掉字段重来一次，不递归、不加退避：这是能力差异不是网络抖动
                    retry_effort = False
                    body = _strip_effort(body)
                    log.warning("%s 不接受 reasoning_effort，去掉该字段重试", profile.provider)
                    resp = client.post(profile.url, headers=_headers(profile), json=body)
                resp.raise_for_status()
                data = resp.json()
            content = (data["choices"][0]["message"].get("content") or "")
            pt, ct, rt = _usage(data)
            _write_log(agent=agent, model=profile.model, ok=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       prompt_tokens=pt, completion_tokens=ct, reasoning_tokens=rt)
            return content
        except (KeyError, IndexError, ValueError) as exc:
            last = LLMError("LLM_BAD_RESPONSE", "LLM 响应结构异常", _safe_detail(exc))
            break
        except Exception as exc:
            last = error_from(exc)
            if attempt < len(RETRY_DELAYS):
                log.warning("LLM 第 %s 次调用失败（%s），%ss 后重试",
                            attempt + 1, last.detail, RETRY_DELAYS[attempt])
                time.sleep(RETRY_DELAYS[attempt])
                continue
            break

    _write_log(agent=agent, model=profile.model, ok=False,
               duration_ms=int((time.monotonic() - started) * 1000),
               error_msg=last.code if last else "LLM_HTTP_ERROR")
    # from None：切断原始 httpx 异常上下文，避免请求头（含 Key）进入异常栈
    raise (last or LLMError("LLM_HTTP_ERROR", "LLM 调用失败")) from None


def chat_stream(
    messages: list[dict], *, agent: str = "default", usage_out: dict | None = None,
    max_tokens: int = 4096,
) -> Iterator[str]:
    """流式调用，只 yield content 的 delta；reasoning_content 的 delta 直接丢弃。

    `usage_out`：可选的字典，调用方传进来就地填 token 用量（SSE 的 done 事件要用）。
    用可变容器而不是返回值，是因为流式生成器只能 yield 文本片段。
    `max_tokens`：出题要一次吐 20 题（≈4k+ token），调用方可以抬高；默认仍是 4096。
    """
    cfg = get_settings()
    profile = llm_route.resolve(agent)
    if not profile.has_key:
        _write_log(agent=agent, model=profile.model, ok=False, duration_ms=0,
                   error_msg="LLM_NO_KEY")
        raise no_key_error(profile)

    body = llm_route.payload(messages, profile, json_mode=False, stream=True,
                             max_tokens=max_tokens)
    headers = _headers(profile)
    log.info("LLM 流式调用 agent=%s provider=%s model=%s effort=%s",
             agent, profile.provider, profile.model,
             body.get("reasoning_effort") or "none")
    started = time.monotonic()
    pt = ct = rt = None
    ok = False
    retry_effort = True
    try:
        while True:
            with httpx.Client(timeout=cfg.llm_timeout) as client:
                with client.stream("POST", profile.url, headers=headers, json=body) as resp:
                    if retry_effort and _effort_rejected(resp, body, stream=True):
                        retry_effort = False
                        body = _strip_effort(body)
                        log.warning("%s 不接受 reasoning_effort，去掉该字段重试",
                                    profile.provider)
                        continue          # 只可能回到这里一次
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            data = json.loads(raw)
                        except ValueError:
                            continue
                        if data.get("usage"):
                            pt, ct, rt = _usage(data)
                        for choice in data.get("choices") or []:
                            delta = choice.get("delta") or {}
                            piece = delta.get("content")
                            if piece:
                                yield piece
            ok = True
            break
    except Exception as exc:
        err = error_from(exc)
        _write_log(agent=agent, model=profile.model, ok=False,
                   duration_ms=int((time.monotonic() - started) * 1000),
                   error_msg=err.code)
        raise err from None
    finally:
        if ok:
            _write_log(agent=agent, model=profile.model, ok=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       prompt_tokens=pt, completion_tokens=ct, reasoning_tokens=rt)
        if usage_out is not None:
            usage_out.update({"prompt_tokens": pt, "completion_tokens": ct,
                              "reasoning_tokens": rt})


def _paired_object(text: str) -> str | None:
    """从左到右找第一个 {，跳过字符串内的括号，截取到匹配的 }。"""
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_json(text: str) -> dict:
    """M1 §6.3 的实现顺序；失败抛 LLM_BAD_JSON，由调用方决定是否重试。"""
    if not text or not text.strip():
        raise LLMError("LLM_BAD_JSON", "LLM 返回空内容")
    for candidate in (
        text.strip(),
        (lambda m: m.group(1).strip() if m else None)(
            re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        ),
        _paired_object(text),
    ):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            continue
    raise LLMError("LLM_BAD_JSON", "无法从 LLM 响应中解析出 JSON 对象")
