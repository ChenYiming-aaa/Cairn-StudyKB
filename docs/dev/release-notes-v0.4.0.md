# v0.4.0 · 界面重做，多了学习记录

> **作用域**：v0.4.0 的 Release 标题与正文底稿；§2 照抄进 GitHub Release，§3 不贴。
> **读者**：下载这一版的人。
> **建立**：2026-11-27，按 `发版说明规范.md` 写。

## 1. 标题

`v0.4.0 · 界面重做，多了学习记录`

## 2. 正文

```text
1. 详情页换成新页头与概览
2. 列表徽标带圆点和文字
3. 删除内容改成先确认
4. 顶栏图标化，只留一颗主按钮
5. 新增学习记录热力图
6. 详情页能看这条掌握度

升级：设置 → 关于 → 检查更新

数据：数据目录不动，可装回上一版

安装包：Cairn-0.4.0-setup.exe（184.5 MB），sha256 见附件
```

## 3. 维护者备注（不贴 Release）

### 3.1 逐条对应的改动

| 正文点 | 改动 |
|---|---|
| 1 详情页换成新页头与概览 | `components/ItemDetail.vue` 加面包屑页头（`detail/DetailHeader.vue`：标题可改、状态徽标、工作区下拉、主操作随状态切换 —— 没整理完是「开始整理」，整理完是「练这条」）+ 可折叠概览面板（`detail/InsightPanel.vue` 四件：指标块 / 原文概览 / 进度环 / 完善度清单）。页签带计数，不进去也知道里面有没有东西。props / emits / 路由一个没改。 |
| 2 列表徽标带圆点和文字 | `components/list/ItemRow.vue` 换成 `ui/Badge.vue` 原语（`.u-badge-*` + 圆点），四种状态仍是 **待整理** 灰 / **整理中** 琥珀（跳动圆点）/ **已整理** 淡绿 / **失败** 红。状态→徽标的映射收进 `utils/status.js`，列表与详情共用一份；`StatusBadge.vue` 已无引用，删除。 |
| 3 删除内容改成先确认 | 原来 `window.confirm`，现在走 `ui/Dialog.vue` 对话框（`detail/DetailHeader.vue` 内），Esc / 点遮罩可关，焦点回到触发按钮。 |
| 4 顶栏图标化，只留一颗主按钮 | `App.vue`：五个导航项各带图标＋文字，连接状态从一颗圆点改成「已连接 / 连接中 / 未连接」带文字，任务入口降为图标＋角标（`aria-label` 保留「N 项未完成」），整条顶栏只有「采集内容」一颗实心按钮。原来「任务」与主操作平级，看不出哪个是主路径。 |
| 5 新增学习记录热力图 | 新端点 `GET /api/stats/heatmap?days=364`（7–366，越界 422）+ `components/dashboard/ContributionGraph.vue`（52 周 × 7 天）。一格强度 = 当天 `quiz_attempt` 条数 + 当天整理成 `ready` 的篇数，与「连续学习天数」同一对信号，所以「图上有格子」和「这天算学过」不会互相矛盾。空库也画格子并给一句提示。 |
| 6 详情页能看这条掌握度 | 新端点 `GET /api/stats/mastery/{item_id}` + 概览侧栏第二个环。口径：**每道题最近一次判定答对的题数 ÷ 该内容全部题数**，没练过的题也算分母；`is_correct IS NULL` 单列 `pending`，不算对也不算错；没有题时 `mastery` 是 `null` 而不是 0，前端整块不渲染（不拿 0% 冒充「一题都不会」）；内容不存在 404。 |

### 3.2 两次口径决定（为什么这样算）

- **热力图强度按绝对次数分档**（1 次 / 2–3 / 4–5 / ≥6），不做「窗口内最大值归一化」。归一化会把「一天 29 次、另一天 1 次」里的 1 次压成几乎看不见，而那天同样是真的学了。
- **掌握度看「最近一次判定」，不累计历史正确率**：一道题错了三遍后改对，现在最该反映的是「现在会不会」。历史正确率留在复习页的错题本里。

