# Cairn

> cairn /kɛərn/ · 登山者沿途堆的石堆路标。走一段留一块石头，靠自己堆的标记找得回来。

个人自用的学习闭环工具：把文本 / 网页 / 视频采集进本地知识库，由 LLM 自动分类、摘要、结构化，
形成可阅读、可检索、可生成学习页、可出题练习的知识资产，并用番茄钟记录学习时间。

**当前状态**：**M5（计时与交付）进行中**——T5.1–T5.5 已完成：
番茄钟（时间戳口径 / 暂停 / 提前完成 / 放弃 / 结束写笔记 / 刷新恢复 / 15 秒心跳）、顶栏迷你计时器、
条目与练习页「开始专注」、条目学习记录、仪表盘（6 区块 + 原生 CSS 周条形图）、`verify_m5.py`（50/50）；
**后端已能打成单目录 exe，桌面壳会拉起它并加载同源页面，`npm run dist` 能出 407MB 的 NSIS 安装包**
（2026-11-08 实测：打包后首屏 4126ms、关窗无残留进程、首次启动自动建库）。
**首次引导与安装段文档（T5.7–T5.8）未完成**，安装包也**还没在本机真装过**，所以暂不对外发。
M1–M4 已验收（tag `m1-done` / `m2-done` / `m3-done` / `m4-done`）。

**已能做什么**：网页链接与视频链接都能入库（网页走 trafilatura 抽正文，视频优先用自带字幕，
没有字幕才走 yt-dlp + faster-whisper 转录）；「检索问答」页里可以
① 对整库提问，答案分条并带 `[n]` 引用，点引用/来源卡片直接跳到原文那一段并高亮；
② 直接搜原文片段，两字词也能搜（自动走 LIKE），命中的关键词高亮、标出 `fts`/`like`/`vector`；
③ 每次问答（含"库里没有"）自动存进「历史」抽屉，点一条就恢复当时的问题、答案与来源，
**不会重新调模型**，也可以单条删除。
检索是 FTS5（trigram）+ bge 向量两路召回再 RRF 融合，向量不可用时自动降级为纯全文检索
（全文零命中时向量还要过距离阈值，否则判"库里没有"直接短路，不调模型）。
④ 条目详情第 4 个 Tab「思维导图」按笔记标题层级现场出图（纯 Python 手写 SVG，不缓存）；
⑤ 「学习页」页里多选条目 → 生成一份**单文件离线** HTML（内联样式 + 内嵌导图 + 代码高亮）→
iframe 预览 → 下载分享，历史产物可回看与删除。
⑥ 「练习」页：选一条 ready 条目 → 选题型（单选/多选/判断/简答）、难度、题数（5/10/20）→
**题面逐题流式浮现**（可中途停止，已收到的题留着）→ 一题一屏作答，答完立刻看到对错与解析 →
交卷后出总分/正确率与逐题回看。出题只依据材料（按 chunk 等距抽样覆盖全文）、坏 JSON 单题跳过、
题数不足逐题补生成、同题撞指纹复用不重复入库；客观题判分在后端（多选按集合、顺序无关），
简答走 LLM 批改给出"你提到了…但漏了…"，批改失败落 `is_correct = NULL`（**待人工判断**，不冤枉人）。
⑦ 「复习」页：答错的题按 1 → 2 → 4 → 7 → 15 天自动回来（`due_at` 存 UTC，比较在 Python 侧），
今日到期一次最多 20 题，直接进入作答；「错题本」标签页列出**最近一次仍答错**的题，复习答对即移出。
⑧ 番茄钟：条目详情或练习页点「开始专注」（带入条目标题），或顶栏「专注」开一轮自由专注；
15/25/50 分钟可选，可暂停/继续/提前完成/放弃，到点先冻结时长再让你写一句笔记；
顶栏迷你计时器显示剩余时间，**刷新、切页面、重启后端都不会重置**（时长以 `start_time` 推算，
15 秒心跳兜底强杀），一轮结束后出现在该条目的「学习记录」页签里。
⑨ 「仪表盘」页：今日待整理 / 今日待复习 / 连续学习天数 / 今日正确率 / 本周专注（原生 CSS 条形图，
7 天）/ 分类分布，数字全部由后端按固定口径算好，前端不做二次统计。

