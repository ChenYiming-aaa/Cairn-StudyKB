"""模型输出形状（`services/schemas.py`）的契约。

这一组不测「模型肯不肯听话」，只测「模型不听话时我们最后存进去的是什么」——
后者才是缺陷发生的地方：`str({"a": 1})` 变成一个标题时不会抛任何异常，
只会在几天后表现为「这条内容的标题是一串花括号」。
"""
from __future__ import annotations

import typing

import pytest
from pydantic import ValidationError

from app.services import schemas
from app.services.agents import quizzer
from app.services.exam.prompt import merge
from app.services.schemas import ExamFix, OrganizeResult, QuizItem


def organize(**raw) -> OrganizeResult:
    """只给关心的字段，其余走默认 —— 让每个用例只表达一件事。"""
    return OrganizeResult.from_raw(raw, "原题")


# ── 题型 / 难度：两份定义必须一致 ────────────────────────────

def test_quiz_types_match_literal():
    """`TYPES` 是运行时判据、`QuizType` 是字段类型，改一处忘另一处就是「新题型永远被跳过」。"""
    assert list(typing.get_args(schemas.QuizType)) == list(schemas.TYPES)


def test_difficulties_match_literal():
    assert list(typing.get_args(schemas.Difficulty)) == list(schemas.DIFFICULTIES)


# ── 标题：任何非文本形态都不许变成字符串 ────────────────────

@pytest.mark.parametrize("raw_title", [{"a": 1}, ["甲", "乙"], {"标题": "甲"}, True, None, ""])
def test_title_not_stringified(raw_title):
    """模型把标题写成对象/数组时，退回原标题 —— 不许出现 `{'a': 1}` 这种标题。"""
    assert organize(title=raw_title, summary="摘要").title == "原题"


@pytest.mark.parametrize(("raw_title", "expected"), [
    ("  《宏观  经济学》  ", "宏观 经济学"),
    ("第一章：绪论。", "第一章：绪论"),
    ("《》", "原题"),                          # 只剩书名号 → 等于没给
    ("一" * 30, "一" * 20),                    # 超长强截，不加省略号
])
def test_title_cleaned(raw_title, expected):
    assert organize(title=raw_title, summary="摘要").title == expected


def test_title_fallback_never_empty():
    """条目本身标题为空时也得有个非空标题，否则整条内容在列表里没有可点的字。"""
    assert OrganizeResult.from_raw({"summary": "摘要"}, "").title == "未命名"


# ── 标签 / 要点：只收文本，且不重复 ────────────────────────

def test_tags_dropped_when_not_list():
    """模型把 tags 写成一句话时按空处理（与改造前同口径）：猜分隔符的代价是标签里出现怪词。"""
    assert organize(summary="摘要", tags="复习, 考试").tags == []


def test_tags_cleaned_and_deduped():
    result = organize(summary="摘要", tags=["#复习", "复习", " 考试 ", "", 3])
    assert result.tags == ["复习", "考试", "3"]


def test_tags_capped():
    assert len(organize(summary="摘要", tags=[f"标签{i}" for i in range(12)]).tags) == schemas.MAX_TAGS


def test_key_points_drop_non_text():
    assert organize(summary="摘要", key_points=[{"x": 1}, "要点一", 3, ["要点二"]]).key_points == [
        "要点一", "3"]


def test_key_points_capped():
    points = [f"要点{i}" for i in range(12)]
    assert len(organize(summary="摘要", key_points=points).key_points) == schemas.MAX_KEY_POINTS


def test_category_default_only_when_missing():
    """分类不设长度上限：15 字的课程全名是正经分类，截断反而让它对不上别的条目。"""
    assert organize(summary="摘要").category == "未分类"
    assert organize(summary="摘要", category={"x": 1}).category == "未分类"
    full = "马克思主义基本原理概论"
    assert organize(summary="摘要", category=f" {full} ").category == full


# ── structured_note：非 material 一律清空（不是「别动」）────

@pytest.mark.parametrize("kind", ["exam", "image"])
def test_structured_note_cleared(kind):
    """prompt 说了不要输出，模型偶尔还是写一篇 —— 在形状层拦住，而不是指望它听话。"""
    result = OrganizeResult.from_raw(
        {"summary": "摘要", "structured_note": "## 笔记\n正文"}, "试卷", kind)
    assert result.structured_note == ""


def test_structured_note_kept_for_material():
    result = organize(summary="摘要", structured_note="  ## 笔记  ")
    assert result.structured_note == "## 笔记"


