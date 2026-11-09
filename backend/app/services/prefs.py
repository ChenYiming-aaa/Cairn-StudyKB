"""用户偏好读写（M6 T6.2）。

职责只有一件：把 `<数据目录>/settings.json` 变成一个**可以被手改、被损坏、被并发写**的文件，
而调用方永远拿到一份形状完整、可直接用的字典。

四条规则（数据契约 §9，缺一条就会出现"用户手改一个键，整个设置没了"）：
1. **缺省即合并**：`默认值 ← 文件` 深合并，文件缺键就补，坏一个键不影响其余
2. **损坏即备份**：解析失败把原文件改名 `settings.json.bad-<时间戳>`，用默认值继续跑
3. **原子写**：先写唯一临时文件再 `os.replace`，断电不会留半截
4. **按 mtime 失效缓存**：用户手改 JSON 后下一次读取就生效，不用重启

密钥不在这里：Key 只活在 `.env`（红线 7），本模块只认 `key_env`（变量名）。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

from app.config import config_audit, env_value, get_settings
from app.errors import ApiError

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

THEMES = ("paper", "notes", "chestnut", "docs", "study", "teal")
MODES = ("light", "dark", "system")
FONT_SIZES = ("sm", "md", "lg")
EFFORTS = ("none", "low", "medium", "high")
# 四个任务与 llm._write_log 的 agent 名一致，改这里要同步改 services/agents/*
AGENTS = ("organizer", "asker", "quizzer", "grader")
PROVIDER_IDS = ("deepseek", "custom")

DEFAULT_PROVIDER = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "key_env": "LLM_API_KEY",
        "supports_effort": True,
        "models": ["deepseek-flash", "deepseek-reasoner"],
    },
    "custom": {
        "label": "OpenAI 兼容",
        "base_url": "",
        "key_env": "ALT_API_KEY",
        "supports_effort": False,
        "models": [],
    },
}

DEFAULT_TASK = {"provider": "deepseek", "model": "deepseek-flash", "effort": "low"}


def defaults() -> dict:
    """完整默认值。每次返回新对象，调用方随便改不会污染别人。"""
    return {
        "version": SCHEMA_VERSION,
        "llm": {
            "active": "deepseek",
            "providers": copy.deepcopy(DEFAULT_PROVIDER),
            "tasks": {agent: dict(DEFAULT_TASK) for agent in AGENTS},
        },
        # font_size：2026-11-09 裁决做三档（T6.8 落地），先占位保证形状稳定
        "appearance": {"theme": "paper", "mode": "system", "font_size": "md"},
        "components": {},
    }


def path() -> Path:
    return Path(get_settings().data_dir) / "settings.json"


def _seed_from_env() -> dict:
    """**首次**读取（还没有 settings.json）时，用 `.env` 的现值做初值。

    为什么必须做：v0.1.0 用户把 base_url / model / effort 全写在 `.env` 里，
    如果这里直接给硬编码默认值，升级后他们的接口地址会被悄悄换回 DeepSeek 官方地址 ——
    表现就是「昨天还能用，今天 401」。settings.json 一旦存在，就以它为准。
    """
    data = defaults()
    cfg = get_settings()
    deepseek = data["llm"]["providers"]["deepseek"]
    if (cfg.llm_base_url or "").strip():
        deepseek["base_url"] = cfg.llm_base_url.strip().rstrip("/")
    if (cfg.llm_model or "").strip():
        model = cfg.llm_model.strip()
        if model not in deepseek["models"]:
            deepseek["models"] = [model] + deepseek["models"]
        for task in data["llm"]["tasks"].values():
            task["model"] = model
    if (cfg.llm_effort or "").strip() in EFFORTS:
        for task in data["llm"]["tasks"].values():
            task["effort"] = cfg.llm_effort.strip()
    return data


# ── 缓存：按 (mtime_ns, size) 失效 ─────────────────────────────
_lock = threading.RLock()
_cache: dict | None = None
_cache_key: tuple[int, int] | None = None


def _stat_key(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _deep_merge(base: dict, patch: dict) -> dict:
    """`patch` 覆盖 `base`；只对 dict 递归，list 整体替换（模型列表不能合并成并集）。"""
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _read_file(p: Path) -> dict:
    """读 + 合并默认值；损坏时备份并回落默认值。任何情况下都返回可用字典。"""
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _seed_from_env()
    except OSError as exc:
        log.warning("读 settings.json 失败（%s），改用默认值", type(exc).__name__)
        return defaults()
    if not raw.strip():
        return defaults()
    try:
        loaded = json.loads(raw)
    except ValueError:
        loaded = None
    if not isinstance(loaded, dict):
        _quarantine(p)
        return defaults()
    return _deep_merge(defaults(), loaded)


def _quarantine(p: Path) -> None:
    """损坏文件不删，改名留证：用户手改坏了还能捞回来。"""
    backup = p.with_name(f"{p.name}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        os.replace(p, backup)
        log.warning("settings.json 解析失败，已备份为 %s 并用默认值继续", backup.name)
    except OSError as exc:
        log.error("settings.json 损坏且备份失败：%s", type(exc).__name__)


def load() -> dict:
    """当前生效配置（默认值 ← 文件）。带 mtime 缓存，手改文件后下一次调用即生效。"""
    p = path()
    key = _stat_key(p)
    with _lock:
        global _cache, _cache_key
        if _cache is not None and key == _cache_key:
            return copy.deepcopy(_cache)
        data = _read_file(p)
        _cache, _cache_key = copy.deepcopy(data), key
        return data


def invalidate() -> None:
    """丢掉缓存（换数据目录、或测试里直接改文件后强制重读）。"""
    global _cache, _cache_key
    with _lock:
        _cache, _cache_key = None, None


def _check(merged: dict) -> None:
    """写盘前的语义校验。只校验"会直接导致功能错乱"的键，不做通用 schema。"""
    llm = merged.get("llm") or {}
    active = llm.get("active")
    if active not in PROVIDER_IDS:
        raise ApiError("SETTINGS_INVALID", f"未知的 provider：{active}", detail="llm.active", status=400)

    providers = llm.get("providers") or {}
    for pid, conf in providers.items():
        if pid not in PROVIDER_IDS:
            raise ApiError("SETTINGS_INVALID", f"未知的 provider：{pid}",
                           detail="llm.providers", status=400)
        base = str(conf.get("base_url") or "")
        if base and not base.startswith(("http://", "https://")):
            raise ApiError("SETTINGS_INVALID", "接口地址必须以 http:// 或 https:// 开头",
                           detail=f"llm.providers.{pid}.base_url", status=400)
        models = conf.get("models")
        if models is not None and not isinstance(models, list):
            raise ApiError("SETTINGS_INVALID", "模型列表必须是数组",
                           detail=f"llm.providers.{pid}.models", status=400)

    tasks = llm.get("tasks") or {}
    for agent, task in tasks.items():
        if agent not in AGENTS and agent != "*":
            raise ApiError("SETTINGS_INVALID", f"未知的任务：{agent}",
                           detail="llm.tasks", status=400)
        if task.get("provider") and task["provider"] not in PROVIDER_IDS:
            raise ApiError("SETTINGS_INVALID", f"未知的 provider：{task['provider']}",
                           detail=f"llm.tasks.{agent}.provider", status=400)
        if task.get("effort") and task["effort"] not in EFFORTS:
            raise ApiError("SETTINGS_INVALID", f"未知的思考强度：{task['effort']}",
                           detail=f"llm.tasks.{agent}.effort", status=400)

    look = merged.get("appearance") or {}
    for field, allowed in (("theme", THEMES), ("mode", MODES), ("font_size", FONT_SIZES)):
        value = look.get(field)
        if value is not None and value not in allowed:
            raise ApiError("SETTINGS_INVALID", f"{field} 取值非法：{value}",
                           detail=f"appearance.{field}", status=400)


def save(patch: dict) -> dict:
    """深合并写入并返回写入后的全量。`patch` 只带要改的部分。"""
    if not isinstance(patch, dict) or not patch:
        raise ApiError("SETTINGS_INVALID", "没有需要保存的内容", status=400)

    p = path()
    with _lock:
        merged = _deep_merge(load(), patch)
        merged["version"] = SCHEMA_VERSION
        _check(merged)
        _write_atomic(p, merged)
        global _cache, _cache_key
        _cache, _cache_key = copy.deepcopy(merged), _stat_key(p)
        return merged


def _write_atomic(p: Path, data: dict) -> None:
    """唯一临时名 + os.replace：并发写不会互相覆盖出坏文件。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    except OSError as exc:
        log.error("写 settings.json 失败：%s", type(exc).__name__)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ApiError("SETTINGS_WRITE_FAILED", "无法写入设置文件",
                       detail=type(exc).__name__, status=500) from exc


