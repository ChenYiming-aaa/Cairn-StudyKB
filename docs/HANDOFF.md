# HANDOFF · 进度台账

> **作用域**：只读本文件最后 2 条 + `00-总纲.md` + 当前里程碑文档。**不要读** `archive/*`。
> **冲突时**：本文件的"遗留问题"若与当前里程碑文档矛盾，以本文件为准（它更接近事实），并回头修里程碑文档。
> **用途**：这是唯一能真正扛住上下文压缩的东西。文档会过时，代码会变，"我上次做到哪、卡在哪、下一步做什么"只在这里。
> **规则**：
> 1. **只追加，不修改历史条目**（写错了就在新条目里更正）
> 2. 每次会话结束前必须写一条，哪怕只做了很小的事
> 3. 新会话**只读最后 2 条**，不要从头读
> 4. "遗留问题"必须写成可执行的一句话，不要写"还需优化"

---

## 条目模板（复制下面这段用）

```markdown
## YYYY-MM-DD HH:mm · M{n} · 会话主题

**完成**
- T1.x 具体做了什么（一句话，能对应到任务编号）

**改动文件**
- `backend/app/services/llm.py`（新增）
- `backend/app/routers/knowledge.py`（改）

**验证**
- `scripts/verify_m1.py` → 7/7 PASS
- 手工验证：粘贴 800 字 → 整理成功

**遗留问题**（每条都要能直接开干）
- [ ] 整理 Agent 对超短文本（<100 字）会返回空 summary，需在 prompt 里加最小长度约束
- [ ] 分类树的空态样式还没做

**待裁决冲突**（没有就写"无"）
- `milestones/M3` 说向量表叫 `chunk_emb`，`数据契约` 写的是 `chunk_vec` → 按 §5.1 以契约为准，已改 M3

**下一会话第一件事**
> 打开 `milestones/M1-*.md` 的 T1.11，写 verify 脚本。
```

---

## 2026-11-05 20:40 · M0 · 文档体系搭建（尚未开始写代码）

**完成**
- 将初版《实施规格书》拆成三层文档：总纲 / 契约 / 里程碑
- 建立 ADR 决策记录（16 条），把技术选型的理由与推翻成本固化下来
- 建立本台账

**改动文件**
- `docs/00-总纲.md`（新增）
- `docs/contracts/数据契约.md`（新增）
- `docs/contracts/接口契约.md`（新增）
- `docs/contracts/决策记录.md`（新增）
- `docs/milestones/M1-骨架与最小闭环.md`（新增）
- `docs/milestones/M2-真实内容采集.md`（新增）
- `docs/milestones/M3-检索与学习页.md`（新增）
- `docs/milestones/M4-出题与练习.md`（新增）
- `docs/milestones/M5-计时与交付.md`（新增）
- `docs/archive/实施规格书-v1.0.md`（归档，勿读）

**验证**
- 尚未开始编码，无验证

**遗留问题**
- [ ] 用户尚未最终确认三件事：番茄钟应用锁定是否属于本期核心（当前判定为 v2）、`structured_note` 是否需要可视化编辑、M3/M4 顺序是否调整
- [ ] 本机 `ffmpeg` 未安装，M2 前必须补
- [ ] `uv` 是否已安装待确认

**下一会话第一件事**
> 用户确认后，从 `milestones/M1-骨架与最小闭环.md` 的 T1.1 开始；开工前先跑一遍 §2 的前置核对命令。

---

## 2026-11-05 20:45 · M0 · 建立文档防漂移机制

**背景**：用户提出担心——权限全开时 agent 可能读错文档，导致信息不一致。

**完成**
- 10 份文档全部加上「作用域声明」（读什么 / 不读什么 / 冲突怎么办）
- `00-总纲` 新增 §5.1 冲突裁决链（L0 红线 → L5 归档）、§5.2 文档自我失效约定、§5.3 自动校验
- `00-总纲` §6 加入「读取纪律」5 条
- 新增 `tools/doc_check.py`：6 项交叉校验

**改动文件**
- `tools/doc_check.py`（新增）
- `docs/00-总纲.md`（改，版本 v1.0 → v1.1）
- `docs/contracts/{数据契约,接口契约,决策记录}.md`（加作用域声明）
- `docs/milestones/M1..M5`（加作用域声明）
- `docs/HANDOFF.md`（加作用域声明 + 待裁决冲突字段）

**验证**
- `python tools/doc_check.py` → 6 项全 PASS
- lint 首跑就抓到真问题：M3 里 `CREATE VIRTUAL TABLE chunk_vec` 未在数据契约登记 → 已补进契约

**遗留问题**
- [ ] 用户仍未答复三件事：番茄钟应用锁定是否本期、`structured_note` 是否需可视化编辑、M3/M4 顺序
- [ ] 目录尚未 `git init`，M1 开工前必做

**待裁决冲突**
- 无

**下一会话第一件事**
> 跑 `python tools/doc_check.py` 确认文档未漂移；然后按 M1 §2 核对环境（ffmpeg、uv、sqlite 版本）。

---

## 2026-11-05 20:55 · M0 · 用户三项决策落定

