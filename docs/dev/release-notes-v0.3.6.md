# v0.3.6 · 整理不再覆盖手改

> **作用域**：v0.3.6 的 Release 标题与正文底稿；§2 照抄进 GitHub Release，§3 不贴。
> **读者**：下载这一版的人。
> **建立**：2026-11-22，按 `发版说明规范.md` 写。

## 1. 标题

`v0.3.6 · 整理不再覆盖手改`

## 2. 正文

```text
1. 说明里的重复话删掉
2. 页面标题一眼分得清
3. 设置页签去掉副标题
4. 整理不再盖掉手改的笔记
5. 同一份内容只留一条
6. 几条内容可以同时整理
7. 两字词也能搜到

升级：设置 → 关于 → 检查更新

数据：库已升级，建议不要装回上一版

安装包：Cairn-0.3.6-setup.exe（184.5 MB），sha256 见附件
```

## 3. 维护者备注（不贴 Release）

### 3.1 逐条对应的改动

| 正文点 | 改动 |
|---|---|
| 1 说明里的重复话删掉 | 文案瘦身：9 个界面 4308 → 3869 字（−439），设置四页签副标题、六张配色卡描述、任务中心逐行说明、下载页四卡重复的「演示版不能装」全删；`SearchScopeHint` 三处提示并进空态标题（`标题里没有「xx」`）。详见 `docs/dev/文案与信息布局瘦身-2026-11-22.md`。 |
| 2 页面标题一眼分得清 | 视觉层级 7 条：页面标题从浏览器默认样式改为显式 `fs-xl`；区块名从 `fs-xs + text-3`（比它管的内容还淡）提到 `fs-sm + text-2`；面板名与字段标签收成两档。详见 `docs/dev/视觉层级审计-2026-11-22.md`。 |
| 3 设置页签去掉副标题 | `settings/*Tab.vue` 四处副标题删除；`components.json` 的四个组件 `why` 收短。 |
| 4 整理不再盖掉手改的笔记 | `organizer.run` 入口与写库前各复查一次 `note_edited`；`save_organize_result` 增 `overwrite_note` 开关，只有用户在界面确认覆盖时才写 `note_edited=0`。任务排队期间手改的笔记不再被静默撤销。 |
| 5 同一份内容只留一条 | `idx_item_hash` 改 `CREATE UNIQUE INDEX`；v6 迁移把历史重复组的 `content_hash` 改写为 `hash:id`（保留最小 id）后建唯一索引；`create_item` 捕获 `IntegrityError` 回查已有行。 |
| 6 几条内容可以同时整理 | 任务 worker 数改由 `CAIRN_TASK_WORKERS` 控制（默认 3，上限 8）；`claim_organize` 用条件 UPDATE（`WHERE status='pending'`、`rowcount==1`）抢占，避免两条任务抢同一条内容。 |
| 7 两字词也能搜到 | `retriever` 的 LIKE 兜底补 `ESCAPE '\'`；两字词兜底按 `length(content)` 排序，短片段优先。 |

### 3.2 数据与回退

v6 迁移只改 `content_hash` 的取值形态并加唯一索引，**内容本身一行没动**。
装回 v0.3.5 时库能打开（`user_version=6` 高于旧代码已知的 5，旧代码不会再升），
但旧代码没有接 `IntegrityError`，重复采集同一份内容会直接 500 —— 所以正文写「建议不要装回上一版」。

### 3.3 验收

- 回归 `m1 56 / m2 118 / m3 61 / m4 78 / m5 25 / m9 306 / m10 151 / m11 61 = 856 全绿`；
  m6 / m7 / m8 本轮未触及（m7 需重建 dist，界面改动已用 Playwright 走查覆盖）。
- 真实库已升 v6：`user_version=6`、`idx_item_hash` 为 UNIQUE。
- 安装包 `Cairn-0.3.6-setup.exe` **184,462,145 B**（184.5 MB），
  sha256 `6c1108f662b9bd459a8d8b316d021f1737c085acee81ad0cd838949946927699`。
