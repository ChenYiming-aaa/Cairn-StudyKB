"""M10 验收脚本：试卷导入与校对。

用法：
    cd backend && uv run python scripts/verify_m10.py
    cd backend && uv run python scripts/verify_m10.py --only clean      # 只跑规则清洗
    cd backend && uv run python scripts/verify_m10.py --only parse      # 只跑解析
    cd backend && uv run python scripts/verify_m10.py --only commit     # 只跑提交
    cd backend && uv run python scripts/verify_m10.py --only proofread  # 只跑校对
    cd backend && uv run python scripts/verify_m10.py --only paper      # 只跑按卷练习
    cd backend && uv run python scripts/verify_m10.py --only import     # 只跑批量导入
    cd backend && uv run python scripts/verify_m10.py --only audit      # 只跑题目初审

退出码：0 全绿 / 1 有用例失败 / 2 环境不满足

覆盖分组：
  §clean   T10.1 五个纯函数。每条都带「不该改」的用例 —— 误改比认错字更难发现
  §parse   T10.2 规则切分：题数、答案抽取率、答案区锚点、题型推断、跳号检测
  §commit  T10.3 一次事务写入、重复提交按题号认身份、练过的题删不掉但摘出卷子、
           答案与题型不自洽降级
  §proofread T10.4 三道闸门（结构化 diff / 编辑距离 / 原文不覆盖）+ 答案行守卫
  §paper   T10.5 按原卷题号排序（TEXT 题号直排会把第 10 题排到第 2 题前）、只取导入题
  §import  T10.6 只列不导、自然序、老格式给替代、逐个失败不影响其余、上限 100
  §audit   T10.9 初审：规则体检不误报、缺答案只报不猜、模型改法的三道守卫
           （动数字 / 带题号 / 换成另一句）、分批、模型挂了降级不 500

**不联网、不调 LLM**：模型那两处（`prompt.refine` / `proofread.review_page`）全部打桩，
用固定返回验守卫。判据在脚本里独立重算（不 import 被测函数的判定），
自己调自己不算验。

**缺样本是 SKIP 不是 FAIL**：`samples/` 不入库，干净机上本来就没有。
真样本那一段走 `skip()`，规则部分用内联文本照跑。
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SAMPLES = ROOT / "samples"
TMP = Path(tempfile.mkdtemp(prefix="cairn-verify-m10-"))
(TMP / ".env").write_text("LLM_API_KEY=sk-verify-m10-not-a-real-key\n", encoding="utf-8")
os.environ["DATA_DIR"] = str(TMP)            # 必须早于 import app
os.environ["VECTOR_ENABLED"] = "0"
os.environ["CAIRN_ENV_STRICT"] = "1"
os.environ.setdefault("LOG_LEVEL", "WARNING")

sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient      # noqa: E402

from app.db.conn import get_conn               # noqa: E402
from app.db.migrate import init_db             # noqa: E402
from app.main import app                       # noqa: E402
from app.services.exam import audit, clean, parse, proofread   # noqa: E402

RESULTS: list[tuple[bool, str, str]] = []
WARNINGS: list[str] = []
_seq = itertools.count(1)

# 一份最小但真实的卷子：题干、四个选项、答案速查表、一道主观题。
# 不用 samples/ 是为了让这一段在干净机上也能跑（样本那段另算）。
PAPER = """二级 Python 模拟试卷
一、单项选择题（每小题 2 分）
1. 表达式 3**2//2 的值是
A. 4
B. 5
C. 6
D. 7
2. 已知 s = "Python", 表达式 s[1:4] 的结果是
A. Pyt
B. yth
C. tho
D. hon
3. 下列各项中, 属于不可变类型的是
A. list
B. dict
C. tuple
D. set
4. 表达式 round(2.5) 的结果是
A. 2
B. 3
C. 2.5
D. 4
5. 关于列表 append 方法, 说法正确的是
A. 返回新列表
B. 把整个对象作为单个元素追加
C. 只能追加数字
D. 会去重
二、基本操作题
6. 编写程序, 输出 1 到 10 的和
参考答案
一、客观题答案
1. A 2. B 3. C 4. A 5. B
二、主观题
6. print(sum(range(1, 11)))
"""


def skip(name: str, detail: str = "") -> None:
    WARNINGS.append(name)
    print(f"  SKIP  {name}" + (f"   → {detail}" if detail else ""))


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((bool(ok), name, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   → {detail}" if detail else ""))
    return bool(ok)


def make_item(pages: list[str], *, title: str = "模拟试卷", kind: str = "material") -> tuple[int, int]:
    """造一条内容 + 一个原件 + 若干页识别文本，返回 (item_id, file_id)。"""
    tag = next(_seq)
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO knowledge_item (title, raw_content, content_hash, source_type,
                                               status, created_at, updated_at, kind)
                   VALUES (?, ?, ?, 'file', 'pending', '2026-11-13T00:00:00', '2026-11-13T00:00:00', ?)""",
                (title, "[文件] exam.pdf", f"verify-m10-{tag}", kind),
            )
            item_id = int(cur.lastrowid)
            cur = conn.execute(
                """INSERT INTO item_file (item_id, role, original_name, ext, mime, size, sha256,
                                          stored_path, page_count, has_text_layer, ocr_status)
                   VALUES (?, 'main', 'exam.pdf', 'pdf', 'application/pdf', 1024, ?,
                           ?, ?, 0, 'done')""",
                (item_id, f"sha-{tag}", f"files/{item_id}/exam.pdf", len(pages)),
            )
            file_id = int(cur.lastrowid)
            for page_no, text in enumerate(pages, 1):
                conn.execute(
                    "INSERT INTO item_page (item_id, file_id, page_no, text, source, avg_conf)"
                    " VALUES (?, ?, ?, ?, 'ocr', 0.95)",
                    (item_id, file_id, page_no, text),
                )
    finally:
        conn.close()
    return item_id, file_id


