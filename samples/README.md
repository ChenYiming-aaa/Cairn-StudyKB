# samples/ · 本地导入验收样本

16 份真实格式的样本：**4 个主题 × 4 种版式**。用于 M9/M10 的文件抽取、双栏判列、试卷结构与 OCR 识别验收，对应 `docs/dev/执行计划-v0.3-M9-M11.md` §2.1 的四类样本口径。

> 这些是本地验收素材，**不随安装包发布，也不进仓库**（16 份 docx/pdf 与配图已由根目录 `.gitignore` 忽略）。
> 本目录下的 `_content.py`、`_generate.py` 与本文件保留在仓库，用于复现。

## 1. 清单

每个主题目录内都是一组完整的「四份样本」，文件名与执行计划 §2.1 一致：

| 主题目录 | `course.docx` | `twocol.pdf` | `exam.pdf` | `scan.pdf` |
|---|---|---|---|---|
| `python/` 计算机二级 Python | 4 章 · 3 表 2 图 | 10 页双栏 | 25 题 | 3 页拍照 |
| `java/` 计算机二级 Java | 4 章 · 4 表 3 图 | 10 页双栏 | 25 题 | 3 页拍照 |
| `cet6/` 大学英语六级 | 4 章 · 4 表 2 图 | 10 页双栏 | 27 题 | 3 页拍照 |
| `math/` 大学数学（高等数学） | 4 章 · 3 表 3 图 | 10 页双栏 | 24 题 | 3 页拍照 |

内容是真实学科考点与题目（NCRE 二级 Python/Java、CET-6 题型、高数上册），不是 Lorem ipsum 或占位符。
同一个主题内，讲义 / 试卷 / 拍照卷是**不同套卷**：拍照卷标为往次真题的考生回忆版，含手写答案与批注。

**验收脚本按四个主题目录读取**（`samples/python/` / `java/` / `cet6/` / `math/`），遍历四组共 16 份，用来测不同学科版式、题号写法与拍照质量下的识别能力；不要只挑一组，也不要复制到根目录当单份样本用（对应执行计划 §2.1 的口径）。

## 2. 四类样本各自验什么

| 类型 | 构造特征 | 对应验收点 |
|---|---|---|
| `course.docx` | Heading 1/2 层级、项目符号与编号列表、2–4 个表格、2–3 张真实网络配图、代码块、提示框、页眉与页码域 | docx 抽取、HTML 呈现、L3 图片 |
| `twocol.pdf` | A4 每页两栏 + 栏间分隔线；**10 页**；每页固定页眉（页高上 12% 区域内）与页码（下 15% 区域内）；课堂笔记留白；附录 A–G（真题自测 / 答案 / 速查表 / 解析 / 易错点 / 拍照真题 / 限时练习） | 双栏判列、页眉页脚清洗、抽取字数比对 |
| `exam.pdf` | **文字层可复制**；题号全卷 1–N 连续；选择题 A–D 四选项齐全；末页「参考答案与解析」含逐题解析与主观题参考答案 | 试卷结构化、题号/选项/答案抽取（≥20 题、答案抽中率） |
| `scan.pdf` | 图片型 PDF，**无文字层**；1240×1754（A4 @150dpi）；每页一张 JPEG；倾斜 +1.3° / −1.1° / +0.8°；单侧光照不均、高斯噪点、轻微模糊、JPEG q82；蓝色手写批注与阅卷痕迹 | 识别质量、页图对照、答案复核 |

`exam.pdf` 与 `scan.pdf` 是刻意做成一「有文字层」一「无文字层」的对照。按 `需求-v0.3-本地文件与试卷导入.md` 的 v0.3.1 修订，**PDF 正文一律走本地识别**：`exam.pdf` 的文字层只用于与识别结果做校验比对（`has_text_layer` 的校验用途）和 L3 原件定位，`scan.pdf` 则完全依赖识别。两份合起来才能验证「有 / 无文字层走同一条链路」。

## 3. 配图来源（真实网络素材，非 AI 生成）

12 张图放在 `images/`，逐张 URL、字节数与文件头记在 [`images/_sources.json`](images/_sources.json)。下载通道实测：`python.org` / `docs.python.org` / `raw.githubusercontent.com` / `matplotlib.org` / `bkimg.cdn.bcebos.com` / `commons.wikimedia.org` 的 `Special:FilePath` 可直连；`upload.wikimedia.org` 在本机超时，故 Commons 图走 `Special:FilePath` 取回。

