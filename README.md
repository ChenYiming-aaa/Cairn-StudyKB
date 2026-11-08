<p align="center">
  <img src="docs/images/logo.png" width="88" alt="Cairn">
</p>

<h1 align="center">Cairn</h1>

<p align="center">
  把看过的网页、视频、文章收进本地知识库，让 AI 整理成可检索、可复习的知识资产。<br/>
  单机运行 · 数据在你自己的硬盘上 · Windows 桌面应用
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-lightgrey.svg" alt="Platform">
  <img src="https://img.shields.io/badge/version-0.1.0-green.svg" alt="Version">
  <img src="https://img.shields.io/badge/data-100%25%20local-success.svg" alt="Local first">
</p>

<p align="center">
  <a href="#下载与安装">下载</a> ·
  <a href="#界面">截图</a> ·
  <a href="#它能做什么">功能</a> ·
  <a href="#第一次打开要配什么">配置</a> ·
  <a href="#常见问题">常见问题</a>
</p>

---

> **cairn** /kɛərn/ · 登山者沿途堆的石堆路标。走一段留一块石头，靠自己堆的标记找得回来。

## 这是什么

看过的东西大多留不下来：网页关掉就散了，视频看完只剩「我好像学过」的感觉，摘抄攒了一堆却从来没回头读过。

Cairn 想把这条断掉的链路接上：**一个链接丢进去 → AI 抽正文、分类、写摘要和结构化笔记 → 之后能按语义搜出来、能生成学习页、能自动出题考你、答错的题按间隔重复回来找你。** 学多久也有记录，仪表盘上一眼看到今天该干什么。

它是给一个人用的工具，不是一个平台：没有账号、没有云同步、没有多人协作。所有内容存在一个本地 SQLite 文件里，唯一出网的动作是调用你自己配置的大模型接口。

