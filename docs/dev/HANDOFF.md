# HANDOFF · 进度台账

> **作用域**：只读「当前状态」+ 最后 2 条 + `00-总纲.md` + 当前里程碑文档。**不要读** `archive/*`。
> **冲突时**：本文件的"遗留问题"若与当前里程碑文档矛盾，以本文件为准（它更接近事实），并回头修里程碑文档。
> **用途**：这是唯一能真正扛住上下文压缩的东西。文档会过时，代码会变，"我上次做到哪、卡在哪、下一步做什么"只在这里。
> **规则**：
> 1. **只追加，不修改历史条目**（写错了就在新条目里更正）
> 2. 每次会话结束前必须写一条，哪怕只做了很小的事
> 3. 新会话**只读「当前状态」+ 最后 2 条**，不要从头读
> 4. "遗留问题"必须写成可执行的一句话，不要写"还需优化"
> 5. **归档**：某里程碑**已验收、且不再是下一里程碑的直接前置**时，把它的条目**原样**移入
>    `docs/dev/archive/HANDOFF-<日期区间>.md`（一个字都不改），本文件只留索引；当前里程碑的直接前置
>    （如 M5 之于 M4）先留着，等下一个里程碑验收时再移
>
> **路径变更（2026-11-08）**：本文档与 `contracts/` `milestones/` `00-总纲.md` `会话提示词手册.md`
> 一起从 `docs/` 迁到 `docs/dev/`，`docs/` 顶层只留给用户看的 `images/` 和 `README` 素材。
> 下面**历史条目里写的 `docs/xxx` 路径一律读作 `docs/dev/xxx`**（历史条目按规矩不改）。

---

## 当前状态（2026-11-27 · 每次会话结束更新这一段）

| 项 | 值 |
|---|---|
| 阶段 | **v0.4 优化线**：`docs/dev/优化方案-v0.4.md` 共 7 批。**批 1–5 已完成**（试卷重做 / 数据备份 / 已有题池 / 上工手册与版本台账 / CI），批 6 单测、批 7 P2 待开工 |
| 功能基线 | M11 已完成（v0.3 三层：识别 / 试卷 / 原件呈现）。里程碑台账在 `执行计划-v0.3-M9-M11.md` §9，各里程碑细节在 `milestones/` |
| 版本 | **0.3.7**（**五处**一致：`pyproject` / `app/version.py` / 两个 `package.json` / README 徽标；`tools/bump_version.py --check`） |
| 发布 | 最新 Release **`v0.3.7`**（2026-11-24，`Cairn-0.3.7-setup.exe` 184,465,211 B，`/releases/latest` 指向它、已进更新通道）。历史：v0.3.5 / v0.3.3 / v0.3.2 / v0.3.1 / v0.3.0 / v0.3.0-alpha.1 / v0.2.x |
| 最近验收 | 2026-11-27：**CI 三个 job 全绿**（front 16–19 s / docs 5–7 s / backend 17–24 s，run `45933146553`）· 本机 2026-11-26：`verify_m7` 99/99 · `verify_m10` 151/151 · `verify_m11` 61/61 · `verify_pool` 23/23 · `verify_backup` 33/33 · `doc_check --strict` 0 FAIL / 0 WARN · eslint 干净 · build ≈4 s（主包 415 kB / gzip 148） |
| 下一件事 | 批 6：最小单测（`pytest` ≥30 条）+ 提示词输出 schema（`优化方案-v0.4.md` §4.2）；然后批 7 P2 |
| 在线演示 | <https://chenyiming-aaa.github.io/Cairn-StudyKB/> —— `VITE_DEMO=1` 静态演示，`pages.yml` 随 main 自动重建；**仓库必须 Public**（免费账号私有仓库不支持 Pages） |
| 许可证 | MIT（`LICENSE`） |
| 台账 | 本文件只留「当前状态 + 归档索引 + 2026-11-17 起的条目」。M4–M11 在 `archive/HANDOFF-2026-11-07至11-14.md`，M0–M3 在 `archive/HANDOFF-2026-11-05至11-07.md` |

**改代码前必读的四条**（完整版与解除条件在 `00-总纲.md` §2 / §3）：

- **版本只走工具**：`tools/bump_version.py --to X.Y.Z`（**五处**，含 README 徽标），提交前 `--check`；
  只 bump 不打包时 README 要写「源码 vX / 安装包仍是 vY」。
- **体积只有一个算法**：`utils/format.fileSize(bytes, digits)`，十进制 10⁶。别再手写 `/1024`。
- **动效只走 token**（`--dur-*` / `--ease-*`）；`tokens.css` 是**生成物**，往里加东西必须同步改
  `tools/check_contrast.py`，否则下次生成静默抹掉。