def test_empty_summary_survives_as_empty():
    """空摘要不在形状层判死：它由 `organizer._quality_ok` 触发重试，两条路不能混。"""
    assert organize(summary=None).summary == ""


# ── 出题：跳过原因保持原样，坏形状只是多一种 ────────────────

def _raw(**patch) -> dict:
    base = {"type": "single", "question": "下列说法正确的是？",
            "options": ["甲", "乙"], "answer": "A", "explanation": "依据在第一段",
            "difficulty": "understand"}
    base.update(patch)
    return base


def test_quiz_item_accepts_clean_object():
    data, reason = quizzer.normalize(_raw(), difficulty="basic")
    assert reason == "" and data["type"] == "single" and data["answer"] == "A"


@pytest.mark.parametrize(("patch", "reason"), [
    ({"type": "填空"}, "bad_type"),
    ({"question": "短"}, "empty_question"),
    ({"explanation": "  "}, "missing_explanation"),
    ({"answer": "Z"}, "bad_answer"),
    ({"options": ["甲"]}, "bad_options"),
])
def test_quiz_skip_reasons_unchanged(patch, reason):
    """跳过原因是对外口径（SSE 的 skip 事件），形状层不许把它们合并成一种。"""
    data, got = quizzer.normalize(_raw(**patch), difficulty="basic")
    assert (data, got) == (None, reason)


def test_quiz_difficulty_falls_back_to_request():
    """模型给了 basic/understand/apply 以外的值时，用请求里那一档，不是拒绝这道题。"""
    data, reason = quizzer.normalize(_raw(difficulty="很难"), difficulty="apply")
    assert reason == "" and data["difficulty"] == "apply"


def test_quiz_answer_shapes_by_type():
    multiple, _ = quizzer.normalize(
        _raw(type="multiple", options=["甲", "乙", "丙"], answer=["A", "C"]), difficulty="basic")
    judge, _ = quizzer.normalize(
        _raw(type="boolean", options=[], answer="对"), difficulty="basic")
    short, _ = quizzer.normalize(
        _raw(type="short", options=[], answer="先算总量再除以天数"), difficulty="basic")
    assert multiple["answer"] == ["A", "C"]
    assert judge["answer"] is True
    assert short["answer"].startswith("先算总量")


def test_quiz_item_rejects_unknown_type():
    """`QuizItem` 自己也要拦：模型侧的新题型不能靠「恰好没进 TYPES」蒙过去。"""
    with pytest.raises(ValidationError):
        QuizItem(type="essay", question="请论述", options=[], answer="A",
                 explanation="依据", difficulty="basic")


# ── 试卷补字段：坏一个字段只丢那一个 ──────────────────────

def test_exam_fix_drops_bad_score():
    assert ExamFix.from_raw({"score": "3分"}).score is None
    assert ExamFix.from_raw({"score": 999}).score is None
    assert ExamFix.from_raw({"score": 2}).score == 2.0


def test_exam_fix_clamps_confidence():
    assert ExamFix.from_raw({"confidence": 5}).confidence == 1.0
    assert ExamFix.from_raw({"confidence": -3}).confidence == 0.0
    assert ExamFix.from_raw({"confidence": "高"}).confidence is None


def test_exam_fix_options_must_be_list():
    assert ExamFix.from_raw({"options": "A. 甲 B. 乙"}).options == []
    assert ExamFix.from_raw({"options": ["A. 甲", "", {"x": 1}, "乙"]}).options == ["A. 甲", "乙"]


def test_exam_fix_type_accepts_any_text():
    """中文题型值留给 `merge` 判 —— 在这里判死会连带丢掉本来能用的答案。"""
    assert ExamFix.from_raw({"type": " 单选 "}).type == "单选"
    assert ExamFix.from_raw({"type": ["single"]}).type is None


def test_exam_merge_keeps_answer_when_type_is_junk():
    draft = {"type": "single", "options": ["甲", "乙"], "answer": None,
             "score": None, "confidence": 0.55, "question": "题干", "number": "1"}
    merged, taken = merge(draft, {"type": "单选", "answer": "B", "score": "3分"})
    assert merged["answer"] == "B"       # 题型没采纳，答案照样采纳
    assert merged["score"] is None
    assert taken == ["answer"]


def test_exam_merge_never_touches_stem_or_number():
    draft = {"type": "single", "options": ["甲", "乙"], "answer": "A",
             "score": None, "confidence": 0.55, "question": "题干", "number": "7"}
    merged, taken = merge(draft, {"question": "另一道题", "number": "8", "answer": "B"})
    assert merged["question"] == "题干" and merged["number"] == "7"
    assert merged["answer"] == "A" and taken == []