`verify_m1.py` 50/51（见 `HANDOFF.md` 2026-11-07 那条：有一条断言写死任务数 3，与实际 11 不符，
属既有脆弱断言，未修）、`verify_m2.py` 116/118（同样两条 `force` 用例在 HEAD 上就红）、
`verify_m3.py` 61/61、`verify_m4.py` 69/69 PASS。

## 目录

| 目录 | 内容 |
|---|---|
| `backend/` | FastAPI + SQLite；表结构与端点在 `docs/contracts/`，脚本在 `backend/scripts/` |
| `frontend/` | Vue 3 + Vite；`e2e/` 是浏览器回归，`src/styles/tokens.css` 是唯一配色/间距来源 |
| `desktop/` | Electron 壳（`main.js`）：spawn 后端 → 随机端口 + HTTP 握手 → 窗口加载 `http://127.0.0.1:<port>/`（**页面与 `/api` 同源，不走 file://**）。dev 用 `uv run python -m app`，打包后用 `resources/backend/cairn-backend.exe`；后端起不来时加载 `error.html` 兜底页而不是白窗。**图标/签名/托盘/自动更新、NSIS 安装包都还没做**，见 `docs/HANDOFF.md` |
| `tools/` | `doc_check.py` 文档一致性检查；`prepare_ffmpeg.py` 把本机 ffmpeg 全套（exe + 7 个 DLL）复制进 `desktop/resources/ffmpeg/` 供打包 |
| `data/` | 开发期数据库与日志，**永不入库** |
| `docs/` | 总纲、契约（数据/接口/ADR）、里程碑、进度台账 |

## 技术栈

Python 3.12 · FastAPI · SQLite（FTS5 + sqlite-vec）· bge-small-zh-v1.5 · Vue 3 · Electron
采集侧：trafilatura + httpx（网页）· yt-dlp + ffmpeg + faster-whisper（视频）

## 先读这些

| 文件 | 作用 |
|---|---|
| [`docs/00-总纲.md`](docs/00-总纲.md) | **入口**。红线、技术栈、里程碑地图、会话工作法 |
| [`docs/milestones/`](docs/milestones/) | 每个里程碑的自包含执行文档 |
| [`docs/contracts/`](docs/contracts/) | 数据契约、接口契约、决策记录（ADR） |
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | 进度台账：顶部「当前状态」表 + 最近条目（每次会话结尾追加） |
| [`docs/archive/`](docs/archive/) | 归档：已完结且不再是前置的里程碑台账、v1.0 规格书。**只做追溯，不读** |

## 开发约定

- 技术栈定版见 `docs/00-总纲.md` §3，更换需先在 `决策记录.md` 追加 ADR
- 红线见 §2，四条技术限制的解除条件见 §2.1
- **每次完成改动后同步更新本 README**（当前状态、配置项、目录与用法），停更就等于写错；总纲 §6 已把它列为收尾动作之一
- **每次 commit 都要推到 GitHub**：`git push origin main`，有标签再 `git push origin --tags`。别攒到里程碑结束——本地提交不算交付。推送要用 `"C:\Program Files\Git\cmd\git.exe"`，PATH 里的 WorkBuddy 精简版 git 缺 `git-remote-https`，`git push` 会直接报错

## 验证