def drafts_of(pages: list[str]) -> tuple[list[dict], dict]:
    """内联文本 → 草稿与统计（走真实的 split_answer_zone / read_answers / split_blocks）。"""
    rows = [{"page_no": i, "text": t} for i, t in enumerate(pages, 1)]
    question_pages, answer_pages = parse.split_answer_zone(rows)
    answers, explanations, subjective = parse.read_answers(
        [line for zone in answer_pages for line in zone])
    cleaned = clean.clean_pages([p["lines"] for p in question_pages])
    blocks = parse.split_blocks(
        [{"page_no": p["page_no"], "lines": lines}
         for p, lines in zip(question_pages, cleaned)])
    drafts = [parse.to_draft(b, answers, explanations, subjective) for b in blocks]
    return drafts, {"answers": answers, "subjective": subjective, "blocks": blocks}


# ── §clean T10.1 ───────────────────────────────────────────
def group_clean() -> None:
    # 页眉页脚：整页重复 + 位于页边才删；正文里偶尔出现一次的同名行不动
    pages = [
        ["二级 Python 模拟试卷（一）", "一、单项选择题", "1. 表达式 3**2//2 的值是", "A. 5"],
        ["二级 Python 模拟试卷（一）", "2. 已知 s = 'Python'", "A. Pyt", "— 2 —"],
        ["二级 Python 模拟试卷（一）", "第 3 页", "3. round(2.5)", "A. 2"],
    ]
    kept = clean.drop_headers(pages)
    flat = [line for page in kept for line in page]
    check("页眉只在页边出现时被删", flat.count("二级 Python 模拟试卷（一）") == 0, str(flat[:4]))
    check("页码行被删（— 2 — / 第 3 页）",
          not any("2 —" in line or "第 3 页" in line for line in flat), str(flat))
    check("正文行一行不少", sum(len(p) for p in kept) == 7, str([len(p) for p in kept]))

    check("折行合并：行尾无标点且下一行不是题号",
          clean.merge_broken(["1. 下列各项中，属于", "不可变类型的是"]) == ["1. 下列各项中，属于不可变类型的是"],
          str(clean.merge_broken(["1. 下列各项中，属于", "不可变类型的是"])))
    check("下一行是题号就不合（那可能是折行甩出来的新题号）",
          clean.merge_broken(["1. 题干前半", "2. 下一题"]) == ["1. 题干前半", "2. 下一题"],
          str(clean.merge_broken(["1. 题干前半", "2. 下一题"])))
    check("选项行不合并",
          clean.merge_broken(["A. list", "B. dict"]) == ["A. list", "B. dict"])
    check("标题行不合并",
          clean.merge_broken(["一、单项选择题", "1. 题干"]) == ["一、单项选择题", "1. 题干"])

    check("中文语境的 ASCII 逗号改全角",
          clean.normalize_width("下列各项中, 属于不可变") == "下列各项中，属于不可变",
          clean.normalize_width("下列各项中, 属于不可变"))
    code = "a = [1,2,3]; a.append([4,5])"
    check("代码行零改动", clean.normalize_width(code) == code, clean.normalize_width(code))
    english = 'He said, "yes." Then left.'
    check("英文段落零改动", clean.normalize_width(english) == english, clean.normalize_width(english))
    check("小数点与版本号不当标点",
          clean.normalize_width("Python 3.11 的 3.14 是 pi") == "Python 3.11 的 3.14 是 pi")

    # 「中文句子里的代码」：整行含中文，但那一小段是代码/算式，标点一个都不许动。
    # 2026-11-13 真样本实测踩到：`randint(1, 10)` 被改成 `randint(1， 10)`，
    # 用户照着背的就是另一段代码了（答案本身是错的）。
    mixed = [
        "random.randint(1, 10) 生成的随机整数范围是",
        "已知 d = {'a': 1}，表达式 d.get('b', 0) 的值是",
        "for i in range(2, 10, 3) 循环体执行的次数是",
        "函数 f(x) = ln(x - 1) + √(4 - x²) 的定义域是",
        "计算定积分 ∫[0, π/2] sin²x dx",
    ]
    for line in mixed:
        check(f"混排行里的代码不失真：{line[:16]}…", clean.normalize_width(line) == line,
              clean.normalize_width(line))
    check("但同一个句子里的中文标点照旧改全角",
          clean.normalize_width("已知 d = {'a': 1}, 表达式 x 的值") == "已知 d = {'a': 1}，表达式 x 的值",
          clean.normalize_width("已知 d = {'a': 1}, 表达式 x 的值"))

    # 跨页断开的那一刀：题干最后半句落到下一页，不能被当成选项的续行
    spread = clean.clean_pages([
        ["一、单选题", "1. 下列关于 Python 的说法中正确"],
        ["的是", "A. 甲", "B. 乙", "C. 丙", "D. 丁"],
    ])
    check("跨页断行接回同一行",
          spread[0][-1] == "1. 下列关于 Python 的说法中正确的是" and spread[1][0] == "A. 甲",
          str(spread))
    keep = clean.clean_pages([["1. 题干", "A. 甲", "B. 乙"], ["的是", "C. 丙"]])
    check("上一页收尾是选项行就不接（否则两个选项会并成一个）",
          keep[0][-1] == "B. 乙" and keep[1][0] == "的是", str(keep))
    head = clean.clean_pages([["一、单项选择题"], ["本卷共 10 题"]])
    check("上一页收尾是大题标题也不接",
          head[0][-1] == "一、单项选择题" and head[1][0] == "本卷共 10 题", str(head))

    check("题号归一 12、", clean.normalize_number("12、题干")["num"] == "12",
          str(clean.normalize_number("12、题干")))
    check("题号归一 第1题", clean.normalize_number("第1题 题干")["num"] == "1")
    check("题号归一 （3）", clean.normalize_number("（3）题干")["num"] == "3")
    check("大题标题 一、 单独一类", clean.normalize_number("一、单项选择题")["kind"] == "cjk")
    check("小数不当题号", clean.normalize_number("3.14 是 pi") is None,
          str(clean.normalize_number("3.14 是 pi")))
    check("选项行不当题号", clean.normalize_number("A. 选项") is None)

    opts, complete = clean.align_options(["A. list", "B. dict", "C. tuple", "D. set"])
    check("选项字母剥掉、只留文本", opts == ["list", "dict", "tuple", "set"] and complete, str(opts))
    spread, spread_ok = clean.align_options(["A. list  B. dict  C. tuple  D. set"])
    check("行内并排的四个选项切开", spread == ["list", "dict", "tuple", "set"] and spread_ok, str(spread))
    # 真样本里更常见的是**单空格**：见一个空格就切会把正文腰斩，所以只在「≥3 段且字母递增」时切
    one_space, one_ok = clean.align_options(["A. list B. dict C. tuple D. set"])
    check("单空格并排的四个选项也切开",
          one_space == ["list", "dict", "tuple", "set"] and one_ok, str(one_space))
    hanzi, hanzi_ok = clean.align_options(["A.正弦 B.余弦 C.正切 D.余切"])
    check("中文选项单空格并排也切得开",
          hanzi == ["正弦", "余弦", "正切", "余切"] and hanzi_ok, str(hanzi))
    trap, _trap_ok = clean.align_options(["A. 见 B 项的做法"])
    check("正文里顺带出现 B 项不腰斩", trap == ["见 B 项的做法"], str(trap))
    two, two_ok = clean.align_options(["A. x = 1  B. y = 2"], expected=2)
    check("两个选项并排（判断题）也算齐", two == ["x = 1", "y = 2"] and two_ok, str(two))
    three, three_ok = clean.align_options(["A. list", "B. dict", "C. tuple"])
    check("只有三个选项 → 标不全", len(three) == 3 and not three_ok, str(three))
    judge, judge_ok = clean.align_options(["正确", "错误"], expected=2)
    check("判断题两个无字母选项也算齐", judge == ["正确", "错误"] and judge_ok, str(judge))