- **改界面文案先读** `docs/dev/文案规范.md`，改完跑 `verify_m7`（它按禁止词逐页扫）。

## 归档索引

| 归档文件 | 内容 | 何时可丢 |
|---|---|---|
| [`archive/HANDOFF-2026-11-05至11-07.md`](archive/HANDOFF-2026-11-05至11-07.md) | M0 文档体系 / M1 后端与前端 / M2 采集 / M3 检索问答，共 26 条会话记录（含全部补丁与复核） | 永久保留（git 之外的第二份可读版本） |
| [`archive/HANDOFF-2026-11-07至11-14.md`](archive/HANDOFF-2026-11-07至11-14.md) | M4 出题判分 / M5 打包安装 / M6 主题引导 / M7 布局文案 / M8 体积更新 / M9 采集识别 / M10 试卷导入 / M11 原件呈现 + v0.3.0 发版与体积口径，共 41 条会话记录； 附录留 v0.3.0 收口与 11-09 四条裁决 | 永久保留（同上） |

> 归档口径：某里程碑**已验收、且不再是下一里程碑的直接前置**时，条目原样移入 `archive/`，本文件只留索引。2026-11-26 已把 M4–M11 全部移走（它们都已验收并发布）。

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

## 2026-11-17 · 功能价值审计的两轮收口（含番茄钟下线）

**做了什么**：按 `docs/dev/功能价值审计-2026-11-17.md` 逐条核对「每个按钮声称的事是否真的发生」，
两轮共落地 9 条收敛 + 1 条下线。

**第一轮**（commit `eb21519`）：入库后自动排队整理（`dispatch.organize_if_pending`，条件 UPDATE 抢占，
`note_edited` / `kind=exam` / 无 Key 都不排）、出题优先读整理笔记（`quizzer.material_for_item`）、
首次答对也进复习队列（`FIRST_CORRECT=2`，删 `not_tracked`）、三处「搜标题」共用 `SearchScopeHint`、
导图降为笔记页内折叠块、任务中心按「收内容 / 整理内容 / 安装组件」聚合、导航「学习」改名「导出」。

**第二轮**：**番茄钟与「学习记录」整块下线**（用户裁决）。删 `Pomodoro.vue` / `SessionLog.vue` /
`useTimer.js` / `routers/session.py` / `repo/sessions.py`，移除顶栏迷你计时器、详情页「学习记录」页签、
`startFocus`、`stats/week` 与六个 session 端点。连带：仪表盘 6 块 → 5 块、今日条 4 格 → 3 格、
「连续学习天数」改按「当天有作答或有内容被整理成 ready」算（否则永远是 0）、
`/api/stats/today` 删 `focus_seconds` / `sessions` / `week_focus_seconds` 三个字段。
`study_session` 表与历史数据保留，只是从此没有写入方。版本升到 **0.3.5**（源码，未打包）。

**验收**：`tools/regress.py --keep-going` **m1–m11 全绿 1144 条 / 8.6 分钟**
（m1 56 · m2 118 · m3 61 · m4 78 · **m5 25**（重写）· m6 83 · **m7 99** · m8 106 · **m9 306** · m10 151 · m11 61），
前端 `vite build` 通过（产物里已无被删组件的引用）。

**顺带修掉的既有缺陷**：`verify_m9.py` 的桩函数少 `timeout` 形参（`json_call` 会透传），
`§kind` 这一组 19 条**从来没跑起来过**。加一个默认形参后 `--only kind` 19/19 —— 断言本身都是对的，
只是没被执行。这类「整组静默不跑」比 FAIL 更危险：报告上只少一行数字，看不出少了 19 条检查。

**踩到的坑**：我在后台跑 `regress` 的同时又起了一个 `verify_m9`，两路同时抢识别组件与端口，
那一轮 m9 报了 173/175 两个 FAIL。**同机不要并发跑两个 m9**（`§layout` 会真起 OCR worker）；
顺序重跑 306/306，与单跑一致。别把这种失败当缺陷去改代码。

**下一会话第一件事**
> 「导出」要不要退出主导航仍是待裁决项（审计 §8.8 / §9.6）：它占第 5 个位置但属低频动作，
> 退出去得给「已生成的离线文件」另找入口，目前只有这个页面。**没动**。

---

## 2026-11-17 · v0.3.5 发版（功能收敛 + 番茄钟下线）