def provider(pid: str) -> dict:
    """某个 provider 的配置（已合并默认值）；未知 id 抛 400。"""
    providers = load()["llm"]["providers"]
    if pid not in providers:
        raise ApiError("SETTINGS_INVALID", f"未知的 provider：{pid}", status=400)
    return providers[pid]


def has_key(pid: str) -> bool:
    """该 provider 的 Key 配没配 —— 只看对应变量有没有值，**绝不返回值**。

    走 `config.env_value` 而不是 `os.environ`：严格模式下 `.env` 的值不在进程环境里（S-3）。
    """
    conf = provider(pid)
    env_name = str(conf.get("key_env") or "")
    if env_name and env_value(env_name).strip():
        return True
    # 老口径兜底：v0.1.0 的 .env 一直用 LLM_API_KEY，Settings 里也留了一份快照
    return pid == "deepseek" and get_settings().has_llm_key


def get_task_profile(agent: str) -> dict:
    """解析某个任务实际要用的 provider / model / effort（路由规则见 ADR-026）。

    顺序：`tasks[agent]` → `tasks['*']` → `providers[active]` 的默认。
    返回的 `model` 一定是非空串（回落到 `models[0]`，再回落到 `.env` 的 `LLM_MODEL`）。
    """
    cfg = get_settings()
    llm = load()["llm"]
    task = dict(llm["tasks"].get(agent) or llm["tasks"].get("*") or {})
    pid = task.get("provider") or llm.get("active") or "deepseek"
    conf = llm["providers"].get(pid) or DEFAULT_PROVIDER["deepseek"]
    models = conf.get("models") or []
    model = (task.get("model") or "").strip() or (models[0] if models else "") or cfg.llm_model
    effort = (task.get("effort") or "").strip() or cfg.llm_effort or "low"
    return {
        "agent": agent,
        "provider": pid,
        "label": conf.get("label") or pid,
        "model": model,
        "effort": effort,
        "supports_effort": bool(conf.get("supports_effort")),
        "base_url": str(conf.get("base_url") or cfg.llm_base_url).rstrip("/"),
        "key_env": str(conf.get("key_env") or ""),
    }


def public_view() -> dict:
    """给前端的形状：不含任何密钥，只给 `has_key`（接口契约 GET /api/settings）。"""
    data = load()
    providers = {
        pid: {
            "label": conf.get("label") or pid,
            "base_url": conf.get("base_url") or "",
            "has_key": has_key(pid),
            "supports_effort": bool(conf.get("supports_effort")),
            "models": list(conf.get("models") or []),
        }
        for pid, conf in data["llm"]["providers"].items()
    }
    return {
        "llm": {
            "active": data["llm"].get("active") or "deepseek",
            "providers": providers,
            "tasks": data["llm"]["tasks"],
        },
        "appearance": data["appearance"],
        "components": data.get("components") or {},
        "env_file": str(get_settings().env_file),
        # 配置来源（S-3）：设置窗口的「关于」直接显示「有没有从老地方拿过配置」
        "config": config_audit(),
    }