# ── §parse T10.2 ───────────────────────────────────────────
def group_parse() -> None:
    drafts, meta = drafts_of([PAPER])
    check("题数 = 6（5 选择 + 1 主观）", len(drafts) == 6, str([d["number"] for d in drafts]))
    with_answer = sum(1 for d in drafts if d["answer"] is not None)
    check("答案抽取 6/6", with_answer == 6, f"{with_answer}/6")
    check("单选题型正确", sum(1 for d in drafts if d["type"] == "single") == 5,
          str([d["type"] for d in drafts]))
    check("主观题题型正确", drafts[-1]["type"] == "short", drafts[-1]["type"])
    check("选项齐 4 个", all(len(d["options"]) == 4 for d in drafts[:5]),
          str([len(d["options"]) for d in drafts[:5]]))
    check("答案 A/B/C/A/B 逐题对上",
          [d["answer"] for d in drafts[:5]] == ["A", "B", "C", "A", "B"],
          str([d["answer"] for d in drafts[:5]]))
    check("主观题答案取「参考答案」区那段代码",
          (drafts[-1]["answer"] or "").startswith("print(sum("), str(drafts[-1]["answer"]))
    check("章节与分值进了草稿",
          drafts[0]["group"] and drafts[0]["score"] == 2.0,
          f"group={drafts[0]['group']} score={drafts[0]['score']}")

    # 答案区锚点必须是整行标题：题干里的「正确答案是」不能当入口
    tricky = [
        {"page_no": 1, "text": "1. 下列哪项是正确答案\nA. 甲\nB. 乙\nC. 丙\nD. 丁\n2. 第二题\nA. 甲\nB. 乙\nC. 丙\nD. 丁"},
    ]
    qpages, apages = parse.split_answer_zone(tricky)
    check("题干里的「正确答案」不会被当成答案区入口",
          len(qpages) == 1 and len(qpages[0]["lines"]) == 10 and not apages,
          f"题目区 {len(qpages[0]['lines']) if qpages else 0} 行，答案区 {len(apages)} 页")

    gaps = parse.find_gaps([
        {"number": "1", "group": "一、单选"}, {"number": "2", "group": "一、单选"},
        {"number": "4", "group": "一、单选"},
    ])
    check("同章节跳号被报出来", gaps == [{"section": "一、单选", "missing": ["3"]}], str(gaps))
    gaps2 = parse.find_gaps([
        {"number": "1", "group": "一、单选"}, {"number": "2", "group": "一、单选"},
        {"number": "1", "group": "二、操作"}, {"number": "2", "group": "二、操作"},
    ])
    check("换章节重新编号不算跳号", gaps2 == [], str(gaps2))

    client = TestClient(app)
    item_id, file_id = make_item(["这张图里没有题号，只有一段说明文字。\n就这样。"])
    r = client.post("/api/exams/parse", json={"file_id": file_id, "use_llm": False})
    check("0 题 → 422 EXAM_NO_QUESTIONS",
          r.status_code == 422 and r.json()["error"]["code"] == "EXAM_NO_QUESTIONS", r.text[:120])
    r2 = client.post("/api/exams/parse", json={"file_id": 999999, "use_llm": False})
    check("原件不存在 → 404", r2.status_code == 404, r2.text[:120])
    check("解析不落库（题目表还是 0 条）",
          _count("SELECT COUNT(*) FROM question WHERE item_id=?", (item_id,)) == 0)
    check("解析不把内容定性成试卷", _item_field(item_id, "kind") == "material")

    # 校对过的页文本要进解析。写了 `text_reviewed` 却只读 `text`，
    # 用户校对完再导一遍，题目还是认错的原样 —— 那校对等于没做（2026-11-13 修）
    item2, file2 = make_item(["1. 表达试 3**2//2 的值是\nA. 4\nB. 5\nC. 6\nD. 7"])
    conn = get_conn()
    try:
        with conn:
            conn.execute("UPDATE item_page SET text_reviewed=? WHERE file_id=? AND page_no=1",
                         ("1. 表达式 3**2//2 的值是\nA. 4\nB. 5\nC. 6\nD. 7", file2))
    finally:
        conn.close()
    polished = parse.parse(file2, use_llm=False)
    check("解析读校对后的文本（不是只读识别原文）",
          polished["drafts"][0]["question"] == "表达式 3**2//2 的值是",
          polished["drafts"][0]["question"])
    check("校对后原文照样留着", "表达试" in (_page_field(file2, 1, "text") or ""),
          (_page_field(file2, 1, "text") or "")[:16])

    # 真样本：题数要与 _check.json 记的题号数对上
    check_file = SAMPLES / "_check.json"
    if not check_file.is_file():
        skip("§parse 真样本（缺 samples/_check.json）")
        return
    try:
        import pypdfium2 as pdfium
    except ImportError:
        skip("§parse 真样本（没装 pypdfium2）")
        return
    expect = json.loads(check_file.read_text(encoding="utf-8"))
    for topic in ("python", "math"):
        pdf_path = SAMPLES / topic / "exam.pdf"
        if not pdf_path.is_file():
            skip(f"§parse 真样本 {topic}（缺 {pdf_path.name}）")
            continue
        pdf = pdfium.PdfDocument(str(pdf_path))
        pages = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
        drafts, _meta = drafts_of(pages)
        want = int(expect.get(topic, {}).get("exam", {}).get("question_marks") or 0)
        check(f"真样本 {topic} 题数 {len(drafts)} = 卷面 {want}",
              bool(want) and len(drafts) == want, f"{len(drafts)} vs {want}")
        if topic == "python":
            # 这句最容易被「全半角归一」改坏：中文里夹着 `randint(1, 10)`，
            # 改成「1，10」就不是同一段代码，用户照着背进考场是错的
            hits = [d["question"] for d in drafts if "randint" in (d["question"] or "")]
            check("真样本里的代码没被全角化（randint(1, 10) 原样）",
                  bool(hits) and "randint(1, 10)" in hits[0],
                  hits[0][:70] if hits else "没找到那道题")