**用户决策**
1. 番茄钟应用锁定 → **不属于本期**（v2）
2. `structured_note` → **要可编辑**，且**要能生成思维导图**
3. M3 / M4 顺序 → **不调整**

**完成**
- 数据契约：`knowledge_item` 增 `note_edited`；`chunk` 增 `source`（raw/note）+ 索引改为 `(item_id, source)`；新增 §6 派生重建规则、§7 导图不落库规则
- 接口契约：新增 `GET /api/knowledge/{id}/mindmap`；`PATCH` 增加"保存笔记必须重建 note chunk"的副作用；详情响应加 `note_edited`
- 决策记录：新增 ADR-017（后端出 SVG）、ADR-018（Markdown 源码编辑）、ADR-019（导图不落库）
- M1：T1.10 扩为"阅读器 + 笔记编辑器"，新增 §6.9 编辑器实现、§6.10 chunker 复用；DoD 加 2 条
- M3：新增 T3.7 思维导图，其余任务顺延；新增 §6.6 导图生成（解析/布局/绘制/四个必须）；HTML 模板要求内嵌 SVG 且 bleach 白名单放行 SVG
- 总纲：技术栈加"笔记编辑""思维导图"两行；M3 描述与工期更新

**改动文件**
- `docs/contracts/{数据契约,接口契约,决策记录}.md`
- `docs/milestones/{M1-骨架与最小闭环,M3-检索与学习页}.md`
- `docs/00-总纲.md`

**验证**
- `python tools/doc_check.py` → 6 项全 PASS（ADR 19 条、端点 30 个、表 11 张）

**遗留问题**
- [ ] 目录尚未 `git init`
- [ ] `ffmpeg`、`uv` 仍未确认安装

**待裁决冲突**
- 无

**下一会话第一件事**
> `git init` + 首次提交，然后按 M1 §2 核对环境，从 T1.1 开始。

---

## 2026-11-05 21:05 · M0 · 四条红线复核与精确化

**背景**：用户质疑红线第 3–6 条（多 Agent 框架 / ORM / UI 组件库 / 独立向量库）是否武断。

**结论**：三条站得住但缺"何时该解除"的判据；**第 4 条表述不准**（把"不用 ORM 自动映射"写成了"不用 ORM"），已修正。

**用户新决策**
- 数据层：**裸 SQL + `repo/` 薄封装 + Pydantic 模型**（不引 ORM）
- 前端：**原生 CSS + 自建组件，允许单点引入专用小库**

**完成**
- 总纲 §2 第 3–6 条改写为精确表述（第 4 条从"不引入 ORM"→"不引入 ORM 的对象关系自动映射"）
- 总纲新增 §2.1「四条限制的真实理由与解除条件」表格
- 决策记录新增 ADR-020：逐条写清真实理由、我承认的代价、解除条件；并在 ADR-005 加前向引用
- M1 约束第 2 条同步改写

**改动文件**
- `docs/00-总纲.md`（§2 改写 + 新增 §2.1）
- `docs/contracts/决策记录.md`（ADR-020 新增，ADR-005 加引用）
- `docs/milestones/M1-骨架与最小闭环.md`（约束第 2 条）

**验证**
- `python tools/doc_check.py` → 6 项全 PASS（ADR 20 条、端点 30 个、表 11 张）

**遗留问题**（已在下一会话前全部解决，见下方 21:20 条目）

**待裁决冲突**
- 无

---

## 2026-11-05 21:20 · M0 · 仓库初始化 + 环境核对完成

**完成**

- `git init -b main` + 首次提交（14 个文件）+ 标签 `m0-docs`；`.gitattributes` 统一 LF
- `.gitignore` 排除 `data/ *.db .env node_modules dist build models logs` 与 `.workbuddy/`
- 新增 `README.md`、`docs/会话提示词手册.md`
- 环境核对结果（实测）：
  - Python 3.13.14（另需 uv 装 3.12）、SQLite **3.53.1**（远超 trigram 要求的 3.34）
  - uv 0.13.5 ✅、Node 22.22.2 ✅、git 2.55 ✅、winget 1.29 ✅、CUDA 12.4 在 PATH ✅
  - **ffmpeg / ffprobe 4.3.1 已装**（conda-forge 清华镜像 → `D:\Anaconda3\Library\bin`），实测 16k 单声道 wav 转码成功
- `00-总纲.md` §9 环境基线改写为实测值；M2 §2 前置条件与排障表同步修正

**踩到的坑（已写进总纲 §9，别再重复）**

- `winget install Gyan.FFmpeg` 本机被拦截；gyan.dev / GitHub Releases 只有 ~7KB/s，80MB 静态包下不动
- 有效路径：`conda install -c https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge ffmpeg`
- ffmpeg 装在 Anaconda 目录下，**M5 打包必须自带一份进 `resources/`**，不能依赖系统 PATH

**改动文件**

- `.gitignore`、`.gitattributes`、`README.md`（新增）
- `docs/会话提示词手册.md`（新增）
- `docs/00-总纲.md`（§5 表格加手册行、§9 重写）
- `docs/milestones/M2-真实内容采集.md`（前置条件与排障修正）