| 命令 | 验什么 | 何时跑 |
|---|---|---|
| `python tools/doc_check.py` | 文档一致性（作用域、ADR/端点/表引用、完结标记） | 改文档后、每次会话开场 |
| `cd backend && uv run python scripts/status.py` | 数据目录 / 表行数 / 最近任务 / 环境自检（只读） | 每次会话开场与收尾 |
| `cd backend && uv run python scripts/env_check.py` | ffmpeg / whisper / embedding / sqlite-vec / LLM Key（`--json` 机读，`--strict` 有阻塞项即 exit 1） | 排查"转录跑不起来" |
| `cd backend && uv run python scripts/verify_m1.py` | M1 后端链路 51 项（含分类聚合端点），真实 LLM 调用 | 动到条目 / 整理 / chunk |
| `cd backend && uv run python scripts/verify_m2.py` | M2 采集链路 118 项：网页/视频成功、去重、force、三类抓取失败、未登记 5xx 归类、四阶段进度、重试、并发、僵尸任务、字幕选取/解析/降级（**默认全用假 fetcher/transcriber，不打真实站点**） | 动到采集 / 任务状态机 / 字幕 |
| `cd backend && uv run python scripts/verify_m2.py --online` | 上面 118 项 + 16 项真实链路：两个公开页真抓、真 404、真去重（**要外网，断了会红**） | 动到 fetcher / 抽取库 / 降级策略，或验收前 |
| `cd backend && uv run python scripts/verify_m3.py` | M3 全链路 61 项：导图层级/折叠/转义/与笔记同步、学习页落库/内联样式/内嵌 SVG/净化与 XSS/断网自包含/下载、短词 LIKE、空检索不调模型、SSE 三事件顺序（**向量关闭 + LLM 用假实现**，不联网不烧钱） | 动到导图 / 渲染 / 检索 / 问答 |
| `cd backend && uv run python scripts/verify_m4.py` | M4 全链路 69 项：增量括号扫描、逐题 emit、坏 JSON/越界答案/缺解析/重复只跳该题、补生成、撞指纹复用、多选乱序与少选、单选归一、判断布尔、空答案、简答反馈、批改失败落 NULL、错误码归一（超时/额度/其他 HTTP）、选项不带字母前缀（生成侧与读取侧都剥）、复习间隔 1→2→4→7→15、时间旅行查到期、错题本进出、参数校验（**出题与批改全用假实现**，不联网不烧钱） | 动到出题 / 判分 / 复习队列 |
| `cd backend && uv run python scripts/verify_m5.py` | M5 计时与统计 50 项：start 并发 409 / current / 心跳卷账与锚点 / 暂停不计时 / finish 幂等与笔记 / abandon 不计入专注 / >4h 启动清理（模拟重启）/ 学习记录过滤 / `stats/today` 与**独立写的 SQL 聚合**逐项对账 / `stats/week` 七天与合计 / 口径边界（昨天的 pending 不算、NULL 不进分母、分类前 8、连续天数今天没学不算断）（**临时库，不联网不烧钱**） | 动到计时 / 统计 / 仪表盘 |
| `cd backend && uv run python scripts/backfill_embed.py` | 全库补向量（幂等，只处理缺向量的 chunk）；`--stats` 只看覆盖率 | 首次启用向量、换 embedding 模型后 |
| `cd frontend && npm run lint` | 前端正确性问题（未定义/未使用变量、Vue 必备规则） | 改前端后 |
| `cd frontend && npm run build` | 可构建 | 改前端后 |
| `cd frontend && npm run e2e` | 浏览器端到端 24 项（需先起前后端，真实 LLM） | 动到 UI 主流程 |
| `cd frontend && D:/Anaconda3/python.exe e2e/m4_quiz.py --db <副本库>` | M4 练习页 19 项：5 道单选逐题浮现（每 200ms 采卡片数）、答完立即见对错与解析、选项字母只出现一次、结果页 N/5、复习角标与接口一致（需先起 8757 + 5174，真实 LLM 1 次调用） | 动到练习/复习页 |
| `cd desktop && npm start` | Electron 壳（dev）：spawn 后端 → 端口握手 → 窗口显示真实 UI（`http://127.0.0.1:<port>/`，页面与 `/api` 同源、无 CORS）→ 关窗后无 python 残留（日志 `desktop/_smoke/shell.log`，含握手耗时与首屏耗时） | 动到桌面壳 / 后端启动方式 / 静态挂载 |
| `cd backend && uv run pyinstaller --noconfirm --distpath build/dist --workpath build/work cairn-backend.spec` | 把后端打成 `build/dist/cairn-backend/`（onedir，windowed，约 965MB） | 改了后端代码、要在桌面端验证 |
| `cd desktop && npm run pack` | 打可执行目录（`electron-builder --dir`，不出安装包），产物在 `desktop/release/win-unpacked/Cairn.exe` | 验证"打包后能不能真跑起来" |
| `cd desktop && npm run dist` | 出 NSIS 安装包 → `desktop/release/Cairn-<版本>-setup.exe`（约 407MB，2 分钟） | 交付前 |

