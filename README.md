# Cairn

> cairn /kɛərn/ · 登山者沿途堆的石堆路标。走一段留一块石头，靠自己堆的标记找得回来。

个人自用的学习闭环工具：把文本 / 网页 / 视频采集进本地知识库，由 LLM 自动分类、摘要、结构化，
形成可阅读、可检索、可生成学习页、可出题练习的知识资产，并用番茄钟记录学习时间。

**当前状态**：M2（真实内容采集）已验收（2026-11-06，tag `m2-done`）。
网页链接与视频链接都能入库：网页走 trafilatura 抽正文，视频**优先用自带字幕**（省掉下载与识别），
没有字幕才走 yt-dlp + faster-whisper 转录成带 `[mm:ss]` 时间戳的正文；两条链都有查重
（同 URL / 同内容）、6+8 类错误码带中文文案、四阶段进度与任务中心（失败可重试）。
采集完成后可直接「去看看」跳到该条目，或「继续采集」下一条。
`verify_m2.py` 72/72 PASS，`verify_m1.py` 51/51 PASS。下一步 M3：全文检索 / 向量检索 / 问答。

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

## 验证

| 命令 | 验什么 | 何时跑 |
|---|---|---|
| `python tools/doc_check.py` | 文档一致性（作用域、ADR/端点/表引用、完结标记） | 改文档后、每次会话开场 |
| `cd backend && uv run python scripts/status.py` | 数据目录 / 表行数 / 最近任务 / 环境自检（只读） | 每次会话开场与收尾 |
| `cd backend && uv run python scripts/env_check.py` | ffmpeg / whisper / embedding / sqlite-vec / LLM Key（`--json` 机读，`--strict` 有阻塞项即 exit 1） | 排查"转录跑不起来" |
| `cd backend && uv run python scripts/verify_m1.py` | M1 后端链路 51 项（含分类聚合端点），真实 LLM 调用 | 动到条目 / 整理 / chunk |
| `cd backend && uv run python scripts/verify_m2.py` | M2 采集链路 72 项：网页/视频成功、去重、force、三类抓取失败、四阶段进度、重试、并发、僵尸任务、字幕选取/解析/降级（**全用假 fetcher/transcriber，不打真实站点**） | 动到采集 / 任务状态机 / 字幕 |
| `cd frontend && npm run lint` | 前端正确性问题（未定义/未使用变量、Vue 必备规则） | 改前端后 |
| `cd frontend && npm run build` | 可构建 | 改前端后 |
| `cd frontend && npm run e2e` | 浏览器端到端 24 项（需先起前后端，真实 LLM） | 动到 UI 主流程 |

`verify_m1.py` 与 `npm run e2e` 都会真的调模型（各约 1–3 次调用），别当免费工具循环跑。
`verify_m2.py` 全程注入假实现，不访问外部站点、不调模型，可以随便跑。
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

> **站点登录**：需要登录才给内容的站点（B 站字幕、知乎受限页）在采集面板的「链接采集」里
> 点「站点登录」即可。后端会弹一个**独立**的浏览器窗口，登完自动导出 cookie 并立即生效，
> 不用改 `.env`、不用重启，也不碰你日常用的浏览器。
> 知乎这类站点光有 cookie 不够（它拦的是浏览器指纹），所以网页抓取在 httpx 失败时会
> 自动改用同一个浏览器渲染再抓一次，多花 3–5 秒。


> 语音模型不是环境变量：视频采集时由请求体 `model` 决定（默认 `small`），
> 首次使用自动下载到 `data/models/whisper/`（约 500MB，删了下次会重下）。
>
> 字幕优先是**默认行为**，不需要开关：有中英字幕就用，没有就转。人工字幕优先于自动字幕，
> 简体优先于繁体。任务 `output_json.source` 会标明这次走的是 `subtitle` 还是 `asr`。

> API 规范以 https://api-docs.deepseek.com 为准，本表核对于 2026-11-05。

## 数据与备份

所有数据在单个 SQLite 文件 `data/data.db`（生产环境为 `%APPDATA%/Cairn/data.db`）。
备份 = 复制这个文件。`data/` 已在 `.gitignore` 中排除，**永不入库**。