# ── §commit T10.3 ──────────────────────────────────────────
def group_commit() -> None:
    client = TestClient(app)
    drafts, _meta = drafts_of([PAPER])
    item_id, file_id = make_item([PAPER], title="提交用试卷")

    r = client.post("/api/exams/commit", json={"file_id": file_id, "drafts": drafts})
    body = r.json()
    check("提交返回 201", r.status_code == 201, r.text[:150])
    check("写入条数 = 草稿数", body["imported"] == len(drafts), str(body["imported"]))
    check("内容被定性成 exam", _item_field(item_id, "kind") == "exam")
    check("内容状态置 ready（能练了）", _item_field(item_id, "status") == "ready")
    check("题目全部 origin=imported",
          _count("SELECT COUNT(*) FROM question WHERE item_id=? AND origin='imported'", (item_id,)) == len(drafts))
    check("题号映射一次给全", len(body["number_map"]) == len(drafts), str(body["number_map"]))

    first_ids = dict(_qids(item_id, origin="imported"))
    # 复核页最常见的改动：改答案 + 改题干错字。题号不变 → 必须原地改，不能多出一道题
    edited = [dict(d) for d in drafts]
    edited[0]["answer"] = "D"
    edited[0]["question"] = edited[0]["question"] + "（补的尾巴）"
    r2 = client.post("/api/exams/commit", json={"file_id": file_id, "drafts": edited})
    check("二次提交后题数不变", r2.json()["imported"] == len(drafts), str(r2.json()["imported"]))
    check("二次提交按题号认身份（题数没涨）",
          _count("SELECT COUNT(*) FROM question WHERE item_id=?", (item_id,)) == len(drafts))
    after = dict(_qids(item_id, origin="imported"))
    check("改题干不会换出一行新题（id 不变）", after.get("1") == first_ids.get("1"),
          f"{first_ids.get('1')} → {after.get('1')}")
    q1 = _question(after.get("1"))
    check("改后的答案生效", q1["answer"] == "D", str(q1["answer"]))
    check("改后的题干生效", q1["question"].endswith("（补的尾巴）"), q1["question"][-12:])

    # 删题：没练过的真删；练过的留在库里但摘出卷子
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO quiz_attempt (question_id, user_answer, is_correct, created_at)"
                " VALUES (?, 'A', 0, '2026-11-13T00:00:00')", (after["1"],))
    finally:
        conn.close()
    fewer = [d for d in edited if d["number"] not in ("1", "2")]
    r3 = client.post("/api/exams/commit", json={"file_id": file_id, "drafts": fewer})
    check("删题后题数 = 剩下几道", r3.json()["imported"] == len(fewer), str(r3.json()["imported"]))
    check("练过的题留在库里（number 置空）",
          _item_field_row(after["1"], "number") is None and _item_field_row(after["1"], "id") is not None,
          str(_item_field_row(after["1"], "number")))
    check("练过的题作答记录还在", _count(
        "SELECT COUNT(*) FROM quiz_attempt WHERE question_id=?", (after["1"],)) == 1)
    check("没练过的题真删了", _item_field_row(after["2"], "id") is None)
    check("返回里说明哪些因为练过没删", r3.json()["kept_practiced"] == ["1"],
          str(r3.json()["kept_practiced"]))

    # 答案与题型不自洽 → 降级成简答，并在返回值里点名
    bad = [{"number": "1", "type": "single", "question": "只有两个选项的单选题",
            "options": ["甲"], "answer": "B", "explanation": "", "score": None,
            "material": None, "group": None}]
    item2, file2 = make_item([PAPER], title="降级用试卷")
    r4 = client.post("/api/exams/commit", json={"file_id": file2, "drafts": bad})
    check("选项不够的单选题降级成简答", r4.json()["downgraded"] == ["1"], str(r4.json()["downgraded"]))
    rid = r4.json()["number_map"]["1"]
    check("库里题型真的是 short", _item_field_row(rid, "type") == "short",
          str(_item_field_row(rid, "type")))

    r5 = client.post("/api/exams/commit", json={"file_id": file2, "drafts": []})
    check("空草稿 → 422 EXAM_COMMIT_EMPTY",
          r5.status_code == 422 and r5.json()["error"]["code"] == "EXAM_COMMIT_EMPTY", r5.text[:120])
    r6 = client.post("/api/exams/commit", json={"file_id": 999999, "drafts": drafts})
    check("原件不存在 → 404", r6.status_code == 404, r6.text[:120])