跑桌面壳前**必须先 `cd frontend && npm run build`**：没有 `frontend/dist` 时后端不挂静态路由，
窗口会白屏（后端本身不会报错，只是 `GET /` 返回 404）。

空壳验证加 `SMOKE_AUTOCLOSE_MS=5000` 会自动关窗并截图到 `desktop/_smoke/window.png`，便于非交互地验证。

> **本机跑 Electron 必须去掉 `ELECTRON_RUN_AS_NODE`**：WorkBuddy 的 shell 里默认带
> `ELECTRON_RUN_AS_NODE=1`，带着它启动 `electron.exe` / `Cairn.exe` 会退化成纯 Node，
> 报 `Cannot read properties of undefined (reading 'isPackaged')` 且不写日志（看起来像"打包坏了"）。
> 一律用 `env -u ELECTRON_RUN_AS_NODE <exe>` 启动。
>
> 装依赖与打包都必须走镜像：npm 加 `--registry=https://registry.npmmirror.com`
> （直连卡 19 分钟，镜像 38 秒），electron-builder 二进制加
> `ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/`。

`verify_m1.py` 与 `npm run e2e` 都会真的调模型（各约 1–3 次调用），别当免费工具循环跑。
`verify_m3.py` 与 `verify_m4.py` 全程不联网：前者 `VECTOR_ENABLED=0` + 假 `asker.stream`，
后者把 `quizzer.stream` 与 `llm.chat` 都换成假实现，可以随便跑。
`verify_m4.py` 的"待复习永远为空"用**时间旅行**验（直接改 `due_at` 或给仓库函数传 `now`），不改系统时间。
`verify_m2.py` 默认全程注入假实现，不访问外部站点、不调模型，可以随便跑；只有加 `--online` 才发真实请求（两个公开页 + 一个 404）。
前端 lint 只查正确性、不管格式：无分号、单引号这类风格靠人守。

## 配置

复制 `.env.example` 为 `.env`，填入 API Key（`.env` 已被 gitignore，永不入库）：

```bash
cp .env.example .env
```