| 它不做 | 说明 |
|---|---|
| 不做云端存储 | 数据在 `%APPDATA%\Cairn\`，卸载也不删 |
| 不支持多人 / 团队 | 单用户单机，后续也不会做 |
| 不自动替你「读完」 | 采集是自动化，理解还得你自己看、自己写 |

## 下载与安装

**系统要求**：Windows 10 / 11，x64。**不需要装 Python、Node 或 ffmpeg**，安装包自带运行时和 ffmpeg。

1. 到 [Releases](https://github.com/ChenYiming-aaa/Cairn-StudyKB/releases) 下载 `Cairn-0.1.0-setup.exe`（约 426 MB —— 里面塞了 Python 运行时、`torch` 和 `ffmpeg`，不是下载出错）
2. 双击安装。若弹出蓝色的「Windows 已保护你的电脑」，点 **更多信息 → 仍要运行**
   （安装包没有做代码签名，这不是病毒告警，只是"没见过这个发布者"）
3. 安装向导可以改安装目录；默认装在当前用户目录下，**不需要管理员权限**，卸载也走「应用和功能」里的同名条目
4. 首次启动约 4–6 秒出界面（先起本地后端，握手成功才建窗口，所以不会白屏）
5. 如果还没配模型 Key，会自动进「环境」引导页：粘贴 Key → 保存并检查 → 变绿 → 去知识库

以后双击桌面或开始菜单的 **Cairn** 即可。重复双击不会开第二个实例，只会把已有窗口叫到前面。

## 界面

**知识库** · 左边是自动生成的分类与标签树，中间是条目列表，右边是选中条目的摘要与要点（笔记、原文、思维导图、学习记录各占一个页签）。

![知识库](docs/images/01-knowledge.png)

**条目详情** · AI 重写标题、给摘要、拆要点、写 Markdown 笔记；笔记可以手改，改完索引自动重建。

![条目详情](docs/images/02-item-detail.png)

**思维导图** · 按笔记的标题层级现场出图，用来检查自己的理解结构有没有断层。

![思维导图](docs/images/03-mindmap.png)

**检索问答** · 对整库提问，答案分条并带 `[n]` 引用；点引用直接跳到原文那一段并高亮。全文搜不到就坦白说"库里没有"，不硬编。

![检索问答](docs/images/04-ask.png)

**学习页** · 多选条目生成一份**单文件离线** HTML（内联样式、内嵌导图、代码高亮），能断网打开、能直接发给别人。

![学习页](docs/images/05-pages.png)

**复习** · 答错的题按 1 → 2 → 4 → 7 → 15 天回来；到期就出现在这里，一题一屏，答完立刻给判定和解析。

![复习](docs/images/06-review.png)

**练习** · 选一条 ready 条目，挑题型（单选 / 多选 / 判断 / 简答）、难度、题数（5 / 10 / 20），题面逐题流式浮现。

![练习](docs/images/08-practice.png)

**仪表盘** · 今日待整理、今日待复习、连续学习天数、今日正确率、本周专注、分类分布，全部由后端按固定口径算好。

![仪表盘](docs/images/07-dashboard.png)

## 它能做什么

### 采集
- **网页链接**：抽正文入库（`trafilatura`），自动去掉导航和广告
- **视频链接**：优先用站点自带字幕，没有字幕才下载音频跑本地语音识别（`faster-whisper`）
- **纯文本**：直接粘贴，适合笔记、摘录、短文
- 视频站点的登录态可以放一份 `cookies.txt`，B 站这类必须登录才给字幕的站点才能拿到字幕

### 整理
- 大模型读完全文后：**重写标题**（≤20 字）、给**摘要**、拆 3–6 条**要点**、写一份带标题层级的**结构化笔记**、打**分类**和**标签**
- 单条整理，或「整理全部」批量跑（后台队列，逐条派发独立任务，失败可重试）
- 整理结果全部可手改；手改过的笔记不会被覆盖，索引会跟着重建

### 检索
- **两路召回**：SQLite FTS5（trigram，两字词也能搜）+ 本地 bge 向量，RRF 融合
- 向量不可用时自动降级成纯全文检索，前端明说"已降级"，不假装
- 全文零命中时向量还要过距离阈值，否则直接判"库里没有"**不调模型**（省钱也避免瞎编）

### 问答
- 对整库提问，答案分条 + `[n]` 引用；点引用/来源卡片跳到原文并高亮
- 每次问答（含"库里没有"）自动存进历史，点一条就恢复当时的问题、答案与来源，**不会重新调模型**
- 历史可单条删除

### 学习页
- 多条目 → 一份离线 HTML：内联样式、内嵌思维导图、代码高亮，iframe 预览后可下载分享
- 产物有历史记录，可回看、可删除

### 出题与练习
- 四种题型（单选 / 多选 / 判断 / 简答），三档难度，材料按 chunk 等距抽样覆盖全文
- 客观题判分在后端（多选按集合、顺序无关）；简答走大模型批改，给出"你提到了…但漏了…"
- 批改失败时落「待人工判断」，**不冤枉人**

### 复习
- 答错自动进入间隔重复队列：1 → 2 → 4 → 7 → 15 天
- 今日到期一次最多 20 题，直接进入作答；「错题本」只列**最近一次仍答错**的题，复习答对即移出

### 专注
- 条目或练习页点「开始专注」带入上下文，顶栏「专注」可开一轮自由专注
- 15 / 25 / 50 分钟，可暂停、提前完成、放弃；到点先冻结时长再让你写一句笔记
- **刷新、切页面、重启后端都不会重置**（时长以开始时间推算，15 秒心跳兜底）
- 一轮结束后出现在该条目的「学习记录」页签里

## 第一次打开要配什么

| 项 | 必需 | 怎么弄 |
|---|---|---|
| **模型 Key** | ✅ 必需 | 「环境」页粘贴任意 OpenAI 兼容服务的 Key（默认 DeepSeek）；填完**立刻生效，不用重启**，存在 `%APPDATA%\Cairn\.env`，重装也还在 |
| ffmpeg | 已自带 | 安装包内置，无需配置 |
| 向量模型（约 92 MB） | 首次检索时自动下载 | 从 `hf-mirror.com` 拉 `bge-small-zh-v1.5`；下不来就自动降级成纯全文检索 |
| 语音识别模型（约 539 MB） | 首次转录音频时自动下载 | 只有「视频没有字幕」时才会用到；有字幕的视频不下载 |

换模型/换服务商：在 `.env` 里改 `LLM_BASE_URL` / `LLM_MODEL` 即可，参考 [.env.example](.env.example)（里面写了硅基流动、阿里百炼、本地 Ollama 的例子）。

## 你的数据在哪

```
%APPDATA%\Cairn\
├─ data.db          # 全部内容：条目、chunk、索引、题目、作答、计时（一个 SQLite 文件）
├─ models\          # 本地向量模型与语音模型
├─ logs\            # 运行日志
└─ .env             # 你的 Key（这一份不会跟着仓库走）
```

- **备份** = 复制整个目录；**迁移** = 把目录搬到新机器同一位置
- 直接复制 `data.db` 在另一个进程里打开也没问题（WAL，`scripts/status.py --db` 就是这么读的）
- **卸载不会删数据**，重装后内容还在；要彻底清空得手动删 `%APPDATA%\Cairn\`
- 出网只有三件事：调用你配置的大模型接口、下载本地模型、采集你给的链接。**没有遥测、没有统计上报**
- 仓库里的 `.gitignore` 把 `data/`、`*.db`、`.env`、`cookies.txt` 全部挡住，私人内容不会被误提交

## 常见问题

<details>
<summary><b>没有模型 Key 能用吗？</b></summary>

能打开、能粘贴文本，但整理、问答、出题都要调模型，没 Key 时这些入口会直接返回 `LLM_NO_KEY` 并提示你去配 Key——**不会留一个注定失败的任务在队列里**。
</details>

<details>
<summary><b>支持哪些模型服务？</b></summary>

任何 OpenAI 兼容的 `/chat/completions` 接口。默认 DeepSeek；硅基流动、阿里百炼、本地 Ollama 都有现成配置示例写在 [.env.example](.env.example) 里。换服务时注意 `base_url` 要不要带 `/v1`（DeepSeek 不带，多数服务带）。
</details>

<details>
<summary><b>安装包为什么有 426 MB？</b></summary>

为了让你不用装任何东西：里面打包了完整 Python 运行时、`torch`（本地向量与语音识别要用）、`ffmpeg` 二进制。代价是体积大、冷启动慢一点，换来的是"双击就能用"。
</details>

<details>
<summary><b>卸载为什么很慢？</b></summary>

要删 1.4 GB 文件，加上杀毒软件实时扫描，实测能到十分钟。数据目录不在卸载范围内，所以卸载不会碰你的知识库。
</details>

<details>
<summary><b>B 站视频拿不到字幕？</b></summary>

B 站的字幕接口必须登录。用浏览器扩展导出一份 `bilibili.com` 的 cookies（Netscape 格式），存成文件后把路径填到 `.env` 的 `YTDLP_COOKIES`。拿不到字幕也不会失败，会自动退回下载音频 + 本地语音识别，只是慢很多。
</details>

<details>
<summary><b>换了向量模型，检索结果不对了？</b></summary>

换 `EMBED_MODEL` 必须重建 `chunk_vec` 表（维度变了），否则新旧向量混在一起。见 `docs/dev/milestones/M3-检索与学习页.md` §6.3。
</details>

## 已知限制

诚实列一下，v0.1.0 就是这样：

- **安装包没有代码签名**。SmartScreen 会拦一次，正式分发需要买证书
- **冷启动约 6.7 秒**（热启动约 4 秒）。首启要建表 + 杀软扫 1.4 GB，重型导入已经延迟加载
- **URL 规范化只去 fragment 不去 query**。带 `?spm=` / `?utm_source=` 的同一篇文章会被当成两条
- **多选偶尔出现"四个选项全对"**。prompt 已约束，但没有量化断言拦住它
- **题目、作答、复习记录无限增长**，没有保留策略；数据量很大之后仪表盘可能变慢
- **只支持 Windows x64 的安装包**。源码本身跨平台，但打好的包只有 Windows 版
- 前端交互与视觉还有一块优化空间（这一版优先保证功能正确）

## 从源码运行

<details>
<summary><b>开发环境与命令</b></summary>

**依赖**：Python 3.12（用 [uv](https://docs.astral.sh/uv/) 管理）、Node 20+、ffmpeg（可选，只在测视频采集时需要）。

```bash
# 后端（默认 127.0.0.1:8756）
cd backend
cp ../.env.example ../.env      # 填 LLM_API_KEY
uv sync
uv run python -m app