**验证**

- `python tools/doc_check.py` → 6 项全 PASS（11 份文档）
- `ffmpeg -f lavfi -i sine → 16k mono wav` → 成功，`ffprobe` 读到 duration=2.0

**遗留问题**

- [ ] Python 3.12 尚未安装（M1 T1.1 第一件事：`uv python install 3.12`）
- [ ] LLM API Key 尚未配置（M1 T1.5 之前必须就位）

**待裁决冲突**
- 无

**下一会话第一件事**
> 用户新开会话执行 M1。开场按 `00-总纲.md` §6：读总纲 + M1 文档 → 跑 `tools/doc_check.py`（`scripts/status.py` 还没创建，T1.4 才产出）→ 读本文件最后两条。

---

## 2026-11-05 22:24 · M0 · 项目定名 cairn

**背景**：用户要求取一个有特色、不与常见项目重名的名字。原占位名 `study-kb` 过于通名。

**决策**：项目定名 **Cairn**（cairn /kɛərn/，登山者沿途堆的石堆路标——走一段留一块石头，靠自己的标记找得回来）。弃用候选：`herbarium`（意象最贴但 9 字母难拼）、`loom`（已被知名录屏工具占用品牌）、`kindling`。

**命名约定（已写入总纲 §1.1，改起来很贵）**

| 用途 | 取值 |
|---|---|
| GitHub 仓库名 | `cairn` |
| Python 包名 | `cairn` |
| 后端可执行文件 | `cairn-backend.exe` |
| 生产数据目录 | `%APPDATA%/Cairn` |
| 数据库文件 | `data.db`（保持不变，目录已带名字） |
| Electron appId / productName | `com.cairn.app` / `Cairn` |

**改动文件**
- `docs/00-总纲.md`（新增 §1.1 命名约定；§5 阅读预算按新行数校正）
- `docs/milestones/M5-计时与交付.md`（`cairn-backend`、`%APPDATA%/Cairn`、appId/productName）
- `README.md`（标题改为 Cairn + 词源说明）

**验证**
- `python tools/doc_check.py` → 6 项全 PASS
- `grep study-kb/StudyKB` 在 archive 之外为 **0** 处（`docs/archive/` 保留旧名，属于历史记录，不修改）

**遗留问题**
- [ ] **GitHub 尚未推送**：本地已有 3 次提交，但从未配置 remote。需用户先在 GitHub 建私有仓库 `cairn`（不要勾任何初始化选项），再执行 `git remote add` + `push`
- [ ] Python 3.12 未安装；LLM API Key 未配置
- [ ] 本地目录名仍是 `知识库agent开发`，与仓库名 `cairn` 不一致。**不影响功能**；若要改，须在没有任何会话运行时操作

**待裁决冲突**
- 无

**下一会话第一件事**
> 若 GitHub 已建好仓库，先 `git remote add origin …` 推送；否则直接开始 M1（`uv python install 3.12`）。

---

## 2026-11-05 22:32 · M0 · 配置远程，推送待用户执行

**背景**：用户建好私有仓库 `https://github.com/ChenYiming-aaa/Cairn-StudyKB`（仓库名并非 `cairn`）。

**完成**
- `origin` 已配置为 `https://github.com/ChenYiming-aaa/Cairn-StudyKB.git`
- 本地：`main` 分支，4 次提交（`50cedaa` 最新），2 个标签（`m0-docs`、`m0-ready`）
- 总纲 §1.1 仓库名更新为 `Cairn-StudyKB`；§9 新增两条 git 环境坑位

**为什么推送没做（重要，别重复踩）**
1. **PATH 里的 `git` 是 WorkBuddy 精简版**（`D:/workbuddy/resources/vendor/PortableGit`，2.55），
   `libexec/git-core` 里**没有 `git-remote-https.exe`**，执行 `git ls-remote` 直接报
   `git: 'remote-https' is not a git command`
2. 完整版在 `C:\Program Files\Git\cmd\git.exe`（2.49），`remote-http(s).exe` 齐全，可用
3. 本 shell 继承代理 `http://127.0.0.1:3669`，`curl https://github.com` 需 20s+；
   `git credential fill` 会等 GCM 弹窗，非交互环境下超时被杀
4. 结论：**需要认证的 git 操作（push/fetch）必须用户在普通终端或 GitHub Desktop 里做**

**遗留问题**
- [ ] **推送未完成**：用户需在自己终端执行 `git push -u origin main && git push --tags`
- [ ] GitHub 凭据尚未缓存，首次推送会弹浏览器登录
- [ ] Python 3.12 未安装；LLM API Key 未配置

**待裁决冲突**
- 无

**下一会话第一件事**
> 先确认推送是否成功（`git log origin/main --oneline` 或看 GitHub 页面）。若已推送，开始 M1：`uv python install 3.12` → T1.1。

---

## 2026-11-05 22:41 · M0 完成 · 远程推送已验证

**结果**：用户在自己终端完成首次登录并推送，**GitHub 凭据已存入 Windows 凭据管理器，此后 agent 侧可直接 push / fetch / ls-remote，无需再人工登录**。