| 文件 | 来源 | 用途 |
|---|---|---|
| `python_logo.png` | python.org 官方 logo | Python 讲义封面 |
| `python_turtle_star.png` | Python 官方文档 turtle 示例图 | turtle 标准库配图 |
| `python_logo_notext.png` | Wikimedia Commons · Python-logo-notext.svg | 双栏讲义配图 |
| `java_logo.png` | GitHub explore topics/java | Java 讲义封面 |
| `java_duke.png` | Wikimedia Commons · Duke (Java mascot) waving | Java 讲义配图 |
| `java_uml_class.png` | Wikimedia Commons · Bank account (UML class diagram) | 面向对象章节配图 |
| `cet6_score_report.jpg` | Wikimedia Commons · CET-6 Score Report.jpg | 六级成绩报告单 |
| `cet6_report_baike.png` | 百度百科图册 · CET 成绩报告单样张 | 六级讲义配图 |
| `math_parabola.png` | Wikimedia Commons · Parabola.svg | 二次函数与极值 |
| `math_integral_area.png` | Wikimedia Commons · Integral as region under curve.svg | 定积分几何意义 |
| `math_normal_dist.png` | Wikimedia Commons · Normal Distribution PDF.svg | 概率论配图 |
| `math_plot_sample.png` | matplotlib 官方文档 simple_plot 示例图 | 函数曲线示意 |

**许可说明**：已核实的是每张图的下载 URL 与图片内容；Wikimedia Commons 素材请按各自文件页的许可使用（其中 `CET-6 Score Report.jpg` 明确为 CC BY-SA 3.0，作者 BreakdownDiode）。Python / Java 标识属各自商标，此处仅作语言指示用途。全部素材只用于本地验收测试，不随产品分发。

## 4. 自检结果（`_check.json`）

由 `python samples/_generate.py --verify` 生成，以下为实跑值（2026-11-12）：

| 主题 | docx 表/图/标题 | 双栏页数·字数·页眉数 | 首页左/右栏字符数 | 试卷页数·题号·选项 | 拍照页数·文字层 |
|---|---|---|---|---|---|
| python | 3 / 2 / 8 | 10 页 · 13160 字 · 10 | 534 / 565 | 7 页 · 25 · 80 | 3 页 · 0 字 |
| java | 4 / 3 / 6 | 10 页 · 15139 字 · 10 | 574 / 680 | 7 页 · 25 · 80 | 3 页 · 0 字 |
| cet6 | 4 / 2 / 4 | 10 页 · 17764 字 · 10 | 726 / 782 | 9 页 · 27 · 100 | 3 页 · 0 字 |
| math | 3 / 3 / 4 | 10 页 · 11935 字 · 10 | 707 / 629 | 6 页 · 24 · 40 | 3 页 · 0 字 |

「首页左/右栏字符数」用 PDF 字符坐标统计，用来证明**真的分了左右两栏**，而不是排版看起来像双栏；页眉数 = 页数，说明每页都有可清洗的重复短行。math 试卷选项数偏少是因为 24 题里只有 10 道四选一，其余 14 道为填空 / 计算 / 证明题。

## 5. 重新生成

生成依赖**装在独立 venv**，不改 `backend/.venv`、不动 `backend/pyproject.toml`：

```bash
VENV="$TEMP/cairn_samples_venv"
uv venv "$VENV" --python 3.12
uv pip install --python "$VENV/Scripts/python.exe" \
    python-docx reportlab pillow numpy requests pypdf pypdfium2 \
    -i https://mirrors.aliyun.com/pypi/simple/

"$VENV/Scripts/python.exe" samples/_generate.py            # 生成 16 份 + _check.json
"$VENV/Scripts/python.exe" samples/_generate.py --verify   # 只跑自检
```

本机字体取自 `C:/Windows/Fonts`：PDF 正文宋体（`simsun.ttc`）、标题黑体（`simhei.ttf`）、数学主题与拍照卷正文微软雅黑（`msyh.ttc`，数学符号 `− ∂ ″` 覆盖最全，也和 OCR 组件基准一致）、手写批注楷体（`simkai.ttf`）。
`_generate.py` 会把缺字形的下标数字 `₀₁₂` 与 `⇒ ⇏` 统一换成等价写法，避免样本里出现假的「生僻字」。
`pypdfium2` 仅用于自检里的双栏坐标统计，缺了不影响生成（该字段会跳过）。
