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



