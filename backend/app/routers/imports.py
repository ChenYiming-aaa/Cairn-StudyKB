"""目录批量导入（T10.6）：**先看清单，再逐个导**。

两条纪律：

1. **只列不导**（`scan`）：一个文件夹扔进来就全导，用户连「哪几个是重复的、哪几个格式不支持」
   都看不到，导完才发现盘里多了 80 条乱七八糟的东西。所以第一步只出清单。
2. **逐个失败不影响其余**（`run`）：一个 PDF 损坏不该让后面 99 个白导。
   结果分三堆报：成功 / 跳过（库里已有）/ 失败（带原因）—— 「导了 8 个」和
   「8 个成功、1 个重复、1 个读不了」是两件事，后者用户才知道该去补哪一份。

上限 100 个：一次导几百份，光是识别队列就要跑几小时，中途关窗口留下的半截状态
比「分两批」更难收拾。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.errors import ApiError
from app.services import files as file_service
from app.routers.files import _queue_read

router = APIRouter(prefix="/api/import", tags=["import"])
log = logging.getLogger(__name__)

MAX_FILES = 100


def _natural_key(name: str) -> list:
    """文件名自然序：`第1题` 排在 `第10题` 前面。纯字典序会把它排到 `第2题` 之后，
    而导入顺序就是用户看到的清单顺序，乱了会显得很随意。"""
    return [(0, int(part)) if part.isdigit() else (1, part.lower())
            for part in re.split(r"(\d+)", name) if part]


def _entry(path: Path) -> dict:
    """一个候选文件 → 清单项。`supported` 为假时 `reason` 说明为什么。"""
    ext = path.suffix.lstrip(".").lower()
    try:
        size = path.stat().st_size
    except OSError as exc:
        return {"path": str(path), "name": path.name, "ext": ext, "size": 0,
                "supported": False, "reason": f"读不到这个文件（{exc.strerror or '拒绝访问'}）"}
    if not path.is_file():
        return {"path": str(path), "name": path.name, "ext": ext, "size": 0,
                "supported": False, "reason": "不是文件"}
    if ext in file_service.LEGACY_EXT:
        target = file_service.LEGACY_EXT[ext]
        return {"path": str(path), "name": path.name, "ext": ext, "size": size,
                "supported": False, "reason": f"老格式，另存为 .{target} 再导"}
    if ext not in file_service.ALLOWED_EXT:
        return {"path": str(path), "name": path.name, "ext": ext, "size": size,
                "supported": False, "reason": "这种格式读不了"}
    if size > file_service.MAX_BYTES:
        limit = file_service.MAX_BYTES // (1024 * 1024)
        return {"path": str(path), "name": path.name, "ext": ext, "size": size,
                "supported": False, "reason": f"超过 {limit} MB"}
    return {"path": str(path), "name": path.name, "ext": ext, "size": size,
            "supported": True, "reason": ""}


def collect(paths: list[str]) -> tuple[list[dict], bool]:
    """目录（或文件）列表 → 清单项 + 是否被截断。

    **只扫一层**：子文件夹里的东西不跟。递归收集看着方便，实际会把 `node_modules`、
    `.git` 这类目录整个卷进来，而用户选目录时想的是「这个文件夹里的卷子」。
    """
    out: list[dict] = []
    truncated = False
    for raw in paths:
        if not raw:
            continue
        root = Path(raw)
        if root.is_dir():
            try:
                children = sorted(
                    (e for e in root.iterdir() if e.is_file() and not e.name.startswith(".")),
                    key=lambda e: _natural_key(e.name),
                )
            except OSError as exc:
                out.append({"path": str(root), "name": root.name, "ext": "", "size": 0,
                            "supported": False, "reason": f"打不开这个文件夹（{exc.strerror or '拒绝访问'}）"})
                continue
        elif root.exists():
            children = [root]
        else:
            out.append({"path": str(root), "name": root.name, "ext": "", "size": 0,
                        "supported": False, "reason": "这个路径不在了"})
            continue

        for child in children:
            if len(out) >= MAX_FILES:
                truncated = True
                break
            out.append(_entry(child))
        if truncated:
            break
    return out, truncated


class ScanBody(BaseModel):
    paths: list[str] = Field(default_factory=list)


@router.post("/scan")
def scan(body: ScanBody) -> dict:
    """列清单，**不导**。前端据此让用户勾选要导哪几个。"""
    files, truncated = collect(body.paths)
    return {
        "files": files,
        "total": len(files),
        "supported": sum(1 for f in files if f["supported"]),
        "truncated": truncated,
        "limit": MAX_FILES,
    }


class RunBody(BaseModel):
    # 只收文件路径（用户在清单里勾过的），不收目录：目录在扫描之后可能又多了文件，
    # 按目录再扫一遍会让「我明明只勾了 3 个，怎么进来 5 个」发生
    paths: list[str] = Field(default_factory=list)


def _import_one(raw: str) -> dict:
    path = Path(raw)
    if not path.is_file():
        raise ApiError("IMPORT_NOT_FOUND", "这个文件不在了", detail=raw, status=404)
    with path.open("rb") as handle:
        saved = file_service.save(handle, filename=path.name)
    # 排队读字与上传走同一条路：组件没装就留在 pending，装完点重读即可
    task_id = _queue_read(saved)
    return {
        "path": str(path),
        "name": path.name,
        "file_id": saved.file_id,
        "item_id": saved.item_id,
        "ocr_status": saved.ocr_status,
        "task_id": task_id,
        "duplicated": saved.duplicated,
    }


@router.post("/run")
def run(body: RunBody) -> dict:
    """按清单顺序逐个导入。**一个失败不影响其余**，三堆分开报。"""
    paths = [p for p in (body.paths or []) if p]
    if not paths:
        raise ApiError("IMPORT_EMPTY", "没有要导入的文件", status=422)
    if len(paths) > MAX_FILES:
        raise ApiError("IMPORT_TOO_MANY", f"一次最多导入 {MAX_FILES} 个，分成几批吧",
                       detail=str(len(paths)), status=422)

    added: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    for raw in paths:
        try:
            result = _import_one(raw)
        except ApiError as exc:
            failed.append({"path": raw, "name": Path(raw).name,
                           "code": exc.code, "reason": exc.message})
            log.warning("批量导入跳过 %s：%s（%s）", raw, exc.message, exc.code)
            continue
        except Exception as exc:            # noqa: BLE001 - 单个文件读不了不能拖垮整批
            failed.append({"path": raw, "name": Path(raw).name,
                           "code": "IMPORT_FAILED", "reason": f"读不了这个文件（{type(exc).__name__}）"})
            log.warning("批量导入异常 %s：%s", raw, type(exc).__name__)
            continue
        (skipped if result["duplicated"] else added).append(result)

    log.info("批量导入：%s 个文件 → 新增 %s、重复 %s、失败 %s",
             len(paths), len(added), len(skipped), len(failed))
    return {
        "total": len(paths),
        "added": added,
        "skipped": skipped,
        "failed": failed,
        "added_count": len(added),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
    }
