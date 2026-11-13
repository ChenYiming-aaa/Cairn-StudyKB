"""试卷端点（M10）：解析与提交。

**这个模块只做两件事：把文件变成草稿、把草稿变成内容与题目。**
题库、判分、复习都复用现有 `question` / `quiz_attempt` / `review_item`
（需求 §5.5：试卷 = 一条 `kind='exam'` 内容 + N 条题目，不新建题库）——
新建一套等于把作答、复习、错题本全部复制一遍。

两条纪律：

1. **`parse` 纯计算不落库**（需求 §6）：上传 100 份试卷不会在知识库里堆出 100 个半成品。
   既然上传那一步已经建好了内容（L1 的占位正文），解析就更不能碰它。
2. **`commit` 一次成型**：内容与全部题目在同一个事务里写，失败整批回滚。
   否则会出现「内容进来了、题目只导了一半」——用户既不能练，也不知道缺哪几题。
"""
from __future__ import annotations

import logging

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.exam import commit as exam_commit
from app.services.exam import parse as exam_parse

router = APIRouter(prefix="/api/exams", tags=["exams"])
log = logging.getLogger(__name__)


class ParseBody(BaseModel):
    file_id: int
    # 默认开：规则切不出的字段（没答案、选项被吃掉）可以让模型补一次；
    # 没有 Key 或模型超时只是「没补上」，规则结果照常返回（parse.py 里已降级）
    use_llm: bool = True


@router.post("/parse")
def parse(body: ParseBody) -> dict:
    """`{file_id}` → `{drafts, stats}`。不建内容、不写库。"""
    result = exam_parse.parse(body.file_id, use_llm=body.use_llm)
    return {"drafts": result["drafts"], "stats": result["stats"]}


class CommitBody(BaseModel):
    file_id: int
    # 复核页原样回传它拿到的那批草稿（可能被用户改过几处）。
    # 不收 `drafts` 之外的字段：题号↔id 的映射由后端重新算，前端不参与对账。
    drafts: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/commit")
def commit(body: CommitBody) -> JSONResponse:
    """复核后的草稿 → 1 条 `kind='exam'` 内容 + N 条 `origin='imported'` 题目（201）。"""
    result = exam_commit.commit(body.file_id, body.drafts)
    return JSONResponse(status_code=201, content=result)