**产物**：`Cairn-0.3.5-setup.exe` **184,458,760 B**（184.5 MB），
sha256 `e9c66a2d5d743ada0a9bfcb131a127dba6466c999f7ba61054b55514e5c95376`，
Release <https://github.com/ChenYiming-aaa/Cairn-StudyKB/releases/tag/v0.3.5>
（`make_latest=true`、`prerelease=false`），附件 `exe` + `.sha256`（88 B）。
tag `v0.3.5` 打在 `3d9e1c4`（**被装的那份源码**），发版文档提交在 tag 之后，**不平移 tag**。

**打包链路**（本机实测耗时）：
1. `backend && .venv/Scripts/pyinstaller --noconfirm --distpath build/dist --workpath build/work cairn-backend.spec`
   —— 96 s，落盘 112 MB；spec 顺带写 `app/_build_info.py`（commit=3d9e1c4、built_at=2026-11-17T21:33:10+08:00）。
2. `frontend && npm run build` —— **必须先重建正式包**：先前验演示站跑的 `VITE_DEMO=1` 会把 demo 数据留在 `dist/`，
   直接打包会让所有用户看到演示库。构建后核对 `dist/index.html` 里没有 `cairn-demo` 标记。
3. `desktop && npx electron-builder --win nsis --publish never --config.directories.output=release-v035`
   —— 103 s；输出到**全新目录**，避开 `release/` 里 `app.asar` 被锁的 EBUSY。
4. `uv lock` → `cairn 0.3.4 → 0.3.5`，与 pyproject 一起提交（否则 lock 与 pyproject 版本对不上）。

**包内冒烟**（不装 NSIS，直接跑 `release-v035/win-unpacked/resources/backend/cairn-backend.exe --port 8799 --data-dir <临时>`）：
`/api/health` ok、`/api/version` 报 `0.3.5` + `3d9e1c4` + `2026-11-17T21:33:10+08:00`、
`/` 200 且**不含 demo 标记**、`/pdf/cmaps/78-H.bcmap` 200、
`/assets/pdf.worker.min-CIqJB0yW.mjs` 200 且 MIME **`text/javascript`**（Windows 不认 `.mjs`，这条最容易漏）、
`/pdf/wasm/openjpeg.wasm` 200 且 `application/wasm`。

**更新器验收**：`tools/e2e_update.py --only real` **4/4 PASS** —— 关于页报 `v0.3.5` + `3d9e1c4` +
`2026-11-17 21:33`，真 `api.github.com` 判「已是最新版本」（说明 `/releases/latest` 已正确指过来）。
`--only install / cancel` 两幕这次没跑（没动 `updater.js`），但**手工真装了一遍**：
`/S` 装到 `%LOCALAPPDATA%\Programs\Cairn`，502 MB，桌面与开始菜单快捷方式、卸载器都正常，验完已卸载。

**两个坑**（下次真装还会遇到）：
- 静默安装**装到 `D:\` 根目录会弹 UAC**，没人点就一直挂着（第一轮挂了 14 分钟，进程 37 MB 不动、目标目录空）；
  装到 `%LOCALAPPDATA%` 就没事。
- **装完 setup 进程不退出**：文件、快捷方式、注册项都已就位，进程仍挂着 50 MB 不动 —— 别等它，确认
  `Cairn.exe` 与 `Uninstall Cairn.exe` 都在就可以 `taskkill`，否则一条 `cmd //c` 会一直不返回。

**别忘了**：演示站与正式包用的是同一份 `frontend/src`，但 `VITE_DEMO` 不同 —— 打包前若刚验过演示站，
先确认 `frontend/dist` 是正式包再进 electron-builder。这次差点踩到，靠构建后 grep 标记挡住。

**下一会话第一件事**
> `/releases/latest` 已指向 v0.3.5，已装 v0.3.3 的用户点「检查更新」就会拿到它（全量包，不支持降级）。
> 演示站随 push 自动重建（`pages.yml`），这轮 `frontend/**` 与 fixtures 都动过，
> push 后 3–4 分钟再跑 `python tools/walk_demo.py --url https://chenyiming-aaa.github.io/Cairn-StudyKB/`。

---

## 2026-11-18 · 发版说明统一（10 个 Release 重写）

**做了什么**：新增 `docs/dev/发版说明规范.md`，并把 **v0.1.0 – v0.3.5 与 `components-v1` 全部按它重写**——
标题统一 `vX.Y.Z · 主线`（≤12 字、一条主线），正文统一 3–7 条编号点（每条 ≤15 字）+ 3–4 行固定短句
（升级 / 数据 / 安装包 / 注意）。10 个 Release 的标题与正文已 PATCH 到线上，附件与 `prerelease` 标记没动，
`/releases/latest` 仍是 v0.3.5。十个正文合计 **15,410 → 1,770 字**（编号点正文共 505 字）。

