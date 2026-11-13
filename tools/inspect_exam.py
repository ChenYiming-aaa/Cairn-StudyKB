#!/usr/bin/env python3
"""看一份真试卷拆成什么样：题数、答案率、每题的题干与选项。

**为什么要有这个**：复核页只在装好的应用里看得到，改规则时想「这一改把哪几道题动了」
得有个命令行能一眼扫完。2026-11-13 就是靠它发现两个真缺陷 —— 中文句子里夹的代码被
全角化（`randint(1, 10)` → `randint(1， 10)`），以及题干跨页那半句被吞成选项的尾巴。

用法（在 backend 下，用它的 venv）：
    .venv/Scripts/python.exe ../tools/inspect_exam.py            # 全部样本
    .venv/Scripts/python.exe ../tools/inspect_exam.py python      # 只看一份

它**只走规则层**（不调模型、不碰库），所以和 `POST /api/exams/parse` 在 `use_llm=false`
时的结果一致；模型补出来的答案这里看不到，那是另一回事。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pypdfium2 as pdfium  # noqa: E402

from app.services.exam import audit, clean, parse  # noqa: E402


def pages_of(path: Path) -> list[dict]:
    """PDF → `[{page_no, text}]`，与 `pdf_pages.py` 交给解析层的形状一致。"""
    pdf = pdfium.PdfDocument(str(path))
    return [{"page_no": i + 1, "text": pdf[i].get_textpage().get_text_bounded()}
            for i in range(len(pdf))]


def main() -> int:
    topics = sys.argv[1:] or ["python", "math", "cet6"]
    missing = 0
    for topic in topics:
        path = ROOT / "samples" / topic / "exam.pdf"
        if not path.is_file():
            print(f"{topic}: 没有 {path.relative_to(ROOT)}（samples/ 不入库，干净机上正常）")
            missing += 1
            continue
        pages = pages_of(path)
        question_pages, answer_pages = parse.split_answer_zone(pages)
        answers, explanations, subjective = parse.read_answers(
            [line for zone in answer_pages for line in zone])
        cleaned = clean.clean_pages([p["lines"] for p in question_pages])
        blocks = parse.split_blocks([
            {"page_no": p["page_no"], "lines": lines}
            for p, lines in zip(question_pages, cleaned)
        ])
        drafts = [parse.to_draft(b, answers, explanations, subjective) for b in blocks]
        thin = [d for d in drafts if d["type"] == "single" and len(d["options"]) < 4]
        answered = sum(1 for d in drafts if d["answer"] is not None)
        flagged = sum(1 for d in drafts if audit.faults(d))
        print("=" * 72)
        print(f"{topic}: {len(pages)} 页（题面 {len(question_pages)} / 答案 {len(answer_pages)}）"
              f" → {len(drafts)} 题，答案 {answered}/{len(drafts)}")
        print(f"  选项不全的单选题：{len(thin)}；初审有疑问：{flagged}")
        for d in drafts:
            stem = d["question"].replace("\n", " ⏎ ")
            flag = ""
            if d["type"] == "single" and len(d["options"]) < 4:
                flag += f"  <<< 只有 {len(d['options'])} 个选项"
            if any(m in d["question"] for m in ("A.", "A．", "B.", "B．")):
                flag += "  <<< 题干里还留着选项字母"
            print(f"  #{d['number']:<4}[{d['type']:<7}] {stem}{flag}")
            for opt in d["options"]:
                print(f"         · {opt}")
            hits = audit.faults(d)
            if hits:
                # 误报看这里：初审报的每一条都会出现在复核页上，错一条用户就少信一分
                print("         ? " + "；".join(f"{h['code']} {h['message']}" for h in hits))
    return 2 if missing == len(topics) else 0


if __name__ == "__main__":
    raise SystemExit(main())