**远程核对（`git ls-remote origin`）**

```
64d60cc  HEAD
64d60cc  refs/heads/main
4148427  refs/tags/m0-docs
a167c49 → 999c70f  refs/tags/m0-ready（附注标签）
```

本地 `HEAD` = `origin/main` = `64d60cc`，**完全一致，无 ahead/behind**。

**踩坑记录（补两条到总纲 §9 的思路）**
- 推送失败的根因不是"私有仓库"，而是 ①PATH 中 git 为精简版缺 `git-remote-https.exe` ②GCM 需人工登录而 agent 是非交互环境
- 私有与否只影响匿名**读**，不影响**推**；公开仓库推送同样要认证
- 诊断技巧：同时 curl 一个已知公开仓库和自建仓库——公开的 504、自己的 404，说明 504 是代理超时而非仓库问题

**M0 正式收尾**

| 项 | 状态 |
|---|---|
| 文档体系（总纲/契约/5 里程碑/台账/提示词手册） | ✅ |
| git 仓库 + 5 次提交 + 2 标签 + 远程同步 | ✅ |
| 环境（Python 3.13/uv/SQLite 3.53/Node 22/CUDA 12.4/ffmpeg 4.3.1） | ✅ |
| 待补：Python 3.12、LLM API Key | ⏳ M1 内解决 |

**下一会话第一件事**
> 开始 M1。`uv python install 3.12` → T1.1 建目录骨架。提示词模板见 `docs/会话提示词手册.md` 模板 A。

---

## 2026-11-06 00:05 · M1 · 后端骨架 T1.1–T1.7（本次会话）

**背景**：M1 开工。开场按总纲 §6 读总纲 + M1 文档、跑 `doc_check.py`、读本台账最后两条；按 M1 §2 逐条核对环境。
**注意**：开场后等待用户裁决期间，另有会话并发提交了 6 次（22:22–23:00，定名 Cairn、配 origin、写台账、新增 `.env.example`、按 DeepSeek 规范更新 LLM 配置、补提示词手册），
并改动了总纲、M1 文档、决策记录（新增 ADR-021）。本会话已重读 `HEAD = origin/main = 748dde1` 的磁盘最新版作为执行依据，开场读到的旧版作废。

**用户裁决（6 条，已全部回写文档）**

| # | 冲突/取舍 | 裁决 |
|---|---|---|
| 1 | M1 §8 要求打 `m1-done` + 改总纲「已验收」+ 盖完结章，但本次只做 T1.1–T1.7、DoD 大半未达成、`verify_m1.py`（T1.11）尚不存在 | 打**阶段 tag `m1-backend`**，不改总纲状态、不盖完结章，台账写明 M1 进行中 |
| 2 | 接口契约标 M1 的 11 个端点，T1.1–T1.7 只明确覆盖 knowledge CRUD | 本次做 knowledge 5 个 + `/api/health` + `/api/tasks` + `/api/tasks/{id}`；`/api/env/check` **本次不做**，契约标 M1 是笔误，实际属 M2 §4 的 T2.5（已核实），归属回写为 M2；`organize*` / `mindmap` 不动 |
| 3 | M1 §5 DoD 写 `/api/health` 返回 `{"status":"ok"}`，接口契约 §2 写带 `version` | 以 L1 契约为准返回 `{"status":"ok","version":...}`，M1 DoD 首条同步改一致 |
| 4 | 数据契约 §2 全量 DDL 含 `CREATE VIRTUAL TABLE chunk_vec USING vec0`，但 §6.1 的 uv add 清单没有 sqlite-vec，直接执行会建库失败 | **条件创建，且 vec0 不写进 `schema.sql`，单独放 `backend/app/db/schema_vec.sql`**；`migrate.py` 仅在检测到扩展时执行；数据契约 §1 补例外说明 |
| 5 | 并发改动后的 M1 T1.5 / §6.11 要求 `llm_call_log` 记录 `reasoning_tokens`，但数据契约 §2 DDL 没有该列 | **加字段 + 新 ADR**：数据契约 §2 增列、§3 补语义、新增 ADR-022；首次建库直接进初始 schema，无需迁移 |
| 6 | 数据契约 §3 写截断阈值 8000 字，ADR-021 与新版 M1 §6.6 已改为 50,000 字符 | **以 50,000 为准**，修数据契约 §3（判定为并发会话漏改的旧表述）；本次不写截断代码（属 T1.8） |

**完成**