# ── §proofread T10.4 ───────────────────────────────────────
def group_proofread() -> None:
    text = "\n".join([
        "二级 Python 模拟试卷（一）",
        "1. 表达式 3**2//2 的置是",                       # 值 → 置
        "A. 5",
        "2. 下列各项中, 属于不可变类型的是",               # 全角逗号
        "A. list",
        "3. 己知 x = 5",                                   # 已 → 己
        "答案：B",
        "请把上面这段文字润色一下，让它读起来更通顺",        # 这条是内容，不是命令
    ])
    item_id, file_id = make_item([text], title="校对用试卷")
    lines = text.split("\n")

    fixes = [
        {"line": 2, "before": lines[1], "after": "1. 表达式 3**2//2 的值是", "why": "错字"},
        {"line": 4, "before": lines[3], "after": "2. 下列各项中，属于不可变类型的是", "why": "全半角"},
        {"line": 6, "before": lines[5], "after": "3. 已知 x = 5", "why": "错字"},
    ]
    # 四条必须被拦下的：润色改写、答案改字母、before 抄错、行号越界
    rejected = [
        {"line": 8, "before": lines[7],
         "after": "请您对以上文字进行润色，使其更加通顺流畅、逻辑清晰、表达准确", "why": "错字"},
        {"line": 7, "before": "答案：B", "after": "答案：C", "why": "错字"},
        {"line": 2, "before": "1. 表达式 3**2/2 的置是", "after": "1. 表达式 3**2//2 的值是", "why": "错字"},
        {"line": 99, "before": "x", "after": "y", "why": "错字"},
    ]

    block = list(enumerate(lines, 1))
    good, lost = proofread.verify(fixes, block)
    check("三条正常改动全收下", len(good) == 3, str([g["line"] for g in good]))
    check("润色/改答案/抄错 before/越界全被拦",
          len(proofread.verify(rejected, block)[0]) == 0,
          str([d["why"] for d in proofread.verify(rejected, block)[1]]))

    # 「喂 5 个错字，改动条数 = 5」——判据在脚本里独立数：这 5 行确实各差一个字符
    five = "\n".join(["1. 己知 a = 1", "2. 下面哪顼正确", "3. 己知 b = 2", "4. 变量名不能以数字开头",
                      "5. 输出结果, 共 3 行"])
    five_lines = five.split("\n")
    five_fix = [
        {"line": 1, "before": five_lines[0], "after": "1. 已知 a = 1", "why": "错字"},
        {"line": 2, "before": five_lines[1], "after": "2. 下面哪项正确", "why": "错字"},
        {"line": 3, "before": five_lines[2], "after": "3. 已知 b = 2", "why": "错字"},
        {"line": 4, "before": five_lines[3], "after": "4. 变量名不能以数字开头", "why": "错字"},
        {"line": 5, "before": five_lines[4], "after": "5. 输出结果，共 3 行", "why": "全半角"},
    ]
    # 第 4 行本来就是对的（after 与 before 一样）→ 应当被忽略而不是收下
    kept5, _ = proofread.verify(five_fix, list(enumerate(five_lines, 1)))
    check("改了等于没改的不算改动（5 条里收 4 条）", len(kept5) == 4, str(len(kept5)))

    # 端到端：打桩模型 → 真实落库路径
    calls = {"n": 0}

    def fake_chat(messages, **kwargs):     # noqa: ARG001
        calls["n"] += 1
        return json.dumps({"changes": fixes}, ensure_ascii=False)

    real_chat = proofread.llm.chat
    proofread.llm.chat = fake_chat
    try:
        client = TestClient(app)
        r = client.post("/api/exams/proofread", json={"file_id": file_id, "use_llm": True})
        data = r.json()
        check("校对端点跑通（纯计算不落库）", r.status_code == 200 and data["changed"] == 3,
              f"{r.status_code} changed={data.get('changed')}")
        check("识别行数如实回报", data["total_lines"] == len(lines), str(data["total_lines"]))
        check("校对不写 text_reviewed", _page_field(file_id, 1, "text_reviewed") is None)

        accepted = [{"page_no": 1, "line": c["line"], "after": c["after"]}
                    for c in data["pages"][0]["changes"][:2]]
        r2 = client.post("/api/exams/proofread/apply",
                         json={"file_id": file_id, "accepted": accepted})
        check("只落用户接受的那两条", r2.json()["applied"] == 2, str(r2.json()["applied"]))
        reviewed = _page_field(file_id, 1, "text_reviewed")
        check("原文 text 没被覆盖", _page_field(file_id, 1, "text") == text)
        check("改后的那一行进了 text_reviewed",
              reviewed and reviewed.split("\n")[1] == "1. 表达式 3**2//2 的值是",
              (reviewed or "").split("\n")[1] if reviewed else "None")
        check("没接受的那条没进（第 3 行还是「己知」）",
              reviewed and reviewed.split("\n")[5] == "3. 己知 x = 5",
              (reviewed or "").split("\n")[5] if reviewed else "None")

        # 前端传来的清单被篡改：落库前必须再校验一遍
        bad = [{"page_no": 1, "line": 2,
                "after": "1. 这是一段完全不同的很长很长的替换内容，用来确认守卫在服务端也生效"}]
        r3 = client.post("/api/exams/proofread/apply", json={"file_id": file_id, "accepted": bad})
        check("落库前重建 + 守卫（篡改被拒）", r3.json()["applied"] == 0 and r3.json()["dropped"],
              str(r3.json()["dropped"]))

        # apply 是「以这次清单为准的全量重建」：上面那次被拒的清单等于「什么都不接受」，
        # 所以这里再来一次正常的，验证重建而不是在旧结果上打补丁
        client.post("/api/exams/proofread/apply", json={"file_id": file_id, "accepted": accepted})
        r4 = client.delete(f"/api/exams/proofread/{file_id}")
        check("回退清掉 text_reviewed", r4.json()["reverted"] == 1
              and _page_field(file_id, 1, "text_reviewed") is None, str(r4.json()))

        # 模型全挂：只是没改动，不能 500
        def boom(messages, **kwargs):      # noqa: ARG001
            raise proofread.llm.LLMError("LLM_HTTP_ERROR", "连不上", "")

        proofread.llm.chat = boom
        r5 = client.post("/api/exams/proofread", json={"file_id": file_id, "use_llm": True})
        check("模型不可用时降级成 0 改动（不 500）",
              r5.status_code == 200 and r5.json()["changed"] == 0, r5.text[:120])
    finally:
        proofread.llm.chat = real_chat

    check("分块 ≤2000 字且按行切",
          all(sum(len(line) + 8 for _, line in b) <= 2000
              for b in proofread.split_blocks([f"第{i}行" + "字" * 40 for i in range(1, 101)])),
          str(len(proofread.split_blocks([f"第{i}行" + "字" * 40 for i in range(1, 101)]))))


