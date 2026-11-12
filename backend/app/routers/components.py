"""下载中心端点（M8 T8.3，接口契约 §components）。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET    | `/api/components`                  | 全部组件的状态（`components.IDS`，别写死个数）+ 清单元信息（repo / tag / 镜像） |
| POST   | `/api/components/{id}/install`     | 起后台下载任务，立即 202 返回 `{task_id}` |
| GET    | `/api/components/{id}/progress`    | 轮询：`{status, phase, got, total, pct, error_code}` |
| POST   | `/api/components/{id}/cancel`      | 取消正在进行的安装（**契约 §3.2 之外新增**，UI 的「取消」要用） |
| DELETE | `/api/components/{id}`             | 卸载：停进程 → 删目录 → 返回释放空间 |

三条纪律：
1. 慢活全在 `services/component_install.py` 的任务线程里，路由层不做 IO ——
   POST install 必须**立刻**返回，否则设置窗口会卡住 30 分钟
2. 错误一律带码（`COMPONENT_DOWNLOAD_FAILED` / `COMPONENT_HASH_MISMATCH` / …），
   前端 `FRIENDLY` 表把它们翻成人话，路由层不拼文案
3. 卸载前先取消再 stop：正在下载时删目录，下载线程会把文件写回已删的路径
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.errors import error_payload
from app.services import component_install, components
from app.services.component_install import InstallError

router = APIRouter(prefix="/api/components", tags=["components"])

# 这些错误码不是"服务器出错"，是"这台机器/这次操作的条件不满足"
_STATUS = {
    "COMPONENT_UNKNOWN": 404,
    "COMPONENT_BUSY": 409,
    "COMPONENT_DISK_FULL": 400,
    "COMPONENT_DOWNLOAD_FAILED": 400,
    "COMPONENT_HASH_MISMATCH": 400,
    "COMPONENT_PACKAGE_INVALID": 400,
}


@router.get("")
def list_components() -> dict:
    man = components.manifest()
    return {
        "items": components.status_all(),
        "repo": man.get("repo", ""),
        "release_tag": man.get("release_tag", ""),
        "manifest_version": man.get("manifest_version", 0),
        "min_app_version": man.get("min_app_version", ""),
        "mirror": component_install.mirror(),
    }


@router.post("/{cid}/install")
def install(cid: str):
    try:
        task_id = component_install.start(cid)
    except InstallError as exc:
        return JSONResponse(
            status_code=_STATUS.get(exc.code, 400),
            content=error_payload(exc.code, exc.message, cid),
        )
    return JSONResponse(status_code=202,
                        content={"task_id": task_id, "id": cid,
                                 "size": int((components.entries().get(cid) or {}).get("size") or 0)})


@router.get("/{cid}/progress")
def progress(cid: str):
    if cid not in components.IDS:
        return JSONResponse(status_code=404,
                            content=error_payload("COMPONENT_UNKNOWN",
                                                  f"没有这个组件：{cid}", cid))
    return component_install.progress(cid)


@router.post("/{cid}/cancel")
def cancel(cid: str):
    if cid not in components.IDS:
        return JSONResponse(status_code=404,
                            content=error_payload("COMPONENT_UNKNOWN",
                                                  f"没有这个组件：{cid}", cid))
    cancelled = component_install.cancel(cid)
    return {"id": cid, "cancelled": cancelled}


@router.delete("/{cid}")
def uninstall(cid: str):
    if cid not in components.IDS:
        return JSONResponse(status_code=404,
                            content=error_payload("COMPONENT_UNKNOWN",
                                                  f"没有这个组件：{cid}", cid))
    component_install.cancel(cid)
    freed = components.uninstall(cid)
    return {"id": cid, "freed": freed}