**没丢东西**：原文（理由、代码清单、验收条数、旧的作用域/读者提示块）整段搬进各自底稿的
`§3.1 旧版正文（2026-11-18 统一前）`，一个字没删。改前的线上正文备份在
`tmp/release-bodies-backup-2026-11-18.json`（内含 release id 与附件清单），要回退按它 PATCH。

**顺手补的**：`release-notes-v0.3.2.md` 与 `release-notes-components-v1.md` 原来**没有底稿**
（只在网页上贴过），这次从备份正文补出来了。

**两个坑**：
- **GitHub 把段内换行折成空格**：固定短句紧挨着写，线上会挤成一整行「升级：… 数据：… 安装包：…」。
  生成时必须**短句之间留空行**（第一版漏了，已重生成并重推）。
- **字数别靠眼睛**：稿子里「试卷识别更准」我标了 7 字实为 6，示范合计标 60 实为 61。
  脚本里加了断言（点数 3–7、主线 ≤12、每点 ≤15），跑一遍就知道哪条超了。

**下一会话第一件事**
> 发版说明按 `发版说明规范.md` 写：底稿三节（标题 / 正文 / 维护者备注），贴 Release 时只取前两节。
> 待裁决仍是「导出」要不要退出主导航。

---

## 2026-11-24 · v0.3.7 发版（状态分色、采集不再弹黑框）

**做了什么**：两件用户报的界面问题 + 一个长期在红的验收组。

**状态徽标四色**：`.badge-ready` 从与 `.badge-pending` 共用的中性变量改为 `success-soft`
淡绿底 + `success-ink` 绿字（`frontend/src/styles/app.css`）。2026-11-22 为避免「一排饱和绿胶囊
压标题」把已整理也压成中性，代价是与「待整理」视觉完全一样 —— 用户扫列表分不出哪些没弄完。
恢复绿色但用淡底，区分状态又不压标题。四态各一色：灰 / 琥珀+脉冲 / 淡绿 / 红。
`verify_m7` 的对比度断言 `badge-ready 4.82:1`、`badge-pending 6.17:1` 过 AA；README 补了四色说明。

**采集视频闪 cmd 框**：根因是后端在安装包里是**无控制台的 windowed exe**，Windows 下
spawn 控制台程序（ffmpeg）会为子进程新建窗口。运行时三处子进程里只有 `component_proc`
加了 `CREATE_NO_WINDOW`；`env_probe._version()`（每次启动/进设置就跑，所以表现为「一进来就弹」）
与 `transcriber._extract_audio()`（真转录时跑）都漏了。新增 `backend/app/subproc.py`
收拢这个常量，三处统一引用。

**verify_m6 第 8 组的长期崩溃**：它手写的 v2 老库桩 `knowledge_item` 缺 `content_hash` 列，
而 v6 迁移要 `UPDATE` 这一列 → 该组必崩，连带第 9 组（严格模式 + `/api/env/check`）永远跑不到。
`git log -S content_hash -- verify_m6.py` 零命中，说明从来没通过过。给桩补列（含 `legacy-hash`
值）+ 两条断言（唯一索引建成、唯一行哈希没被改写成 `hash:id`），85/85。

**验收**：`regress` m1 56 / m2 118 / m3 61 / m4 78 / m5 25 / m6 85 / m7 99 / m8 106 /
m9 306 / m10 151 / m11 61 全绿（共 1146）。m9 首轮 173/175 是已知的假 FAIL（PDFium
后台线程偶发 access violation，顺序重跑 306/306），不是缺陷。

**发版**：源码提交 `b2898ae`、tag `v0.3.7`（附注 tag，指向它）；安装包
`Cairn-0.3.7-setup.exe` **184,465,211 B**（184.5 MB），sha256
`9a85ca48d4d23685afaab91d47108a1eb2d70f68a1b46830445849e9e74123cc`，
`/releases/latest` 已指向 v0.3.7。包内冒烟：`/api/version` 回 `0.3.7 / b2898ae`、
`/pdf/cmaps/*` 200、`assets/*.mjs` 为 `text/javascript`、`/api/health` ok。

**坑**：从 `component_proc.py` 移除局部常量时顺手删了 `import os`，但文件别处还用
`os.environ` → `verify_m8` protocol 组 NameError、76/77。**删 import 前先搜一遍文件里
还有没有第二处使用。**

**顺手校准**：`运行与打包.md` 的验收条数表长期滞后，按本轮实跑改成
m1 56 / m4 78 / m5 25（原写 57，番茄钟下线时删了一批）/ m6 85。

