# Cairn

> cairn /kɛərn/ · 登山者沿途堆的石堆路标。走一段留一块石头，靠自己堆的标记找得回来。

个人自用的学习闭环工具：把文本 / 网页 / 视频采集进本地知识库，由 LLM 自动分类、摘要、结构化，
形成可阅读、可检索、可生成学习页、可出题练习的知识资产，并用番茄钟记录学习时间。

**当前状态**：M3（检索与学习页）**已验收**（2026-11-07，tag `m3-done`）—— T3.1–T3.12 全部完成，
`verify_m3.py` 61/61 PASS。M1、M2 已验收（tag `m1-done` / `m2-done`），下一个里程碑是 M4（出题与练习）。

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
`verify_m1.py` 51/51、`verify_m2.py` 115/115（`--online` 131/131）、`verify_m3.py` 61/61 PASS。

## 目录

| 目录 | 内容 |
|---|---|
| `backend/` | FastAPI + SQLite；表结构与端点在 `docs/contracts/`，脚本在 `backend/scripts/` |
| `frontend/` | Vue 3 + Vite；`e2e/` 是浏览器回归，`src/styles/tokens.css` 是唯一配色/间距来源 |
| `desktop/` | Electron 主进程与 preload，M5 交付阶段才落地（当前只有占位） |
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
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | 进度台账（每次会话结尾追加） |

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
| `cd backend && uv run python scripts/verify_m2.py` | M2 采集链路 115 项：网页/视频成功、去重、force、三类抓取失败、四阶段进度、重试、并发、僵尸任务、字幕选取/解析/降级（**默认全用假 fetcher/transcriber，不打真实站点**） | 动到采集 / 任务状态机 / 字幕 |
| `cd backend && uv run python scripts/verify_m2.py --online` | 上面 115 项 + 16 项真实链路：两个公开页真抓、真 404、真去重（**要外网，断了会红**） | 动到 fetcher / 抽取库 / 降级策略，或验收前 |
| `cd backend && uv run python scripts/verify_m3.py` | M3 全链路 61 项：导图层级/折叠/转义/与笔记同步、学习页落库/内联样式/内嵌 SVG/净化与 XSS/断网自包含/下载、短词 LIKE、空检索不调模型、SSE 三事件顺序（**向量关闭 + LLM 用假实现**，不联网不烧钱） | 动到导图 / 渲染 / 检索 / 问答 |
| `cd backend && uv run python scripts/backfill_embed.py` | 全库补向量（幂等，只处理缺向量的 chunk）；`--stats` 只看覆盖率 | 首次启用向量、换 embedding 模型后 |
| `cd frontend && npm run lint` | 前端正确性问题（未定义/未使用变量、Vue 必备规则） | 改前端后 |
| `cd frontend && npm run build` | 可构建 | 改前端后 |
| `cd frontend && npm run e2e` | 浏览器端到端 24 项（需先起前后端，真实 LLM） | 动到 UI 主流程 |

`verify_m1.py` 与 `npm run e2e` 都会真的调模型（各约 1–3 次调用），别当免费工具循环跑。
`verify_m3.py` 全程不联网：`VECTOR_ENABLED=0` 且把 `asker.stream` 换成假实现，可以随便跑。
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

所有数据在单个 SQLite 文件 `data/data.db`（生产环境为 `%APPDATA%/Cairn/data.db`）。
备份 = 复制这个文件。`data/` 已在 `.gitignore` 中排除，**永不入库**。
