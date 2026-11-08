"""番茄钟端点（T5.1 / T5.2 / T5.3）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/session/start` | 开始；已有 active（running/paused）→ 409 并带上现有 id |
| GET  | `/api/session/current` | 刷新/重启恢复用，没有则 `{"session": null}` |
| POST | `/api/session/{id}/{action}` | pause / resume / finish / abandon |
| POST | `/api/session/{id}/heartbeat` | 15 秒心跳：卷账 + 重置锚点，**不改 status** |
| GET  | `/api/session` | 学习记录（按 target 过滤，只列 done/abandoned） |

`finish` 接受可选 `{"note": "..."}`（T5.1「结束写笔记」）；其余 action 忽略请求体。

两个刻意的宽容（不是漏洞）：
- `finish`/`abandon` 对**同一个终态**幂等（连点两下不报错），跨终态才 409
- `heartbeat` 对非 running 会话直接返回现状，不报错——闭窗时 `sendBeacon` 与
  「暂停」几乎同时到达，迟到的心跳不该弹错误
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.db.conn import get_conn
from app.db.repo import items as items_repo
from app.db.repo import sessions as repo
from app.errors import ApiError

router = APIRouter(prefix="/api", tags=["session"])

TARGET_TYPES = ("item", "quiz", "html", "free")
ACTIONS = {
    "pause": repo.pause,
    "resume": repo.resume,
    "finish": repo.finish,
    "abandon": repo.abandon,
}


class StartBody(BaseModel):
    target_type: str = "free"
    target_id: int | None = None
    planned_seconds: int = Field(default=1500, ge=60, le=4 * 3600)


class ActionBody(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _load(conn, session_id: int) -> dict:
    session = repo.get(conn, session_id)
    if session is None:
        raise ApiError("SESSION_NOT_FOUND", f"计时 {session_id} 不存在", status=404)
    return session


@router.post("/session/start", status_code=201)
def start(body: StartBody) -> dict:
    if body.target_type not in TARGET_TYPES:
        raise ApiError("SESSION_BAD_TARGET",
                       f"target_type 只能是 {'/'.join(TARGET_TYPES)}", status=422)
    conn = get_conn()
    try:
        if body.target_type == "item":
            if body.target_id is None:
                raise ApiError("SESSION_BAD_TARGET", "target_type=item 时必须带 target_id", status=422)
            if items_repo.get_item(conn, body.target_id) is None:
                raise ApiError("ITEM_NOT_FOUND", f"条目 {body.target_id} 不存在", status=404)
        running = repo.active(conn)
        if running is not None:
            raise ApiError(
                "SESSION_ALREADY_RUNNING", "已经有一个计时在进行中",
                detail=f"id={running['id']} status={running['status']}", status=409,
            )
        with conn:
            session = repo.start(
                conn, target_type=body.target_type, target_id=body.target_id,
                planned_seconds=body.planned_seconds,
            )
        return session
    finally:
        conn.close()


@router.get("/session/current")
def current() -> dict:
    conn = get_conn()
    try:
        return {"session": repo.active(conn)}
    finally:
        conn.close()


@router.get("/session")
def history(
    target_type: str | None = Query(default=None),
    target_id: int | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    conn = get_conn()
    try:
        items, total = repo.history(conn, target_type=target_type, target_id=target_id,
                                    limit=limit, offset=offset)
        return {"items": items, "total": total}
    finally:
        conn.close()


@router.post("/session/{session_id}/heartbeat")
def heartbeat(session_id: int) -> dict:
    conn = get_conn()
    try:
        _load(conn, session_id)
        with conn:
            return repo.heartbeat(conn, session_id)
    finally:
        conn.close()


@router.post("/session/{session_id}/{action}")
def act(session_id: int, action: str, body: ActionBody | None = None) -> dict:
    handler = ACTIONS.get(action)
    if handler is None:
        raise ApiError("SESSION_BAD_ACTION", f"不支持的 action：{action}", status=404)

    conn = get_conn()
    try:
        session = _load(conn, session_id)
        status = session["status"]
        terminal = {"finish": "done", "abandon": "abandoned"}.get(action)

        # 幂等：已经是目标终态就当成功返回，**不重算时长、不覆盖 end_time/note**
        if terminal and status == terminal:
            return session
        if status not in repo.ACTIVE:
            raise ApiError(
                "SESSION_STATE", f"计时当前是 {status}，不能 {action}",
                detail=f"id={session_id} status={status}", status=409,
            )

        with conn:
            if action == "finish":
                return handler(conn, session_id, note=body.note if body else None)
            return handler(conn, session_id)
    finally:
        conn.close()