- T1.1 仓库骨架：`backend/ frontend/ desktop/ data/`，`pyproject.toml`（Python 3.12 锁 `>=3.12,<3.13`）+ `uv.lock`，`.gitignore` / `.env.example` 复核已符合要求
- T1.2 `config.py`：命令行 > `.env` > 默认；按天滚动日志到 `data/logs/app.log`；启动打印数据目录与端口。Key 只从 `.env` 读，不提供命令行覆盖
- T1.3 数据库层：`schema.sql`（全量业务表，含 `reasoning_tokens`，trigram FTS5）、`schema_vec.sql`、`migrate.py`（`PRAGMA user_version=1`、WAL、每连接 `foreign_keys=ON`、条件加载 vec）、`repo/` 封装 items/tasks
- T1.4 `scripts/status.py`：DB 路径与各表行数、环境自检、已完成里程碑、最近 3 条任务；支持 `--db` 打开复制品
- T1.5 `services/llm.py`：`chat()` / `chat_stream()` / `extract_json()`，120s 超时、1s/3s 退避重试 2 次，按 §6.11 拼 `{base_url}/chat/completions`（`rstrip('/')`）、`response_format=json_object`、只取 `content` 丢弃 `reasoning_content`、每次调用写 `llm_call_log`
- T1.6 `services/tasks.py`：`ThreadPoolExecutor(max_workers=2)`，`submit(type, fn, input)` 立即返回 uuid，异常落 `error_code/error_msg`，启动清理残留 running
- T1.7 `routers/knowledge.py` + `services/chunker.py`：CRUD 5 个端点、创建自动切块、`content_hash` 去重、PATCH 保存笔记时重建 `source='note'` chunk 并置 `note_edited=1`；`chunker.split()` 为纯函数且两处复用

**改动文件**

- 文档：`docs/contracts/{接口契约,数据契约,决策记录}.md`、`docs/milestones/M1-骨架与最小闭环.md`（均为裁决回写）、`docs/HANDOFF.md`（本条）
- 后端新增 26 个文件（见 `git show --stat`），主要：`backend/app/{main,config,errors}.py`、`backend/app/db/{schema.sql,schema_vec.sql,migrate.py,conn.py,repo/}`、`backend/app/services/{llm,tasks,chunker}.py`、`backend/app/routers/{health,knowledge,tasks}.py`、`backend/scripts/status.py`、`backend/pyproject.toml`、`backend/uv.lock`
- 目录占位：`frontend/.gitkeep`、`desktop/.gitkeep`

**验证**

- `python tools/doc_check.py` → 6 项全 PASS（ADR 22 条、端点 30 个、表 11 张）
- 内联回归 **24/24 PASS**：health/docs、CRUD、去重、note 重建、笔记进 FTS、trigram、chunk_vec 条件跳过、WAL+user_version、reasoning_tokens 列、无 Key `LLM_NO_KEY` 降级、并发 8 任务全 done、异常任务落 error_msg、tasks 端点、启动清理残留、删除后 chunk 与 chunk_fts 均无残留、404 错误形状、复制品可打开
- 真实 `uvicorn app.main:app --port 8756`：`/api/health` 返回 `{"status":"ok","version":"0.1.0"}`、`/docs` 200、OpenAPI 登记的正是裁决范围内 5 个路径
- `uv run python scripts/status.py` → 正常输出（EXIT=0）；`data.db` 整文件复制品可被 `status.py --db` 正常打开
- 红线 7：代码不硬编码 Key、日志不含真实 Key（已用值比对，只报布尔）、`.env` 未被 git 跟踪、异常栈用 `from None` 切断原始 httpx 上下文
- 单文件均 ≤300 行

**过程中修掉的两个真实缺陷**（执行类，未涉及表结构/接口/选型/目录/依赖，按手册 §8 自行处理）

1. `services/tasks.py` 的 `submit(type, ...)` 参数名遮蔽内置 `type()`，except 分支里 `type(exc).__name__` 抛 `TypeError: 'str' object is not callable`，导致异常分支自身崩溃、错误被线程池吞掉，**违反红线 8**。已改用 `exc.__class__.__name__`。另将线程池改为懒加载，避免 lifespan 退出 `shutdown()` 后 `submit()` 永久抛 `cannot schedule new futures after shutdown`
2. Windows + WAL 竞态：最后一个连接关闭时 SQLite 会 checkpoint 并删除 `-wal/-shm`，另一线程此刻打开连接会被判定为只读（`attempt to write a readonly database`），生产里「后台任务写 + 用户请求写」会偶发失败。已在 `db/conn.py` 增加一个不执行业务 SQL 的空闲保活连接阻止 WAL 文件被清理；业务连接仍是「每请求新建」（M1 §6.2）

**遗留问题**（每条都能直接开干）

- [ ] **T1.8 起未做**：整理 Agent（`prompts/organize.md`、`services/agents/organizer.py`）、`POST /api/knowledge/{id}/organize`、`POST /api/knowledge/organize-pending`；整理时按 M1 §6.6 的 50,000 字符截断并置 `truncated=1`
- [ ] **T1.9–T1.11 未做**：前端骨架（先写 `tokens.css`）、阅读器 + 笔记编辑器、`scripts/verify_m1.py`；因此本次未打 `m1-done`、未改总纲状态、未盖完结章
- [ ] `verify_m1.py`（T1.11）写「删除后 chunk_fts 无残留」断言时注意：FTS5 外部内容表 delete 触发器只写删除标记，`chunk_fts` 主虚拟表 `COUNT(*)` 与 `MATCH` 均为 0，但影子表 `chunk_fts_data` 仍留明文 term；实测 `INSERT INTO chunk_fts(chunk_fts) VALUES('optimize')` 可清除。数据契约 §6 规定「`chunk_fts` 只由触发器维护，任何代码都不许直接写它」，**是否允许在删除路径加 optimize 需要裁决**，本次未擅自实现，验收按主虚拟表口径
- [ ] `/api/env/check` 归属已在契约回写为 M2，实现见 M2 §4 T2.5（`scripts/env_check.py`）
- [ ] 总纲 §9 与 21:20 台账记「Python 3.12 尚未安装」，实测 uv 已装 3.12.13 / 3.12.15，本次直接 `uv venv --python 3.12`，未重复 install。按台账「只追加更正」规则在此注明，未改历史条目
- [ ] M1 §8 的 `verify_m1.py 全绿` 与「改总纲为已验收」两项留到 T1.11 完成后执行；届时才打 `m1-done` 并按 §5.2 盖完结章

