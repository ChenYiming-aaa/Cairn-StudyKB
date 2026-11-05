# Cairn

> cairn /kɛərn/ · 登山者沿途堆的石堆路标。走一段留一块石头，靠自己堆的标记找得回来。

个人自用的学习闭环工具：把文本 / 网页 / 视频采集进本地知识库，由 LLM 自动分类、摘要、结构化，
形成可阅读、可检索、可生成学习页、可出题练习的知识资产，并用番茄钟记录学习时间。

**当前状态**：M0 文档阶段完成，尚未开始编码。

## 技术栈

Python 3.12 · FastAPI · SQLite（FTS5 + sqlite-vec）· bge-small-zh-v1.5 · Vue 3 · Electron

## 先读这些

| 文件 | 作用 |
|---|---|
| [`docs/00-总纲.md`](docs/00-总纲.md) | **入口**。红线、技术栈、里程碑地图、会话工作法 |
| [`docs/milestones/`](docs/milestones/) | 每个里程碑的自包含执行文档 |
| [`docs/contracts/`](docs/contracts/) | 数据契约、接口契约、决策记录（ADR） |
| [`docs/HANDOFF.md`](docs/HANDOFF.md) | 进度台账（每次会话结尾追加） |

## 开发约定

```bash
# 文档一致性检查（每次改文档后、每次会话开场）
python tools/doc_check.py
```

- 技术栈定版见 `docs/00-总纲.md` §3，更换需先在 `决策记录.md` 追加 ADR
- 红线见 §2，四条技术限制的解除条件见 §2.1

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

> API 规范以 https://api-docs.deepseek.com 为准，本表核对于 2026-11-05。

## 数据与备份

所有数据在单个 SQLite 文件 `data/data.db`（生产环境为 `%APPDATA%/Cairn/data.db`）。
备份 = 复制这个文件。`data/` 已在 `.gitignore` 中排除，**永不入库**。