**下一会话第一件事**
> HANDOFF「当前状态」段的版本行还停在 0.3.5（v0.3.6 发版时没更新，这轮也没改）；
> 待裁决仍是「导出」要不要退出主导航。

## 2026-11-26 · 全量复核与优化方案（批 1 已落地：试卷重做 + 文档闸门复位）

**起因**：`Cairn-项目分析-2026-11-26.md` 的逐条复核（`docs/dev/复核-项目分析-2026-11-26.md`：30 条断言
24 条复现、5 处修正），随后做第二轮全量体检，产出 `docs/dev/优化方案-v0.4.md`（P0 五项 / P1 四项 /
P2 七项，分 7 批，每批独立可交付）。

**批 1 做了什么**

1. **试卷「再做一遍」真的重开卷**（`frontend/src/views/Practice.vue` 的 `onRestart`）：原来无条件
   `backToIdle()`，25 题交卷后点它只会退回「还没开始」，看起来像卷子没了。现在 `paperRun` 为真时
   再 `await startPaper()` 重新取题。实测（真实库副本 + Chrome 全流程）：25 题答完、交卷 5/25 →
   点「再做一遍」→ **第 1 / 25 题**，console 无错误。生成的题组仍回配置（题是现出的，要重选题型与题数）。
2. **文档闸门复位**：`tools/doc_check.py --strict` 从 **10 FAIL + 1 WARN** 回到 **0 FAIL / 0 WARN（退出码 0）**。
   - 4 份审计文档补作用域块（`交互断裂清单-v0.4`、`功能价值审计`、`动效审计`、`视觉与动效一致性审计`）；
   - 3 个真实端点补进 `接口契约.md`（`GET`/`POST knowledge/{id}/ocr`、`GET review/pending`、`GET tasks`），
     契约登记端点 66 → **69**；
   - 3 处「不是端点形状」的写法改成可核对的形状（`\d+` / `${id}` / `tasks/*`），**闸门规则一行没改** ——
     以后写模板路径用 `{id}` 或去掉 `/api` 前缀，否则会被判成未登记端点；
   - WARN：`会话提示词手册` 里程碑速查表里的 M1 改成「已完结，文档留在 `milestones/`」，不再被当作现状；
   - `交互断裂清单` 13 条施工单各加一行「状态：已完成」（正文 checkbox 保留施工时原样，阅读入口写进
     作用域块），§9 / §10 的完成记录不动。
3. **回归**：`verify_m10` 151/151（2.5 s）、`verify_m11` 61/61（12 s）、`eslint` 干净、
   `vite build` 5.0 s（主包 412.45 kB / gzip 147.09、pdf 分块 501.34 kB 懒加载）。

**下一会话第一件事**
> 批 2（启动时 `VACUUM INTO` 自动备份 + 设置页「立即备份」，保留 7 份）尚未开工；
> 批 3（已有题池，`做已有题（N）`）要改同一个 `Practice.vue`，按 `优化方案-v0.4.md` §7 的顺序别并成一次提交。

## 2026-11-26 晚 · 批 2：数据备份（三条判据先落、再实现）

**判据先落**：`backend/scripts/verify_backup.py`（33 条，离线，约 6 秒）。三组：
- `§flow` 当天不重复 + 备份真的可用（标准 sqlite3 能打开、`knowledge_item` 行数与源库相同、
  `integrity_check` 为 ok）；
- `§keep` 只留 7 份，删的是最旧的那些，且**只认 `data-YYYYMMDD.db`**（`readme.txt`、`data-notadate.db`
  一个都没动）；
- `§failure` 备份失败不阻塞启动：`run()` 如实抛错 → 启动钩子不抛 → 真起一个服务（坏的数据目录）
  `/api/health` 200、`/api/settings/backup` 200 且 `last` 为空。

**判据逼出来的两处认知修正**（不写下来下次还会踩）：
1. **`already_today` 的优先级高于 `recent`**：同一天里 `recent` 分支**不可达**，原方案把两者写成并列条件。
   要验 `recent` 必须造「跨天 + mtime 23 小时前」；我第一次直接断言「第二次调是 recent」，
   实际返回 `already_today` —— 判据错，不是实现错。
2. **Windows 上 `integrity_check` 那条内联连接没关会导致 WinError 32**：验完文件还被占用，后面 rename
   就失败。凡是「开库 → 验 → 改名」的脚本，连接必须 try/finally close。

**实现**：`services/backup.py`（`VACUUM INTO` 快照 / `KEEP=7` / `INTERVAL_HOURS=24` / 只删自己命名的文件 /
失败删掉半份不留残骸）、lifespan 里 `db_backup.maybe_start()`（daemon 线程，内部吞异常只记 warning）、
`GET`/`POST /api/settings/backup`、关于页新增「备份」块（上次备份 / 备份位置 / 立即备份）。
关于页原来那句「备份就是复制这个文件夹」删了 —— 已经有按钮再说这句会自相矛盾。