# 前端（默认 5173，/api 反代到 8756）
cd frontend
npm install
npm run dev

# 桌面壳（dev 模式加载 vite 页面）
cd desktop
npm install
npm start
```

**打包安装包**（会先把 ffmpeg 复制进 `desktop/resources/`）：

```bash
cd backend && uv run pyinstaller --noconfirm --distpath build/dist --workpath build/work cairn-backend.spec
cd ../desktop && npm install && npm run dist     # 产物在 desktop/release/
```

**验收脚本**（真调模型，会自己建临时数据目录，不碰你的库）：

```bash
cd backend
uv run python scripts/verify_m1.py    # 52/52
uv run python scripts/verify_m2.py    # 118/118
uv run python scripts/verify_m3.py    # 61/61
uv run python scripts/verify_m4.py    # 69/69
uv run python scripts/verify_m5.py    # 57/57
```

**目录结构**

```text
backend/    FastAPI 后端：SQLite + FTS5 + sqlite-vec，服务层在 app/services
frontend/   Vue 3 + Vite，hash 路由（Electron 用 file:// 加载不会 404）
desktop/    Electron 主进程、NSIS 打包配置、图标
tools/      文档一致性检查、图标生成、ffmpeg 准备
docs/       用户向图片（images/）+ 开发文档（dev/：总纲、台账、契约、里程碑）
```

开发文档、接口契约、数据契约、里程碑台账都在 [`docs/dev/`](docs/dev/)，代码层面的约定以那份为准。

</details>

## 许可

MIT，见 [LICENSE](LICENSE)。用、改、分发都行，保留版权声明即可；不提供任何担保。

第三方组件遵循各自许可：FastAPI、Vue、Electron、`faster-whisper`、`sentence-transformers`、`sqlite-vec`、`trafilatura`、`yt-dlp` 等。