### 3.3 数据与回退

`SCHEMA_VERSION` 仍是 **6**，与 v0.3.8 相同，**没有迁移，也没有新表** —— 两个端点都是只读聚合，读的是既有
`quiz_attempt.created_at` / `question.item_id` / `knowledge_item.status`。装回 v0.3.8 完全没问题，所以固定短句写「可装回上一版」。

热力图目前**没建** `quiz_attempt(created_at)` 索引：个人库规模下全表扫足够，等真慢了再走迁移。

### 3.4 不写进正文的改动（用户不可见）

- **样式分三层**：`styles/tokens-v05.css`（三级表面 / 三级阴影 / 字号补到 32px / 图标几何 / 两级焦点环）、
  `styles/ui.css`（原语公共层）、`styles/app-shell-v05.css`（把 `.btn` `.input` `.badge` `.state` `.skeleton`
  这批旧类名整体升到新外观，`.workspace` / 三栏宽度这些**结构**声明不动）。`tokens.css` 一行没改 ——
  它是 `check_contrast.py --write` 的生成物，新配色走追加层。
- **`frontend/src/ui/` 12 个原语**（Button / Icon / Badge / Checkbox / Dialog / EmptyState / Field / Input /
  Select / Skeleton / Tabs / Textarea）零依赖；38 枚 symbol 贴在 `index.html` 的 `<body>` 首行（`display:none`，
  不占布局），语义表落 `docs/dev/图标语义映射.md`。
- **仪表盘**：`/api/stats/today` 的五个数字块不动，热力图插在数字卡与分类分布之间。
- **演示站**（`VITE_DEMO=1`）只按 fixture 能确证的部分算：热力图只有快照那天有数字，掌握度只用复习/错题里
  那几道题，不补编历史。

### 3.5 验收

- 本机 2026-11-27：`pytest` **38/38** · `verify_m5` **39/39**（新增热力图逐格 SQL 对账、掌握度语义 8 条）·
  `verify_m7` **99/99** · `verify_m11` **61/61** · `verify_pool` **23/23** · `verify_backup` **33/33** ·
  `verify_m4` **78/78** · `verify_m10` **151/151** · `check_motion_tokens` 全过 ·
  `check_contrast` 6 套 × 明暗 12 组达标 · `doc_check --strict` 0 FAIL / 0 WARN · `bump_version --check` 五处 0.4.0。
- 前端 `npm run lint` 干净，`npm run build` 3.2 s（主包 440.94 kB / gzip 约 155 kB），
  构建后 `grep -r cairn-demo dist` 为空（正式包，没把演示数据带进去）。
- 安装包 `Cairn-0.4.0-setup.exe` **184,499,129 B**（184.5 MB），
  sha256 `1eae68b099c45eff7bd90ee17b6bf2f37862cecc825ccbd39df5106237b3cd35`。
- 包内冒烟（`win-unpacked/resources/backend/cairn-backend.exe --port 8799`）：
  `/api/version` 回 `0.4.0 / 1fe683d / 2026-11-27T15:23:46+08:00`、`/` 200 `text/html`、
  `/pdf/cmaps/Adobe-GB1-UCS2.bcmap` 200（33,974 B）、`assets/pdf.worker.min-*.mjs` 为 `text/javascript`、
  `/api/health` ok、`/api/stats/heatmap?days=7` 回连续 7 格、`/api/stats/mastery/99999` 404。
  真起浏览器加载包内页面：外壳 1、导航 5 项、图标 `<use>` 17 处、热力图 364 格 + 13 个月份标签，**控制台零报错**。

### 3.6 tag 与源码对应

`v0.4.0` 指 `1fe683d`（只有版本号那一个提交），与包内 `_build_info.COMMIT` 一致；
发版文档与台账提交在 tag 之后，不平移 tag。