**实测**：`verify_backup` 33/33；真库副本 + Chrome 走查：「上次备份 11-26 22:22 · 4.1 MB」→ 点「立即备份」→
「今天已经备过了，一天只留一份」（目录仍 1 份）→ 删掉 `backup/` 再点 →「已备份（4.1 MB）」，
console 无错误。真实 4.6 MB 库 VACUUM 后 4.1 MB。
**回归**：`verify_m7` **99/99**（含「设置·关于 没有禁止词」）、`verify_m10` 151/151、`verify_m11` 61/61、
`doc_check --strict` 0 FAIL / 0 WARN、eslint 干净、build 4.8 s。

**下一会话第一件事**
> 批 3（已有题池：`GET knowledge/{id}/questions` + 练习页「做已有题（N）」）—— 要改同一个 `Practice.vue`，
> 与批 1 分开提交。另：批 5 做 CI 时把 `verify_backup.py` 一起挂上（6 秒、离线，比 m4/m10 还便宜）。

## 2026-11-26 深夜 · 批 3：已有题池（做已有题）

**判据先落**：`backend/scripts/verify_pool.py`（23 条，离线，约 2 秒，不调模型）。四组：
- `§count` 没有题回空 / 出 5 题回 5 / 再出 5 题回 10，且**老题 id 一个都没变**（要的是重做同一批，不是换一批）；
- `§order` 导入题在前按题号数值序（1, 2, 10）、模型题在后按入库顺序；
  `origin='imported'` 但题号被摘掉的残留题**不出现**；
- `§shape` payload 是 dict、question/options/answer/explanation 都在、选项已剥自带 `A.` 前缀；
- `§edge` 不存在的 id → 404 `ITEM_NOT_FOUND`；同一份试卷上按卷练 3 道 / 题池 4 道（口径差异是设计）。

**方案没写、实现时补上的一条**：`origin='imported' AND number IS NULL` 必须排除。那是
`exam/commit._drop_unused` 在「用户删了这道题、可它还有作答记录」时摘掉题号的残留，
题池不筛它等于「删了又冒出来」。只筛 `number IS NOT NULL` 又会把模型出的题（题号本来就空）全滤掉，
所以判据写成 `origin <> 'imported' OR number IS NOT NULL`。

**实现**：`repo/questions.list_for_item()`（排序 + 上面那条筛选）/ `GET /api/knowledge/{id}/questions`
（没题回 `total: 0` 而不是 404 —— 否则练习页每次选中一条没出过题的内容都要处理一次异常）/
练习页 `watch(itemId)` 取计数（`poolSeq` 丢弃过期回包，避免快点材料时慢回包盖掉后选的）、
`startPool()`、`poolRun` 与 `paperRun` 分开（题号只有试卷有）。

**一处与方案原文不同**：方案写「点下去 `paperRun = false`」，照做之后交卷页的按钮会变成
「回配置再出一组」——那句话会让人以为要重新花钱出题。改成 `poolRun` 单独记，
`onRestart` 里 `paperRun → startPaper` / `poolRun → startPool`，两种都是「再做一遍」。

**实测**（`verify_pool` 23/23；真库副本 + Chrome）：选「用图书管理系统讲透真实工程架构」（库里 10 题）→
按钮 `做已有题（10）` → 开卷 `第 1 / 10 题`、首题题干与接口一致 → 答完交卷 → 点「再做一遍」→
**回到 `第 1 / 10 题`**；选试卷 → 没有这颗按钮、`按卷练` 仍在（1 颗）。console 无错误。
**回归**：`verify_m10 --only paper` 8/8、`verify_m11` 61/61、`verify_m7` 99/99、
`doc_check --strict` 0 FAIL / 0 WARN（登记端点 69 → 71）、eslint 干净、build 4.0 s（主包 415.36 kB / gzip 148.03）。

**批 3 收尾补修（同日）**：配置栏拖到最窄 240px 时，`出题：<长标题>` 那颗主按钮的
`white-space: nowrap` 会把文字顶出按钮边框、硬切成半个字，既没有省略号也没有 title。
修法：`.cfg-foot` 里三颗按钮的文字统一包进 `.btn-label`（`flex:1 1 auto` + `min-width:0` +
`overflow:hidden` + `text-overflow:ellipsis`），按钮各自带完整文案的 `title`。
判据（真实库副本 + Chrome，`--w-config` 240/300/400 三档）：label 的
`scrollWidth > clientWidth` 只允许出现在窄栏且必须有非空 title；label 左右边界必须落在按钮内容区内；
400px 宽栏不许截断。三档全 OK，console 无错误。

