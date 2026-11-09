"""设置端点（M6 T6.2–T6.4）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET   | `/api/settings`       | 全量配置，**不含任何密钥**，只给 `has_key` |
| PATCH | `/api/settings`       | 局部更新，返回更新后全量 |
| POST  | `/api/settings/probe` | 探测 provider：列模型 + 判活 + 延迟 |
| POST  | `/api/settings/llm`   | 写 Key 到 `.env`、地址到 `settings.json`，热加载 |

三条纪律：
1. 逻辑全在 `services/prefs.py` / `services/env_store.py` / `services/env_probe.py`，
   路由层只做参数校验与形状拼装 —— 引导页与设置窗口必须看到同一份结果
2. 响应里**永不出现 Key**（红线 7），`has_key` 是唯一对外信号
3. 校验失败一律 400 `SETTINGS_INVALID`，`detail` 指明是哪个键（前端要能定位到行）
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.errors import ApiError
from app.services import env_store, llm_route, prefs
from app.services.env_probe import probe_provider

router = APIRouter(tags=["settings"])


@router.get("/api/settings")
def get_settings() -> dict:
    return prefs.public_view()


@router.patch("/api/settings")
def patch_settings(body: dict) -> dict:
    """局部更新。形状与 GET 的对应子树一致，只带要改的部分。"""
    prefs.save(body)
    return prefs.public_view()


class ProbeBody(BaseModel):
    provider: str
    # 三个都可省略：省略就用已保存的 provider 配置；api_key 只用于本次探测，不落盘
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@router.post("/api/settings/probe")
def probe(body: ProbeBody) -> dict:
    if body.provider not in prefs.PROVIDER_IDS:
        raise ApiError("SETTINGS_INVALID", f"未知的 provider：{body.provider}", status=400)
    saved = prefs.provider(body.provider)
    base_url = (body.base_url or "").strip() or str(saved.get("base_url") or "").strip()
    if not base_url:
        raise ApiError("SETTINGS_INVALID", "缺少接口地址：先填 base_url 再探测",
                       detail=f"llm.providers.{body.provider}.base_url", status=400)
    api_key = (body.api_key or "").strip() or llm_route.key_for(body.provider)
    models = saved.get("models") or []
    model = (body.model or "").strip() or (models[0] if models else "")
    result = probe_provider(base_url, api_key, model)
    # 探测成功且拿到列表：顺手记下来，下次打开设置页模型的候选就是真的（不落 Key）
    if result.get("ok") and result.get("models"):
        try:
            prefs.save({"llm": {"providers": {body.provider: {
                "models": result["models"], "base_url": base_url}}}})
        except ApiError:
            pass  # 记不下来只是候选列表空，不影响本次探测结论
    return result


class LlmBody(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""


@router.post("/api/settings/llm")
def save_llm(body: LlmBody) -> dict:
    """Key 落 `.env`、地址落 `settings.json`，写完立即生效（不重启）。"""
    if body.provider not in prefs.PROVIDER_IDS:
        raise ApiError("SETTINGS_INVALID", f"未知的 provider：{body.provider}", status=400)
    path = env_store.update_provider(body.provider, body.api_key, body.base_url)
    return {"saved": True, "env_file": str(path), "settings": prefs.public_view()}