必填项只有 `LLM_API_KEY`，其余已有默认值。取 Key：https://platform.deepseek.com → API keys → 创建。

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com` —— **注意 DeepSeek 不带 `/v1`**，换服务商时必改 |
| `LLM_MODEL` | `deepseek-flash`（另有 `deepseek-v4-pro`） |
| `LLM_EFFORT` | 思考档位 `low`／`high`／`max`，结构化任务用 `low` 省钱 |
| `FFMPEG_DIR` | 本机 ffmpeg 在 Anaconda 下，显式指定避免 IDE 启动时找不到 |
| `HF_ENDPOINT` | **别删**。直连 HuggingFace 不通，模型靠这个镜像下载 |
| `YTDLP_COOKIES` | 可选。Netscape 格式 `cookies.txt` 的绝对路径。留空则用登录助手写出的 `data/cookies.txt`。**一般不用手工配**：在采集面板点「站点登录 → B 站」即可，见下 |
| `BROWSER_CHANNEL` | `msedge`（默认）。浏览器渲染用的通道，可选 `chrome`；置空则用 playwright 自带 Chromium（需先 `playwright install chromium`） |
| `BROWSER_HEADLESS` | `1`（默认）。置 `0` 时渲染也弹窗口，排障用 |
| `VECTOR_ENABLED` | `1`（默认）。置 `0` 时检索只走 FTS/LIKE：问答照常可用，前端提示「向量不可用，已降级」。sqlite-vec 加载失败时同样自动降级，不用改这里 |
| `EMBED_MODEL` | 默认 `BAAI/bge-small-zh-v1.5`。**换模型必须重建向量**（维度变了），见 M3 §6.3 |
| `CAIRN_API_TARGET` | **只给前端开发用**（不是 `.env` 变量，是启动 Vite 时的环境变量）。默认 `/api` 反代到 `127.0.0.1:8756`；想在另一个后端实例（比如 8757 上的联调实例）上跑 UI 时设它，别去改 `vite.config.js` |
| `CAIRN_WEB_DIR` | **只给 Electron 壳用**。后端启动时若该目录下存在 `index.html`，就挂 `/assets` 并让 `GET /` 返回它（页面与 `/api` 同源，绕开 `file://` 的 `null` origin）。默认 `frontend/dist`；目录不存在时整段跳过，不影响 dev 与 API |
| `VECTOR_MIN_DISTANCE` | `1.05`（默认）。全文零命中时，向量最近片段的 L2 距离须 ≤ 此值才算命中，否则判「库里没有」直接返回空（不调模型）。调大更宽松、调小更严格；实测库内语义查询 0.958 能过、库外问题 1.10–1.17 被挡 |

> **站点登录**：需要登录才给内容的站点（B 站字幕、知乎受限页）在采集面板的「链接采集」里
> 点「站点登录」即可。后端会弹一个**独立**的浏览器窗口，登完自动导出 cookie 并立即生效，
> 不用改 `.env`、不用重启，也不碰你日常用的浏览器。
> 知乎这类站点光有 cookie 不够（它拦的是浏览器指纹），所以网页抓取在 httpx 失败时会
> 自动改用同一个浏览器渲染再抓一次，多花 3–5 秒。


> 语音模型不是环境变量：视频采集时由请求体 `model` 决定（默认 `small`），
> 首次使用自动下载到 `data/models/whisper/`（约 500MB，删了下次会重下）。
>
> 向量模型也不是环境变量：`BAAI/bge-small-zh-v1.5` 首次使用自动下载到
> `data/models/embedding/`（约 100MB，走 `HF_ENDPOINT` 镜像）。入库与改笔记后由
> `index_embed` 任务在后台补向量，不卡采集；首次启用或换模型时跑一次
> `scripts/backfill_embed.py` 把历史 chunk 补齐。
>
> 字幕优先是**默认行为**，不需要开关：有中英字幕就用，没有就转。人工字幕优先于自动字幕，
> 简体优先于繁体。任务 `output_json.source` 会标明这次走的是 `subtitle` 还是 `asr`。

> API 规范以 https://api-docs.deepseek.com 为准，本表核对于 2026-11-05。

## 数据与备份

开发期所有数据在 `data/data.db`；**打包后固定在 `%APPDATA%/Cairn/`**（不是安装目录，
否则卸载即丢数据，装在 `Program Files` 下还写不进去）。一个目录装下全部：

| 路径 | 内容 |
|---|---|
| `%APPDATA%/Cairn/data.db` | 数据库（知识条目、题目、计时记录） |
| `%APPDATA%/Cairn/logs/app.log` | 后端日志，按天滚动留 14 天 |
| `%APPDATA%/Cairn/logs/shell.log` | 桌面壳日志（握手耗时、首屏耗时、后端退出码） |
| `%APPDATA%/Cairn/models/` | 向量 / 语音模型缓存（各约 100MB / 500MB） |
| `%APPDATA%/Cairn/.env` | 打包后读的配置（开发期读项目根 `.env`） |

备份 = 复制这个目录（至少 `data.db`）。`data/` 已在 `.gitignore` 中排除，**永不入库**。