# ── §paper T10.5 ───────────────────────────────────────────
def group_paper() -> None:
    client = TestClient(app)
    drafts, _meta = drafts_of([PAPER])
    item_id, file_id = make_item([PAPER], title="按卷练用试卷")
    client.post("/api/exams/commit", json={"file_id": file_id, "drafts": drafts})

    r = client.get(f"/api/quiz/paper/{item_id}")
    body = r.json()
    numbers = [q["number"] for q in body["questions"]]
    check("按卷接口返回全部题", r.status_code == 200 and len(numbers) == len(drafts), str(numbers))
    check("题号是有序的（1..6）", numbers == [str(i) for i in range(1, len(drafts) + 1)], str(numbers))
    check("每道题带 payload（分值/材料/题组在里面）",
          all(isinstance(q.get("payload"), dict) for q in body["questions"]))
    check("题目带题干与答案",
          all(q.get("question") for q in body["questions"]))

    # 题号 10 必须排在 2 后面：TEXT 直接 ORDER BY 会排成 1,10,11,2
    many = [{"number": str(i), "type": "short", "question": f"第 {i} 题",
             "options": [], "answer": "略", "explanation": "", "score": None,
             "material": None, "group": None} for i in range(1, 13)]
    item2, file2 = make_item([PAPER], title="排序用试卷")
    client.post("/api/exams/commit", json={"file_id": file2, "drafts": many})
    got = [q["number"] for q in client.get(f"/api/quiz/paper/{item2}").json()["questions"]]
    check("12 道题的题号按数值排（10 在 2 后面、11/12 在末尾）",
          got == [str(i) for i in range(1, 13)], str(got))

    # 模型出的题不混进「按卷练」
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                """INSERT INTO question (item_id, type, difficulty, payload, fingerprint,
                                         origin, number, created_at)
                   VALUES (?, 'single', 'understand', ?, 'verify-m10-ai-1', 'ai', '99',
                           '2026-11-13T00:00:00')""",
                (item_id, json.dumps({"question": "模型补的题", "options": ["甲", "乙"],
                                      "answer": "A"}, ensure_ascii=False)),
            )
    finally:
        conn.close()
    got2 = [q["number"] for q in client.get(f"/api/quiz/paper/{item_id}").json()["questions"]]
    check("按卷练只取导入题（origin=ai 的不混进来）", "99" not in got2, str(got2))

    empty_item, _ = make_item([PAPER], title="没有题的空卷")
    r3 = client.get(f"/api/quiz/paper/{empty_item}")
    check("没有题的空卷 → 404", r3.status_code == 404, r3.text[:120])

    listed = client.get("/api/knowledge", params={"status": "ready"}).json()["items"]
    check("列表项带 kind（练习页据此分「按卷练」）",
          any(it.get("kind") == "exam" for it in listed), str([(i["title"], i.get("kind")) for i in listed][:3]))


# ── §import T10.6 ──────────────────────────────────────────
def group_import() -> None:
    client = TestClient(app)
    folder = TMP / "批量"
    folder.mkdir(exist_ok=True)
    (folder / "第2题.txt").write_text("二", encoding="utf-8")
    (folder / "第10题.txt").write_text("十", encoding="utf-8")
    (folder / "旧格式.doc").write_text("x", encoding="utf-8")
    (folder / ".隐藏.txt").write_text("x", encoding="utf-8")
    sub = folder / "子目录"
    sub.mkdir(exist_ok=True)
    (sub / "不该进来.txt").write_text("x", encoding="utf-8")

    r = client.post("/api/import/scan", json={"paths": [str(folder)]})
    data = r.json()
    names = [f["name"] for f in data["files"]]
    check("扫描列出 3 个文件（隐藏文件与子目录不进）", data["total"] == 3, str(names))
    check("自然序：第2题 在 第10题 前面",
          names.index("第2题.txt") < names.index("第10题.txt"), str(names))
    check("老格式标不可导并给替代",
          next(f for f in data["files"] if f["name"] == "旧格式.doc")["supported"] is False
          and "docx" in next(f for f in data["files"] if f["name"] == "旧格式.doc")["reason"],
          str([f for f in data["files"] if f["name"] == "旧格式.doc"]))
    check("可导 2 个（老格式那个不算）", data["supported"] == 2, str(data["supported"]))
    check("扫描不落库（知识库没有新内容）",
          _count("SELECT COUNT(*) FROM knowledge_item WHERE title LIKE '第%题'") == 0)

    paths = [f["path"] for f in data["files"] if f["supported"]]
    r2 = client.post("/api/import/run", json={"paths": paths})
    run = r2.json()
    check("批量导入 2 个全部成功", run["added_count"] == 2 and run["failed_count"] == 0, str(run)[:160])
    check("导入后进识别队列（ocr_status 不是 none）",
          all(a["ocr_status"] in ("running", "pending", "done") for a in run["added"]),
          str([a["ocr_status"] for a in run["added"]]))

    r3 = client.post("/api/import/run", json={"paths": paths})
    check("同样的文件再导一次 → 全部判重复",
          r3.json()["added_count"] == 0 and r3.json()["skipped_count"] == 2, str(r3.json())[:160])

    missing = folder / "没有这个.txt"
    r4 = client.post("/api/import/run", json={"paths": [str(missing)] + paths[:1]})
    body = r4.json()
    check("一个失败不影响其余（1 失败 + 1 重复）",
          body["failed_count"] == 1 and body["skipped_count"] == 1
          and len(body["failed"]) == 1, str(body)[:160])
    check("失败项带原因", bool(body["failed"][0]["reason"]), body["failed"][0]["reason"])

    check("空清单 → 422",
          client.post("/api/import/run", json={"paths": []}).status_code == 422)
    too_many = client.post("/api/import/run", json={"paths": paths * 60})
    check("超过 100 个 → 422 IMPORT_TOO_MANY",
          too_many.status_code == 422 and too_many.json()["error"]["code"] == "IMPORT_TOO_MANY",
          too_many.text[:120])

    scan_missing = client.post("/api/import/scan", json={"paths": [str(TMP / "不存在的目录")]})
    check("路径不存在时扫描仍返回 200 且说明原因",
          scan_missing.status_code == 200
          and scan_missing.json()["files"][0]["reason"] == "这个路径不在了",
          scan_missing.text[:120])

    # 上限：造 120 个文件，扫描只列前 100 并标记截断
    big = TMP / "超过上限"
    big.mkdir(exist_ok=True)
    for i in range(120):
        (big / f"f{i:03d}.txt").write_text("x", encoding="utf-8")
    capped = client.post("/api/import/scan", json={"paths": [str(big)]}).json()
    check("超过上限只列 100 并标 truncated",
          capped["total"] == 100 and capped["truncated"] is True, str(capped["total"]))