**下一会话第一件事**
> 批 4（`AGENTS.md` 上工手册 + §4.3 版本与台账单一事实源）。另：批 5 做 CI 时把
> `verify_pool.py`（2 秒）与 `verify_backup.py`（6 秒）一起挂上，比 m4/m10 还便宜。

## 2026-11-26 夜 · 批 4：AGENTS 上工手册 + 版本/台账单一事实源

**A. `AGENTS.md` 追加「上工手册」**（AOCI 段**一字未动**，接在 `<!-- aoci:end -->` 之后）
- 五条命令：起后端 / 起前端 / `tools/regress.py` / `doc_check.py --strict` / `npm run lint && build`，
  另列四条秒级离线验收（`verify_pool` 23 · `verify_backup` 33 · `verify_m4` 78 · `verify_m10` 151）；
- 目录地图 8 行（`routers` 18 个 / `services` 按能力 / `db` 无 ORM / `views` 10 页 / `components` 16 + 5 组 /
  `styles` 的 `tokens.css` 是生成物 / `backend/scripts` 按里程碑 / `docs/dev` 各文件）；
- 九条红线各一行，注明完整版与解除条件在 `00-总纲.md` §2、第 3–6 条另见 ADR-020；
- 动代码前四条：总纲 §2/§3、ADR、契约（改端点/改表）、`文案规范.md`（改界面），外加「改版本只走工具」。

**B. 版本单一事实源：`tools/bump_version.py` 加第五处（README 徽标）**
- 之前它只核 pyproject / `app/version.py` / 两个 `package.json`，徽标停在 **0.3.4** 而代码 **0.3.7**，
  `--check` 一路绿 —— 这次纳入后立刻报红，再用 `--to 0.3.7` 统一。
- 徽标正则必须**非贪婪吃到 `-green.svg`**：写成 `\d+\.\d+\.\d+` 的话预发布版 `0.3.0-alpha.1`
  只会抓到 `0.3.0`，每跑一次 `--to` 就把 `-alpha.1` 漏在外面。README 正文里的「当前版本（v0.3.7）」
  是历史叙述，不归工具管（只动 `badge/version-X.Y.Z-green.svg` 一处）。
- **`verify_m8` §5.2 的断言原来等于没验**：`all(line.split()[-1] not in ("", "(未读到)") for line in tail)`
  遍历的是整段输出，README 那一行整个消失也照样过 → 改成**列名单**（五个文件逐个断言行存在且读到了）。
  106 → 110 条。

**C. HANDOFF 归档 + 当前状态重写**
- 原文 **2904 行**，其中 M4–M11 共 **41 条**会话记录（178–2657 行）整段原样移入
  `archive/HANDOFF-2026-11-07至11-14.md`；搬完用 sha256 校验「归档正文 == 原文件切片」、
  「新文件尾部 == 原文件尾部」，一个字都没改。现在 **330 行**。
- 「当前状态」原来 118 行、日期停在 **11-13**，表格里塞着 M9/M10/M11 的完整实现细节与 v0.3.0 收口，
  第一屏看不到「现在是什么版本、下一步做什么」。重写为 9 行现状表（阶段 / 功能基线 / 版本 / 发布 /
  最近验收 / 下一件事 / 演示站 / 许可证 / 台账）+ 四条硬约定；那两段历史（v0.3.0 收口、体积口径来龙去脉、
  v0.3.1 打包、M9 收口、11-09 四条裁决）**原样**移进归档文件的「附录 · 当期状态快照」。
- 顺手纠正两处过期事实：**最新 Release 是 `v0.3.7`**（GitHub API 核实，`Cairn-0.3.7-setup.exe`
  184,465,211 B，`/releases/latest` 指向它），原表写的 v0.3.5 已落后两个版本；标签行补 `v0.3.7`。

**D. `docs/dev/运行与打包.md` 加「发版后要更新的几处」**
- 版本号一个入口（五处）、README 正文三句、HANDOFF 当前状态三行、Release 底稿、GitHub Release、
  打标签指「被装的那份源码」，各配一句「怎么确认」；并写明「只 bump 不打包时两处都要写源码 vX / 安装包 vY」。

**验收**
- `bump_version --check`：徽标改回 0.3.4 → **exit 1**；恢复 0.3.7 → exit 0（五处一致）。
- `verify_m8` **110/110**、`doc_check --strict` **0 FAIL / 0 WARN**（47 份文档，归档文件不计入）。
- 新会话只读 `AGENTS.md` 即可：起服务、跑回归、知道改文案要读 `文案规范.md`、知道版本只能走工具。