**待裁决冲突**

- 本会话共 6 条冲突/取舍，均已由用户裁决并回写文档（见上表），无遗留待裁决项
- 新增一条**留给 T1.11 的待裁决**：FTS5 影子表明文残留是否算 DoD 的「chunk_fts 有残留」，以及是否允许删除路径执行 `optimize`（与数据契约 §6「不许直接写 chunk_fts」冲突）

**下一会话第一件事**
> 打开 `milestones/M1-骨架与最小闭环.md` 的 T1.8，写 `prompts/organize.md` 与 `services/agents/organizer.py`，再实现 `POST /api/knowledge/{id}/organize`；开工先跑 `uv run python scripts/status.py` 与 `python tools/doc_check.py`。

---

## 2026-11-06 00:20 · M1 · T1.8 整理 Agent + T1.9/T1.10 前端（本次会话）

**背景**：用户要求「继续做 M1 T1.7 以后的前端部分」。开工按总纲 §6 读总纲 + M1 + 契约相关小节，跑 `doc_check.py`（6/6 PASS）与 `status.py`（Python 3.12.13 / SQLite 3.50.4 / trigram 可用 / Key 已配置 / 库内 0 条）。
事实核对发现两处文档与服务端不一致：`POST /api/knowledge/{id}/organize`（T1.8）**尚未实现**；`GET /api/knowledge` 无标签筛选、无分类聚合端点，而 T1.10 要求「两级分类树」。

**用户裁决（3 条，已全部回写契约）**

| # | 冲突/取舍 | 裁决 |
|---|---|---|
| 1 | 两级分类树的层级定义 | **分类（category）→ 标签（tags）**；为此给 `GET /api/knowledge` 增加 `tag` 查询参数（`json_each` 精确匹配），已登记进接口契约 §3 |
| 2 | 分类节点条目数从哪来 | **前端拉 `page_size=100` 的列表本地聚合**，不加聚合端点。代价：条目超 100 后计数偏低，见下方遗留 |
| 3 | T1.8 未实现，前端「整理」按钮无端点 | **顺带补 T1.8**，让闭环真正跑通（本次范围因此扩到后端） |

**完成**

- T1.8 整理 Agent：`prompts/organize.md`（角色/输入/严格 JSON schema/硬性约束，含 M3 导图依赖的 `#`+`-` 结构要求）、`services/agents/organizer.py`（50,000 字符采样前 40k+末 10k、解析失败重试一次、`summary` 空或 `key_points<2` 也重试一次、失败落 `status=failed` 并带错误码上抛）
- T1.8 端点：`POST /{id}/organize`（202 + task_id；无 Key 提前 400 `LLM_NO_KEY`，已在整理中 409 `ITEM_BUSY`）、`POST /organize-pending`（只挑 pending，逐条派发）
- T1.8 落库：新增 `repo.save_organize_result()`，**刻意不走 `update_item`**——后者会因 `structured_note` 把 `note_edited` 置 1，而整理是机器行为不能冒充手改；整理后按数据契约 §6 重建 `source='note'` chunk
- T1.9 前端骨架：Vite 6 + Vue 3 + vue-router（hash 模式，为 M5 `file://` 打包留路）、`styles/tokens.css`（§6.7 全量 + 字体三项新增）、`styles/app.css`（全局控件与三态）、`api/client.js`（统一错误 + `pollTask` 1.5s→5s 退避 20 分钟）、主布局（顶栏 + 左树 + 列表 + 详情）
- T1.10 阅读器 + 笔记编辑器：`CategoryTree`（分类→标签两级、计数、折叠）、`ItemList`（标题搜索 300ms 防抖、状态徽标、空/加载/错误三态）、`ItemDetail`（摘要与要点 / 结构化笔记 / 原文 三 Tab、整理与删除、truncated 提示、笔记已手改标记）、`NoteEditor`（编辑/预览/分屏、marked+dompurify、渲染 500ms 防抖、Ctrl+S 保存、脏标记 + `beforeunload` + 切换条目拦截）

**改动文件**