# ── 小工具 ────────────────────────────────────────────────
def _count(sql: str, args: tuple = ()) -> int:
    conn = get_conn()
    try:
        return int(conn.execute(sql, args).fetchone()[0])
    finally:
        conn.close()


def _item_field(item_id: int, field: str):
    conn = get_conn()
    try:
        row = conn.execute(f"SELECT {field} FROM knowledge_item WHERE id=?", (item_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _item_field_row(question_id: int, field: str):
    conn = get_conn()
    try:
        row = conn.execute(f"SELECT {field} FROM question WHERE id=?", (question_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _qids(item_id: int, *, origin: str) -> list[tuple[str, int]]:
    conn = get_conn()
    try:
        return [(str(r["number"]), int(r["id"])) for r in conn.execute(
            "SELECT id, number FROM question WHERE item_id=? AND origin=?", (item_id, origin))]
    finally:
        conn.close()


def _question(question_id: int) -> dict:
    from app.db.repo import questions as question_repo
    conn = get_conn()
    try:
        return question_repo.get_question(conn, question_id) or {}
    finally:
        conn.close()


# ── §audit T10.9 ───────────────────────────────────────────
def _draft(**kw) -> dict:
    """一条干净的草稿；用例只改它关心的那一个字段。"""
    base = {"number": "1", "type": "single", "question": "表达式 3**2//2 的值是",
            "options": ["4", "5", "6", "7"], "answer": "A"}
    base.update(kw)
    return base


def group_audit() -> None:
    # 体检的第一条纪律是「不许误报」：一条好题被标红，用户就学会无视整排提示
    check("完整的题一条问题都不报", audit.faults(_draft()) == [], str(audit.faults(_draft())))
    check("判断题（两个选项 + 布尔答案）不报问题",
          audit.faults(_draft(type="boolean", options=["正确", "错误"], answer=True)) == [],
          str(audit.faults(_draft(type="boolean", options=["正确", "错误"], answer=True))))
    check("简答题有参考答案不报问题",
          audit.faults(_draft(type="short", options=[], answer="x = 1\nprint(x)")) == [])
    # 「…的值是」「…正确的是」是最常见的结尾，它不该被当成断句
    check("「…的值是」不算断句",
          not [f for f in audit.faults(_draft()) if f["code"] == "STEM_TAIL"])
    # 「1 到 10 的和」是完整的名词短语 —— 这条是拿真卷子跑出来才发现的误报
    check("「输出 1 到 10 的和」不算断句",
          not [f for f in audit.faults(_draft(type="short", options=[], question="编写程序, 输出 1 到 10 的和",
                                             answer="print(sum(range(1, 11)))"))
               if f["code"] == "STEM_TAIL"])

    cases = [
        ("缺答案", _draft(answer=None), "NO_ANSWER", "error"),
        ("题干是空的", _draft(question=""), "NO_STEM", "error"),
        ("单选题选项不到两个", _draft(options=["4"]), "FEW_OPTIONS", "warn"),
        ("答案指向不存在的选项", _draft(answer="D", options=["4", "5"]), "ANSWER_OUT_OF_RANGE", "warn"),
        ("题干只有三个字", _draft(question="正确吗"), "SHORT_STEM", "warn"),
        ("题干断在半路", _draft(question="下列各项中"), "STEM_TAIL", "warn"),
        ("选项混进题干", _draft(question="下列说法正确的是 A. 甲乙丙丁"), "OPTION_IN_STEM", "warn"),
        ("两个选项内容一样", _draft(options=["4", " 4 ", "6", "7"]), "DUP_OPTION", "warn"),
        ("题干里有一句重复", _draft(question="下列哪项正确。下列哪项正确。"), "STEM_DUP", "warn"),
    ]
    for name, draft, code, level in cases:
        hits = [f for f in audit.faults(draft) if f["code"] == code]
        check(f"{name} → {code}（{level}）", len(hits) == 1 and hits[0]["level"] == level,
              str([f["code"] for f in audit.faults(draft)]))

    # 缺答案只报不猜：答案必须由人在复核页定（猜一个答案比留空伤害大）
    no_answer = audit.faults(_draft(answer=None))
    check("缺答案时不替人编答案（没有任何 fix 字段）",
          all("fix" not in f or f["fix"] is None for f in no_answer), str(no_answer))

    # ── 模型那一层的守卫 ──
    block = [(0, _draft(question="下列各项中")), (1, _draft(question="关于列表的说法"))]
    fixes = [
        {"index": 1, "code": "STEM_CUT", "fix": "下列各项中，属于不可变类型的是", "note": "读到「中」就断了"},
        {"index": 2, "code": "STEM_CUT", "fix": "关于列表的说法，正确的是"},
        {"index": 2, "code": "UNREADABLE"},
    ]
    got, _lost = audit.verify(fixes, block)
    check("模型报的三条都收下", len(got) == 3, str([(g["index"], g["code"]) for g in got]))
    check("index 是 1 基，落到草稿下标时要减 1", got[0]["index"] == 0, str(got[0]["index"]))
    check("能改的两题各挂一条改法", sum(1 for g in got if g["fix"]) == 2,
          str([g["fix"] for g in got]))
    check("note 并进固定的报文案里", "读到「中」就断了" in got[0]["message"], got[0]["message"])

    bad = [
        {"index": 1, "code": "STEM_CUT", "fix": "下列各项中，属于不可变类型的是 3 种"},
        {"index": 1, "code": "STEM_MIXED", "fix": "1. 下列各项中"},
        {"index": 1, "code": "OPTION_MIXED", "fix": "这部分内容与原来完全无关，说的是另外一件不相干的事"},
        {"index": 9, "code": "STEM_CUT"},
        {"index": 1, "code": "HAS_ANSWER"},
    ]
    kept, dropped = audit.verify(bad, block)
    check("改法动了数字被拒（问题照报、改法丢掉）",
          any(d["scope"] == "fix" and d["why"] == "改法动了数字" for d in dropped), str(dropped))
    check("带题号的改法被拒", any(d["why"] == "改法里带了题号" for d in dropped))
    check("换成另一句话被拒", any(d["why"] == "改法与原文差得太远" for d in dropped))
    check("题号越界整条丢", any(d["why"] == "题号不在这一批里" for d in dropped))
    check("不认识的问题类型整条丢", any("不认识的问题类型" in d["why"] for d in dropped))
    check("被拒的只是改法，问题本身还留着",
          len(kept) == 3 and all(k["fix"] is None for k in kept),
          str([(k["code"], k["fix"]) for k in kept]))

    check("一题最多一条同一类问题",
          len([k for k in audit.verify(
              [{"index": 1, "code": "STEM_CUT"}, {"index": 1, "code": "STEM_CUT"}], block)[0]]) == 1)

    # ── 分批 ──
    many = [_draft(number=str(i)) for i in range(1, 26)]
    sizes = [len(group) for group in audit.batches(many)]
    check("25 题分成 5 批、每批 ≤6 题", sizes == [6, 6, 6, 6, 1], str(sizes))
    check("超长题自己占一批（不把别人挤掉）",
          [len(g) for g in audit.batches([_draft(question="材料" * 700), _draft()])] == [1, 1])
    check("空草稿切出 0 批", audit.batches([]) == [])

    # ── 端点：端到端，模型打桩 ──
    client = TestClient(app)
    calls = {"n": 0}

    def fake_chat(messages, **kwargs):     # noqa: ARG001
        calls["n"] += 1
        return json.dumps({"issues": [
            {"index": 1, "code": "STEM_CUT", "fix": "表达式 3**2//2 的值是"},
        ]}, ensure_ascii=False)

    real_chat = audit.llm.chat
    audit.llm.chat = fake_chat
    try:
        # 规则与模型说同一件事时只留一条：界面上曾同时出现「断在半路」与「像是被截断」
        audit.llm.chat = lambda messages, **kw: json.dumps(     # noqa: ARG005
            {"issues": [{"index": 1, "code": "STEM_CUT"}]}, ensure_ascii=False)
        one = audit.audit([_draft(question="下列各项中")], use_llm=True)
        codes = [i["code"] for i in one["issues"]]
        check("同一件事只说一遍（模型报了断句，规则那条收起）",
              "STEM_TAIL" not in codes and codes.count("STEM_CUT") == 1, str(codes))

        audit.llm.chat = fake_chat

        paper, _meta = drafts_of([PAPER])
        item3, file3 = make_item([PAPER], title="初审用试卷")
        r = client.post("/api/exams/audit", json={"drafts": paper, "use_llm": True})
        data = r.json()
        check("初审端点跑通", r.status_code == 200, r.text[:120])
        check("6 题走 1 批", data["stats"]["blocks"] == 1 and calls["n"] == 1,
              f"blocks={data['stats'].get('blocks')} calls={calls['n']}")
        check("问题挂在下标 0 上",
              any(i["index"] == 0 and i["code"] == "STEM_CUT" for i in data["issues"]),
              str([(i["index"], i["code"]) for i in data["issues"]]))
        check("统计里数得清几题有问题",
              data["stats"]["flagged"] == len({i["index"] for i in data["issues"]}),
              str(data["stats"]))
        check("初审不落库（页文本没动）", _page_field(file3, 1, "text_reviewed") is None)
        check("初审不建题目", _count("SELECT COUNT(*) FROM question WHERE item_id=?", (item3,)) == 0)
        check("初审不改草稿（返回里没有 drafts）", "drafts" not in data, str(list(data)))

        before = calls["n"]
        r2 = client.post("/api/exams/audit", json={"drafts": paper, "use_llm": False})
        check("关掉模型就不调模型", calls["n"] == before and r2.json()["stats"]["model"] == "off",
              f"calls={calls['n']} model={r2.json()['stats'].get('model')}")

        def boom(messages, **kwargs):      # noqa: ARG001
            raise audit.llm.LLMError("LLM_HTTP_ERROR", "连不上", "")

        audit.llm.chat = boom
        r3 = client.post("/api/exams/audit", json={
            "drafts": [_draft(number="1", question="", options=[], answer=None)], "use_llm": True})
        d3 = r3.json()
        check("模型挂了降级成规则体检（不 500）",
              r3.status_code == 200 and d3["stats"]["model"] == "failed", r3.text[:120])
        check("模型挂了也要报出缺答案与空题干",
              {"NO_ANSWER", "NO_STEM"} <= {i["code"] for i in d3["issues"]},
              str([i["code"] for i in d3["issues"]]))

        r4 = client.post("/api/exams/audit", json={"drafts": [], "use_llm": True})
        check("空草稿不崩", r4.status_code == 200 and r4.json()["issues"] == [], r4.text[:120])
    finally:
        audit.llm.chat = real_chat


def _page_field(file_id: int, page_no: int, field: str):
    conn = get_conn()
    try:
        row = conn.execute(f"SELECT {field} FROM item_page WHERE file_id=? AND page_no=?",
                           (file_id, page_no)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


GROUPS = (
    ("clean", group_clean), ("parse", group_parse), ("commit", group_commit),
    ("proofread", group_proofread), ("paper", group_paper), ("import", group_import),
    ("audit", group_audit),
)


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    init_db()
    print(f"Cairn M10 验收 · 临时数据目录 {TMP}")
    for name, fn in GROUPS:
        if only and only != name:
            continue
        print(f"§{name}")
        try:
            fn()
        except Exception:
            traceback.print_exc()
            check(f"§{name} 跑完", False, "异常中断，见上面的栈")

    bad = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} PASS")
    if WARNINGS:
        print(f"{len(WARNINGS)} 项 SKIP（缺样本，不影响结论）")
        for name in WARNINGS:
            print(f"  · {name}")
    print(f"临时数据目录：{TMP}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