**下一会话第一件事**
> 批 5 CI（`.github/workflows/` 三个 job）。注意 `npm run e2e` 写死了 `D:\Anaconda3\python.exe`
> （`frontend/package.json`），上 CI 前先改成 `python`，否则在 runner 上必然找不到。

---

## 2026-11-27 · 批 5 CI + 填掉批 1–4 留下的两个坑

**A. CI：`.github/workflows/ci.yml`，三个 job（PR #1，run `45933146553` 全绿）**
- `front` 16–19 s：`npm ci` → lint → build → 挡「演示数据进了 dist」。
  闸门的判据不是空话：`VITE_DEMO=1` 构建产物里确实有 `cairn-demo` 标记（在 `assets/index-*.js`），
  正式构建里没有 —— 两头都验过。
- `docs` 5–7 s：`doc_check --strict` + `bump_version --check`，纯标准库。
- `backend` 17–24 s：`uv sync --frozen` 跳过 17 个包（torch / triton / `nvidia-*`），
  再跑 `verify_pool` 23 + `verify_backup` 33 + `verify_m4` 78 + `verify_m10` 148（CI 上少 3 条，
  真样本 `samples/` 按 `.gitignore` 不入库、走 SKIP）。
- 方案 §8 那句「CI 冷装耗时未实测」现在有数了：**首次 20–24 s、命中 `setup-uv` 缓存 17 s**。
  torch 在 linux 上约 4 GB，跳过它才是这个数量级的前提；不跳过的话磁盘和时间都吃不消。
- 坑：**CI 里不能 `uv run`** —— 它会先按锁文件 sync 一遍，把跳过的包又装回来。job 里直接调 `.venv/bin/python`。

**B. 坑一：`npm run e2e` 写死 `D:\Anaconda3\python.exe`**
- 换成 `node e2e/run.mjs`：按 `CAIRN_PYTHON` → `backend/.venv` → `python3` / `python` / `py -3` 依次探测，
  **每个候选真起一次浏览器**才认（包在、浏览器版本对不上时 import 成功、launch 才报错，只验 import 等于没验）。
- Windows 下探测不能走 `python -c`：带换行与引号的 `-c` 会被重新切词（实测 `py -3` 报一串乱码），
  改走 stdin（`python -`）。
- 顺带给仓库 venv 装了 chromium（`PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`；
  直连 `cdn.playwright.dev` 实测 10 分钟停在 0%），本机不再依赖 Anaconda。

**C. 坑二：`tools/regress.py` 只扫 `verify_m*.py`**
- 批 2 / 批 3 新建的 `verify_pool` / `verify_backup` 从来没被「一条命令回归」带上过。
- `discover()` 改为扫全部 `verify_*.py`：里程碑按编号排、`EXTRA` 里的排最后；
  `--only` 同时认 `10` / `m10` / `pool`；`--from` / `--to` 仍只管里程碑（补某一段时不顺带跑补丁套件）。

**D. CI 第一次红就抓到一个真缺陷：`verify_m4` 依赖本机根目录 `.env`**
- 出题接口先判「有没有 Key」，没 Key 直接 400 不抛流 → 事件流是空的 → `events[-1]` IndexError，
  报错离根因很远。本机有真 Key 时永远看不出这件事。
- 修法照 `verify_m10`：往临时数据目录写一份假 Key（模型调用本来就全被打桩）。
- 但假 Key 又让 `organize_if_pending` 多了「有 Key」这一条件 → 建条目时排一条真去调模型的整理任务，
  401 重试三轮、脚本收尾删目录后它还在写 → `llm_call_log 写入失败：OperationalError`。
  断言照样绿、绿里全是噪音 —— 用本来就存在的 `CAIRN_NO_AUTO_ORGANIZE=1`（`verify_m1` 早就在用）关掉。
- 复现方式：`CAIRN_ENV_STRICT=1` 模拟「没有根 `.env`」，本机 78/78。

**E. 红/绿双向验证（方案 §4.1 的验收判据）**
- 故意改坏 `Practice.vue` 一个字符 → `front` 红（lint 拦住）；把 `review.next_interval` 的 ×2 改成 ×3
  → `backend` 红在 `失败：连续答对间隔 1→2→4→7`（77/78）；`docs` 仍绿。回滚后全绿。

**下一会话第一件事**
> 批 6：最小单测（`pytest` ≥30 条）+ 提示词输出 schema。三类边界见 `优化方案-v0.4.md` §4.2。