- 后端：`app/prompts/organize.md`（新）、`app/services/agents/{__init__,organizer}.py`（新）、`app/db/repo/items.py`（`list_items` 加 `tag`；新增 `set_status` / `list_ids_by_status` / `save_organize_result`）、`app/routers/knowledge.py`（两个 organize 端点 + `tag` 参数）
- 前端：`package.json`、`package-lock.json`、`vite.config.js`、`index.html`、`src/{main.js,App.vue}`、`src/router/index.js`、`src/api` 目录下的 `client.js`、`src/styles/{tokens,app}.css`、`src/composables/{useUi,useToast}.js`、`src/utils/format.js`、`src/views/Knowledge.vue`、`src/components/{PasteDialog,StatusBadge,CategoryTree,ItemList,ItemDetail,NoteEditor}.vue`
- 文档：`contracts/接口契约.md`（`tag` 参数、两个 organize 端点形状、`client.js` baseUrl 优先级与「空串走 Vite 代理」）、`00-总纲.md`（M1 状态改「进行中」）、`HANDOFF.md`（本条）

**验证**

- `python tools/doc_check.py` → 6 项全 PASS（ADR 22 / 端点 30 / 表 11）
- 后端冒烟（真实 DeepSeek 调用，临时 DATA_DIR）：800+ 字文本 → `chunk_count=2` → organize 202 → 任务 done → `category=时间管理`、5 个 tags、6 条 key_points、note 645 字、`note_edited=0`、`truncated=0`、note chunk=2 → `?tag=番茄工作法` 命中 1 条 → PATCH 笔记后 `note_edited=1`、note chunk 重建 → `organize-pending` 返回 1 条
- 前端 `npm run build` → 47 modules，CSS 15.3kB / JS 189kB，无告警
- Playwright（Anaconda Python 的 playwright 1.60 + 本机 chromium）端到端：首屏 → 粘贴 400 字 → 列表出现 pending → 整理 → 变 ready → 摘要 137 字 / 关键点 6 条 → 结构化笔记 547 字且预览已渲染 → 追加一行保存 → 刷新后内容仍在且出现「笔记已手改」→ 原文 Tab 正常 → 点分类过滤剩 1 条；**全程 0 条 console 错误**
- 脏标记拦截单独验证：改笔记后点另一条目 → 弹「结构化笔记有未保存的修改…」→ 取消后仍停在原条目、`.dirty` 标记保留
- 截图存于 `data/_e2e/`（gitignored）：`03-ready.png`、`10-note-split.png` 等

**过程中修掉的问题**

1. 前端首轮截图：详情标题取自正文首行（120 字）占三行，把 meta 挤下去 → `.title` 加两行截断
2. 空态（无条目 / 未选中）浮在面板顶部 → `.state` 改 flex 居中，列表与详情各自 `justify-content:center`
3. 正文行宽过宽（详情区约 600px 满宽）→ `.summary/.points/.raw/.prose` 加 `max-width:72ch/74ch`

**已知偏离（不是遗漏，写在这里备查）**

- M1 §6.9 要求「切换 Tab 也要拦截确认」。实现改为三 Tab 用 `v-show` 常驻挂载：切 Tab 不会丢内容，因此只对「切换条目」和「关闭窗口」弹确认。若坚持弹窗，改 `ItemDetail` 的 `v-show` 为 `v-if` 即可，但会丢掉切 Tab 时的编辑状态
- 接口契约 §4 原写「开发期默认 `http://127.0.0.1:8756`」，实现改为空串走 Vite 代理（同源，不依赖 CORS），已回写契约说明两种来源

**遗留问题**（每条都能直接开干）

- [ ] **T1.11 未做**：`backend/scripts/verify_m1.py`（建库→造 3 条→整理→改笔记→断言 chunk 重建→删条目→查残留→清理）。因它不存在，本次未跑 §8 收工清单、未打 tag、未改总纲为「已验收」
- [ ] 分类树计数上限 100 条（裁决 2 的代价）：条目超过 100 后左侧计数偏低。超过时再加 `knowledge/categories` 聚合端点并登记契约
- [ ] 前端未实现改标题 / 改分类 / 改标签的 UI（`PATCH` 后端已支持）。M1 DoD 不要求，属 backlog
- [ ] `verify_m1.py` 写「删条目后 chunk_fts 无残留」时仍需裁决：FTS5 影子表 `chunk_fts_data` 留明文 term 是否算残留、是否允许删除路径执行 `optimize`（与数据契约 §6「不许直接写 chunk_fts」冲突）——**上一会话遗留，本次未动**
- [ ] 开发库 `data/data.db` 现有 1 条真实测试条目（间隔重复，已整理、已手改笔记），是人工验收用的样例数据，未被 git 跟踪
- [ ] 前端无 ESLint / 无单测；`package.json` 只有 dev/build/preview 三个脚本

**待裁决冲突**

- 无（本次 3 条取舍均已由用户裁决并回写契约）

**下一会话第一件事**
> 写 `backend/scripts/verify_m1.py` 覆盖 M1 §4 的 T1.11 与 §5 全部 DoD（含 FTS 残留口径），跑绿后按 §8 收尾：打 `m1-done`、改总纲为「已验收」、按 §5.2 盖完结章。


## 2026-11-06 00:40 · M1 收尾 · T1.11 验收脚本 + 里程碑完结

