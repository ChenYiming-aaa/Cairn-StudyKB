"""模型输出的入库形状（§4.2）：三个 agent 的 JSON，只认这三种模型。

为什么要有这一层：原来的容错散在三个调用点、全靠 `str(value or "")`。
代价是**不报错、但存进了一件不存在的东西** —— 模型把 `title` 写成对象时
`str({"a": 1})` 会变成标题 `{'a': 1}`；把 `tags` 写成一句话时它被静默丢掉却没有痕迹；
把 `answer` 写成 `{"B": true}` 时它变成一个字符串答案，判分永远对不上。
这些都不会抛异常，只会安安静静写进库，用户几天后才发现。

三条约定：

1. **形状只在这里定义**。调用点不再各写一段 `isinstance`，也不再各定一套上限。
2. **容错不降级成失败**。字段类型不对就丢这个字段、退回兜底值 —— 与改造前同一口径
   （真机见过模型把 tags 写成字符串、把选项压成一行、把答案写成 "B."）。所以这里的
   `from_raw()` 基本不会失败；真失败说明是代码 bug，不是模型作怪。
3. **失败走各调用点原有那条路**：整理重试一次再落 failed、出题只跳过这一题、
   试卷只丢模型给的改法（规则切出来的部分一律保留）。**不新增错误码，不新增文案。**

`from_raw()` 与 `model_validate()` 的分工：前者把「模型可能给的样子」压成模型能收的值，
后者只做最后一道形状检查。别把容错写进 validator 里 —— 那样一个坏字段会让整条输出作废，
而实际上坏一个字段只该丢那一个。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_TITLE = 20      # 标题上限 20 字，超了强截，不做「……」省略
MAX_TAGS = 6
MAX_KEY_POINTS = 8
# 题型与难度：元组是运行时用的（校验、筛选），Literal 是给模型字段用的。
# 两份必须一致 —— `tests/test_schemas.py` 用 get_args 比对，改一处忘了另一处会红。
TYPES = ("single", "multiple", "boolean", "short")
DIFFICULTIES = ("basic", "understand", "apply")
QuizType = Literal["single", "multiple", "boolean", "short"]
Difficulty = Literal["basic", "understand", "apply"]


# ── 容错原语 ────────────────────────────────────────────────

def text(value: Any) -> str:
    """只要字符串（数字转成文本）；dict / list / bool 一律当「没给」。

    `str({"a": 1})` 会得到 `"{'a': 1}"` —— 看着合法、实际是垃圾，而且没有任何地方会报错。
    这正是这一层要拦的东西，所以容器类型在这里直接丢，不做 stringify。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def items(value: Any) -> list:
    """只认 list；字符串 / 对象一律当空。

    模型把 `tags` 写成 `"复习, 考试"` 时原来也是当空处理（`_as_list`），
    这里保持同一口径：与其猜分隔符，不如让这次少几个标签 —— 猜错的代价是标签里出现怪词。
    """
    return value if isinstance(value, list) else []


def clean_title(value: Any, fallback: str) -> str:
    """把模型给的标题压成一行、去掉首尾的标点与书名号，并卡在 MAX_TITLE 字内。

    超长直接截断而不是加「…」——标题要进列表行和窗口标题，省略号只是把问题往后推。
    模型没给或给了空白时退回原标题，不让这次整理把标题变成空。
    """
    raw = " ".join(text(value).split())
    raw = raw.strip("#*·-—《》〈〉“”‘’\"'")
    raw = raw.strip("。．.！!？?；;，,：:")
    if not raw:
        return fallback
    return raw[:MAX_TITLE].strip()


# ── organizer ──────────────────────────────────────────────

class OrganizeResult(BaseModel):
    """整理结果（`organize.md` / `organize_exam.md` / `organize_image.md` 三份 prompt 共用）。

    `structured_note` 在 exam / image 上**必须是空串**：prompt 里已经说了不要输出，
    但模型偶尔还是会顺手写一篇 —— 由 `from_raw()` 按 kind 清掉，而不是指望 prompt 听话。
    """

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=MAX_TITLE)
    category: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    summary: str = ""
    key_points: list[str] = Field(default_factory=list, max_length=MAX_KEY_POINTS)
    structured_note: str = ""

    @classmethod
    def from_raw(cls, data: dict, fallback_title: str, kind: str = "material") -> "OrganizeResult":
        tags: list[str] = []
        for raw in items(data.get("tags")):
            tag = text(raw).strip().lstrip("#").strip()
            if tag and tag not in tags:
                tags.append(tag)

        points = [p for p in (text(x).strip() for x in items(data.get("key_points"))) if p]

        # 分类不设上限：真机上出现过 15 字的正经分类（课程全名），截断会把它变得没意义；
        # 只有「没给」才兜底
        category = text(data.get("category")).strip() or "未分类"

        return cls(
            title=clean_title(data.get("title"), fallback_title or "未命名"),
            category=category,
            tags=tags[:MAX_TAGS],
            summary=text(data.get("summary")).strip(),
            key_points=points[:MAX_KEY_POINTS],
            structured_note="" if kind != "material"
            else text(data.get("structured_note")).strip(),
        )


# ── quizzer ────────────────────────────────────────────────

class QuizItem(BaseModel):
    """一道题（`quiz.md`）。字段顺序与入库 payload 一致，`model_dump()` 直接进库。

    `answer` 的形态由题型决定（单选一个字母 / 多选字母数组 / 判断布尔 / 简答文本），
    这里只声明取值范围，具体归一见 `quizzer._answer()` —— 那是题型知识，不是形状。
    """

    model_config = ConfigDict(extra="ignore")

    type: QuizType
    question: str = Field(min_length=4)
    options: list[str] = Field(default_factory=list)
    answer: str | list[str] | bool | None = None
    explanation: str = Field(min_length=1)
    difficulty: Difficulty


# ── exam.parse 的补字段 ────────────────────────────────────

class ExamFix(BaseModel):
    """模型给试卷补的字段（`exam_parse.md`）。**只到这里为止，不碰题干与题号**。

    `type` 用宽松的 str：模型回「单选」这种中文值时，原来只丢 type、答案照样能用；
    做成 Literal 会让整个 fix 作废，反而丢掉本来能用的答案。
    """

    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    answer: Any = None
    score: float | None = None
    options: list[str] = Field(default_factory=list)
    confidence: float | None = None

    @classmethod
    def from_raw(cls, data: dict) -> "ExamFix":
        score = data.get("score")
        try:
            value = float(score)
        except (TypeError, ValueError):
            value = None
        # 分值上限 200：整卷 100 分是常态，出现 1000 只可能是模型把题号当分值
        score_ok = value if value is not None and 0 < value <= 200 else None

        confidence = data.get("confidence")
        try:
            conf = min(1.0, max(0.0, float(confidence)))
        except (TypeError, ValueError):
            conf = None

        qtype = data.get("type")
        return cls(
            type=qtype.strip() if isinstance(qtype, str) and qtype.strip() else None,
            answer=data.get("answer"),
            score=score_ok,
            # 选项带 "A." 前缀是常态，剥前缀留在 exam.prompt 里（它还要判「规则一个都没切出」）
            options=[o for o in (text(x).strip() for x in items(data.get("options"))) if o],
            confidence=conf,
        )
