# v0.3.8 · 试卷能重做，数据有备份

> **作用域**：v0.3.8 的 Release 标题与正文底稿；§2 照抄进 GitHub Release，§3 不贴。
> **读者**：下载这一版的人。
> **建立**：2026-11-27，按 `发版说明规范.md` 写。

## 1. 标题

`v0.3.8 · 试卷能重做，数据有备份`

## 2. 正文

```text
1. 试卷做完能再做一遍
2. 新增「做已有题」，不用重出
3. 数据每天自动备份一份
4. 关于页能手动备份
5. 修好按钮文字被截断

升级：设置 → 关于 → 检查更新

数据：数据目录不动，可装回上一版

安装包：Cairn-0.3.8-setup.exe（184.5 MB），sha256 见附件
```

## 3. 维护者备注（不贴 Release）

### 3.1 逐条对应的改动

| 正文点 | 改动 |
|---|---|
| 1 试卷做完能再做一遍 | `Practice.vue` 的 `onRestart` 原来无条件 `backToIdle()`：交卷后点「再做一遍」，舞台变成「还没开始」。卷子与作答一直在库里，坏的是这颗按钮。改成先 `backToIdle()` 再按上一轮形态重开（`paperRun` 在就 `startPaper()`）。生成的题组没有「题组」实体，仍然回配置重新选题型与题数 —— 那正对应第 2 条的入口。 |
| 2 新增「做已有题」，不用重出 | 新端点 `GET /api/knowledge/{id}/questions` + `repo.questions.list_for_item()`，排序 `origin → 题号数值 → id`；筛选 `origin <> 'imported' OR number IS NOT NULL`（导入的空壳题不算数）。前端在「出题」下加次要按钮 `做已有题（N）`，N=0 不渲染，试卷内容不出这颗按钮（`按卷练` 已是整份卷子）。没建任何新表。 |
| 3 数据每天自动备份一份 | `services/backup.py`：`VACUUM INTO <数据目录>/backup/data-YYYYMMDD.db`（WAL 下直接复制 `data.db` 会漏数据），保留最近 7 份、当天不重复、失败只记日志不阻塞启动；`main.py` lifespan 起 daemon 线程。写入后先做 `PRAGMA integrity_check`，不合格的半份删掉。 |
| 4 关于页能手动备份 | `GET/POST /api/settings/backup` + `AboutTab.vue` 的「备份」块：上次备份（时间 · 体积）、备份位置、立即备份。按钮回报四种结果：已备份 / 今天已经备过 / 刚备过 / 这次没有可备份的内容。 |
| 5 修好按钮文字被截断 | 配置栏三颗按钮的文字包进 `.btn-label`（`flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap`），各带完整 `title`。原来窄宽度下字被切掉一半、右边留一块白。 |

### 3.2 为什么第 1 条排最前

规范 §2.1 要求「会让人以为坏了的那条排最前」。这一版只有它是这种事：交卷后点「再做一遍」没有反应，
用户会以为作答丢了。实际数据一直在库里，`按卷练` 再点一次就能取回整份卷子。

### 3.3 数据与回退

`SCHEMA_VERSION` 仍是 **6**，与 v0.3.7 相同，**没有迁移**，装回 v0.3.7 完全没问题，
所以固定短句写「可装回上一版」。备份目录是新增的，回退后只是没人读它，不影响打开。

### 3.4 不写进正文的改动（用户不可见）

- **CI**：`.github/workflows/ci.yml` 三个 job（front / docs / backend），实测 front 16–20 s /
  docs 5–9 s / backend 17–24 s。backend 靠 `uv sync --frozen` 跳过 17 个包（torch / triton / `nvidia-*`），
  再跑 pytest + `verify_pool` / `verify_backup` / `verify_m4` / `verify_m10`。
- **模型输出 schema**：新增 `app/services/schemas.py`，`OrganizeResult` / `QuizItem` / `ExamFix` 三份模型
  收掉三个调用点的手写容错。原来的 `str(value or "")` 会把 `{"a": 1}` 变成标题、把 `{"B": true}` 变成答案
  —— 不报错、也没痕迹。现在 dict / list / bool 一律不当字符串。失败路径沿用各自原有口径，没加新错误码。
- **pytest**：`backend/tests/` 38 条，`conftest.py` 钉 `CAIRN_ENV_STRICT=1` + 临时数据目录，
  本机有没有 `.env` 都不影响，不真调模型。
- **版本与台账**：`tools/bump_version.py` 纳入 README 徽标（第五处）；`AGENTS.md` 加上工手册；
  `HANDOFF.md` 由 2904 行压到 374 行（M4–M11 的历史段落移进归档文件，两端逐条 sha256 校验）。

### 3.5 验收

- 本机 2026-11-27：`pytest` **38/38** · `verify_m7` **99/99** · `verify_m8` **110/110** ·
  `verify_m10` **151/151** · `doc_check --strict` 0 FAIL / 0 WARN · `bump_version --check` 五处 0.3.8。
- 前端 `npm run lint` 干净，`npm run build` 2.9 s（主包 415.56 kB / gzip 148.07）。
- 安装包 `Cairn-0.3.8-setup.exe` **184,483,214 B**（184.5 MB），
  sha256 `c0340cae8b16b413b7c3ee2c0bf73bbee42acf6fd8ab0b10c7497e193869ea65`。
- 包内冒烟：`/api/version` 回 `0.3.8 / e9d23dc / 2026-11-27T11:46:43+08:00`，
  `/` 200 `text/html`、`/pdf/cmaps/Adobe-GB1-UCS2.bcmap` 200、`assets/pdf.worker.min-*.mjs`
  为 `text/javascript`、`/api/health` ok。