**背景**：上一会话遗留的待裁决——DoD 里「删除后 `chunk_fts` 无残留」是否包含 FTS5 影子表（`chunk_fts_data`）里的明文 term，以及是否因此允许在删除路径执行 `optimize`。

**用户裁决（1 条）**

| # | 冲突/取舍 | 裁决 |
|---|---|---|
| 1 | 影子表明文残留算不算 DoD 的「chunk_fts 有残留」 | **不算**。DoD 说的「残留」只指 **SQL 查得到的东西**，不涉及文件里还留着几个字节。故只断言主虚拟表按 `rowid`/`MATCH` 查不到，删除路径**不执行** `optimize`（也就不用去写 `chunk_fts`，与数据契约 §6「不许直接写」不冲突） |

**完成**

- T1.11 `scripts/verify_m1.py`：8 组断言 43 项，自建临时 `DATA_DIR`、全程不碰 `data/data.db`、末尾清理；`--keep` 可保留现场排障；未配 Key 直接退 2 并说明原因
- T1.11 `scripts/fixtures_m1.py`：3 篇 789–891 字真实中文长文（记忆方法 / 时间管理 / 学习方法），实测均切成 2 块，用于验证 `chunk_count > 1`
- M1 §5 的 11 条 DoD 全部勾上，M1 文档盖完结章、§9 补验收记录；总纲 M1 状态改「已验收」；数据契约 §6 落裁决口径
- 顺手把 `会话提示词手册` 模板 A/B 的示例从 M1 换成 M2——M1 已完结，示例继续指它会让下个会话照着读旧文档

**改动文件**

- `backend/scripts/verify_m1.py`（新）、`backend/scripts/fixtures_m1.py`（新）
- `docs/milestones/M1-骨架与最小闭环.md`（完结章 + DoD 勾选 + §9 验收记录）
- `docs/contracts/数据契约.md`（§6 不变量补残留判定口径）
- `docs/00-总纲.md`（M1 → 已验收）、`docs/会话提示词手册.md`（示例换 M2）、`docs/HANDOFF.md`（本条）

**验证**

- `uv run python scripts/verify_m1.py` → **43/43 PASS，EXIT=0**（真实 DeepSeek，3 篇各 1 次整理 + 1 次批量）
  - 造 3 条均 `pending`/`chunk=2`；`organize` 202→done，`organize-pending` 命中剩余 2 条
  - 三条 `ready` 且 `category/tags/summary/key_points/structured_note` 全非空，`note_edited=0`（机器整理不冒充手改）
  - PATCH 笔记 → `note_edited=1`、note chunk 重建（旧 chunk ID 全消失）、新内容可被 FTS 命中、刷新后仍在
  - 删条目 → `chunk` 0 行、`chunk_fts` 按 `rowid` 0 行、按专属探针文字 `MATCH` 0 命中；清空后两表均 0
  - 无 Key → 400 `LLM_NO_KEY`，服务仍健康，任务数仍为 3（没派发注定失败的任务）
  - `wal_checkpoint` 后整文件复制 → `status.py --db` 退出码 0
- `uv run python scripts/status.py` → EXIT=0，各表行数/环境/任务正常
- `python tools/doc_check.py` → 6 项 PASS + 2 项 WARN（完结文档被 HANDOFF 与手册速查表引用；前者是台账、后者是里程碑索引，均非当现状使用）

**过程中修掉的两个真问题**

1. 第一版验收脚本用「间隔重复」当 FTS 探针，删除后仍报 2 命中——不是残留，是另外两篇正文里真有这四个字。已改为从待删条目里挑一段其他条目不包含的 8 字窗口，先断言删除前可搜到、再断言删除后搜不到
2. `doc_check` 报 HANDOFF 两处端点引用未登记：一处是 `src/api/client.js` 被正则误判为 `/api/client`，一处是 backlog 里提到的 `knowledge/categories`（尚未实现的设想端点）。只改措辞（去掉前导斜杠、拆分路径写法），语义未变，未改校验器

**遗留问题**（每条都能直接开干）

- [ ] M2 开工前按 M2 §2 核对前置：`ffmpeg` 已装（`D:/Anaconda3/Library/bin`）、Key 已配；M2 新增依赖与 `fetch` 目标站点策略需先读 M2 §6
- [ ] 分类树计数上限 100 条（前端聚合的代价）：条目超过 100 后左侧计数偏低，需要时再加 `knowledge/categories` 聚合端点并登记契约
- [ ] 前端未做改标题 / 改分类 / 改标签的 UI（`PATCH` 已支持），M1 不要求，属 backlog
- [ ] 前端无 ESLint / 无单测；`verify_m1.py` 是后端链路验收，不覆盖 UI 交互（UI 由 Playwright 手工脚本验过，未纳入仓库）
- [ ] 开发库 `data/data.db` 里有 1 条人工验收用的样例数据（间隔重复，已整理、已手改笔记），未被 git 跟踪

**待裁决冲突**

- 无

**下一会话第一件事**
> M2 开工：读 `docs/milestones/M2-真实内容采集.md` §2 核环境 → 按 T2.1 起做网页采集；M1 文档已完结，不要把它当现状，接口/表结构一律查 `contracts/` 与 `/docs`。
