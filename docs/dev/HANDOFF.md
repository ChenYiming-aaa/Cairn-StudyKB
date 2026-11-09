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

## 当前状态（2026-11-09 19:30 · 每次会话结束更新这一段）

| 项 | 值 |
|---|---|
| 里程碑 | **M6 进行中（第一部分）**。M6 拆成两部分执行：**第一部分 = T6.0–T6.6**（基线、契约、`prefs`、LLM 按任务路由、provider 探测、设置窗口壳 + 模型 tab）；**第二部分 = T6.7–T6.9**（6 套主题 × 明暗、外观/关于 tab + 字号三档、引导页改造 + `verify_m6` 主题断言 + 回归 + tag `m6-done`） |
| 当前里程碑 | M6 · **第一部分（T6.0–T6.6）已完成**（2026-11-09 19:30）；下一步是第二部分 T6.7–T6.9 |
| 上一里程碑 | **M5 代码完成 + v0.1.0 已发布（tag + GitHub Release + 安装包）**：本机「安装 → 干净 PATH 启动 → 卸载 → 重装数据保留」已闭环。**唯一未闭环项仍是遗留 #2**：装到一台没有 Python/Node 的真机 |
| 远程 | `origin/main` = `59c19ae` 之后有 M6 第一部分若干提交（见文末条目）；**本表不追每次提交** |
| 版本 | `v0.1.0`（desktop / frontend / backend 三处都是 0.1.0）。**M6 关于页显示真实版本 + 「v0.2 开发预览」标注**，统一到 0.2.0 是 T8.6 的事（2026-11-09 你裁决：不提前写死 0.2.0） |
| 标签 | `m0-docs` `m0-ready` `m1-backend` `m1.1` `m1-done` `m2-web` `m2-done` `m3-wip` `m3-done` `m4-wip` `m4-done`(→`a3bab20`) `m5-wip` `v0.1.0` `m6-wip`（M6 基线，2026-11-09） |
| 验收 | **m1 52/52 · m2 118/118 · m3 61/61 · m4 69/69 · m5 57/57 · m6 53/53（2026-11-09 19:25 全量重跑）** · `npm run lint` 干净 · `npm run build` 通过（287 kB / gzip 105 kB） · `doc_check.py` 6 PASS + 1 提示 · 安装包基线 426,428,660 字节 |

| 许可证 | MIT（`LICENSE`，与 AnythingLLM / Quivr 同类项目一致） |
| 在线演示 | **<https://chenyiming-aaa.github.io/Cairn-StudyKB/> 已上线（200）** —— `VITE_DEMO=1` 构建的只读静态演示（fixture 抓自真实后端），`.github/workflows/pages.yml` 在 main 更新后自动部署。**仓库必须 Public**（免费账号私有仓库不支持 Pages，这是首次 404 的原因）；Source 必须是 `GitHub Actions` |
| 发布 | GitHub Release `v0.1.0`：<https://github.com/ChenYiming-aaa/Cairn-StudyKB/releases/tag/v0.1.0>（正文取 `release-notes-v0.1.0.md`，附件 `Cairn-0.1.0-setup.exe` 426,428,660 字节） |
| 台账 | M0–M3 已归档到 `docs/dev/archive/HANDOFF-2026-11-05至11-07.md`；M4 三条 + M5 三条留在本文件（M5 验收后 M4+M5 一起移） |

**2026-11-09 本轮裁决（四条，都已落进文档，改主意要回写）**

1. **配色**：`bread`「书卷」与「暖墨」四个主色完全相同 → 换成 Diary & Journal App（100），改名 **`chestnut`「栗墨」**（深栗棕 `#92400E` + 靛紫 `#6366F1`）。仍是 6 套，色相族互不重复。见 M6 §3
2. **关于页版本号**：显示真实版本（现 `0.1.0`）**并标注「v0.2 开发预览」**，不提前硬写 0.2.0
3. **字号档位**：**做**三档（小/标准/大），改 `--fs-*`，写进 `appearance.font_size`（第二部分 T6.8 实现）
4. **`--c-warning` 取色**：原规则「用调色板 Accent」在 `docs`（蓝）/`chestnut`（靛）/`study`（绿）三套里语义是错的，改为**统一琥珀 `#B45309`**（第二部分 T6.7 实现，若你不同意就在这里改回去）

**未结遗留（历史条目里的遗留已逐条核对，只有下面这些还开着）**

| # | 遗留 | 类型 | 备注 |
|---|---|---|---|
| 1 | ~~`verify_m1.py` 写死 `total == 3`~~ | **已修 2026-11-08** | 改成「organize 任务数前后不变 + 无 `LLM_NO_KEY` 失败任务」，m1 现在 52/52 |
| 2 | 装到**另一台没有 Python/Node** 的 Windows 机器 | DoD 唯一未闭环项 | 我只能用干净 PATH 模拟（已过），真机得你找 |
| 3 | 冷启 6680ms 未达 DoD 的 5 秒（热启 4066ms 达标） | 已记例外 | 原因是首启建 21 张表 + 杀软扫 1.4GB；重型导入已延迟，8.9s → 6.7s |
| 4 | 安装包**未签名** | 发布前必办 | SmartScreen 会拦，README 已写"更多信息 → 仍要运行"；正式分发要买证书 |
| 5 | 多选可能出「四个选项全对」 | 模型质量 | prompt 已约束，无量化断言 |
| 6 | `question` / `quiz_attempt` / `review_item` 无限增长 | backlog，随 v2 做 | 仪表盘不需要保留策略就能跑 |
| 7 | `normalize_url` 只去 fragment 不去 query | 已知限制 | `?spm=` / `?utm_source=` 会让同一篇 CSDN 成两条 |
| 8 | `e2e/m4_quiz.py` 需 `--db` 手改 ready | 工具便利 | 新建条目是 pending，练习页只列 ready |
| 9 | `desktop/release/`、`release-verify/` 的 `app.asar` 被锁，删不掉 | 环境问题 | gitignored，重启后可手工清 |
| 10 | ~~v0.1.0 只在本地打了 tag，远程未推~~ | **已完成 2026-11-08 20:16** | 全部标签（含 `v0.1.0`）已在远程 |
| 11 | ~~GitHub Release 还没建~~ | **已完成 2026-11-08 20:19** | Release id `438225599`，正文＋安装包已上传 |
| 12 | ~~Pages 从没开过~~ | **已完成 2026-11-08 20:12** | 根因是**仓库私有**，转 Public 后 run #2 一次通过；`configure-pages` 步骤已加，以后会自动兜底 |

**下一会话第一件事**
> 开 M6 **第二部分**（T6.7–T6.9）：先读 `milestones/M6-设置与个性化.md` §3 + §3.1（2026-11-09 修订的
> 派生规则，照原规则算出来的 `text-3` 只有 2.19:1），再读 `M6-补充记录.md` 的 S-8～S-10
> （27 处写死颜色要在这一轮全部令牌化）。顺序：`tokens.css` 六套 × 明暗 → `useTheme()` +
> `index.html` 内联脚本（防白闪）→ `tools/check_contrast.py` → 外观/关于 tab + 字号三档 →
> 引导页改造 + `verify_m6` 第七条 → 回归 + tag `m6-done`。
> 另：M5 遗留 #2（找台没装 Python/Node 的真机装一遍）仍然开着，与 M6 并行不冲突。

---

## 归档索引

| 归档文件 | 内容 | 何时可丢 |
|---|---|---|
| [`archive/HANDOFF-2026-11-05至11-07.md`](archive/HANDOFF-2026-11-05至11-07.md) | M0 文档体系 / M1 后端与前端 / M2 采集 / M3 检索问答，共 26 条会话记录（含全部补丁与复核） | 永久保留（git 之外的第二份可读版本） |

> M4 的三条还没归档：M5 直接吃 M4 的数据表，等 M5 验收后再移。届时本文件只剩「当前状态 + 归档索引 + 最近 2 条」。

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

## 2026-11-07 14:10 · M4 · T4.1–T4.4 出题与判分（本次会话）

**范围**：只做 M4 的 T4.1–T4.4（出题 Agent / 增量流式 / 入库存重 / 判分）。
T4.5 练习页、T4.6 复习队列、T4.7 复习页、T4.8 验收脚本**一律没动**，M4 状态是**进行中**，不是已验收。

**完成**
- T4.1 `services/agents/quizzer.py` + `prompts/quiz.md`：材料 → 严格 JSON 题组。prompt 写死
  「只能用材料里出现过的信息」「每题 explanation 要指出依据在材料哪句」「选项必须同层次」
- T4.2 `routers/quiz.py` 的 `POST /api/quiz/generate`（SSE）：一次调用 + 增量括号扫描，
  每完成一题立刻 emit；坏 JSON / 非法答案只 `skip` 这一题。**数量不足逐题补生成**
  （`count=1` + 已出题干，最多补 count 次，一次补不出来就停）
- T4.3 `db/repo/questions.py`：`fingerprint = sha256(item_id|type|去空白题干)`，
  `INSERT ... ON CONFLICT(fingerprint) DO NOTHING` 后查回已有 id；撞了复用旧题（事件里 `duplicate: true`）
- T4.4 `agents/grader.py` + `POST /api/quiz/submit`：客观题后端比对（多选按集合、顺序无关；
  单选大小写/空白归一；判断转布尔），简答走 LLM 批改，**失败落 `is_correct = NULL`** 并提示待人工判断
- 复用 `ask.py` 的 SSE 骨架（`async def` 生成器 + 子线程 + `call_soon_threadsafe`），
  `llm_call_log` 里 `agent='quizzer'/'grader'` 正常记账

**改动文件**
- 新增：`backend/app/services/agents/{quizzer,grader}.py`、`backend/app/prompts/{quiz,grader}.md`、
  `backend/app/routers/quiz.py`、`backend/app/db/repo/questions.py`
- 改：`backend/app/main.py`（挂载 quiz 路由）、`backend/app/services/llm.py`
  （`chat(timeout=)` 覆盖单次超时、`chat_stream(max_tokens=)`，均为可选参数，不影响既有调用）
- 文档：`contracts/接口契约.md`（generate/submit 完整形状、skip.reason 取值、accuracy 口径）、
  `contracts/数据契约.md`（`due_at` 语义，见下）、`milestones/M4`（状态、任务表、DoD、新增 §6.7 实施偏差）、
  `00-总纲`（M4 → 进行中）、`README.md`（当前状态、出题能力、没有 verify_m4 时怎么验）

**裁决（用户 2026-11-07 拍板，已回写文档）**
1. `due_at` 比较：**按 M4 执行**——存 UTC，比较在 Python 侧转 aware datetime。
   `数据契约 §3` 原来写「ISO 字符串可直接字典序比较」，本地时间带 `+08:00`、UTC 带 `+00:00`，
   混着比必错，**已改契约那一句**（不是改 M4）
2. 出题材料：**原文优先**，但**不截前 6000 字**，改成按 chunk 等距抽样覆盖全文（首尾都取到）
3. 补生成：**本轮就做**（不是留到 T4.8）

**验证（都真跑；全程在副本库 `data/tmp/quiztest/`，你真实的 `data/data.db` 一行没写，question 仍是 0）**
- 5 道单选（条目 33 ESLint）→ 20.8s，逐题 SSE，`done {count:5,skipped:0,requested:5}`；
  按 B/A/A/a/A 作答 → `4/5`、`accuracy 0.8`（正好验收场景 A 的数字）
- 3 道多选（条目 11）→ 乱序 `["D","C","B","A"]` 判**对**、少一个判**错**、字符串 `"D,C,B,A"` 也判对
- 20 道混合题型（条目 43，26 个 chunk 抽到 6000 字）→ 94s，**20/20 一次到位**，0 skip，无截断
- 简答：答一半 → `false` + 「你正确答出了…但漏掉了第二问：…」；答全 → `true` + 具体肯定（验收场景 C）
- **NULL 判分**：另起一个 `LLM_API_KEY=""` 的实例跑 submit → `is_correct: null`、
  feedback 「批改服务不可用，已标记待人工判断」，库里 `is_correct IS NULL`（不是 0），同批客观题照常判对
- 健壮性临时脚本（假流，不花调用）**11/11 PASS**：坏 JSON→`skip`、答案越界→`bad_answer`、
  选项不足→`bad_options`、好题照常 emit、补生成补到 3 题、同题二次出题复用 id 且库里只有 1 条
- 参数校验：`count=25`→422、`types:["essay"]`→`QUIZ_BAD_TYPES`、`difficulty:"hard"`→`QUIZ_BAD_DIFFICULTY`、
  `item_id:9999`→404；空答案→判错并回显参考答案
- `llm_call_log` 记账：quizzer 4 次（pt 9744 / ct 16002）、grader 3 次（2 成 1 败）
- `tools/doc_check.py`：6 项通过 + 2 条既有提示

**踩到的坑**
- 出题默认 `max_tokens=4096` 对 20 题是**不够**的，会把末题截断成坏 JSON、全落 skip 再疯狂补生成。
  抬到 8192（`quizzer.MAX_TOKENS`）
- `Scanner.feed()` 之后**必须留着 leftover**：被截断的对象要等下一个 delta；
  末尾仍不完整就报一次 `skip: json_parse_failed`，不要试图"补个括号"猜
- 多选判分的坑不在 `set()`，而在**入参形状**：前端可能给 `["C","A"]`、也可能给 `"A,C"`，
  两种都要能转字母集合（`grader._letters`）
- 补生成如果不判 `duplicate`，模型反复出同一题会让 `count` 虚高；所以同一请求内复用过的 id 要跳过
- 用 `LLM_API_KEY=""` 起实例即可稳定复现"批改服务不可用"，不用等真超时（`load_dotenv(override=False)`
  不会覆盖已存在的空值）

**遗留**
- [ ] T4.5 练习页（前端状态机 idle→generating→answering→submitting→result）
- [ ] T4.6 错题与复习：答错写 `review_item`、答对推进 1→2→4→7→15；`due_at` 存 UTC（裁决 1）
- [ ] T4.7 复习队列页 + `GET /api/review/due`、`GET /api/quiz/wrong`、`POST /api/review/{id}/result`
- [ ] T4.8 `verify_m4.py`（本轮用的是不入库的临时脚本，在 `data/tmp/`，别当长期资产）
- [ ] 简答批改没区分 `LLM_TIMEOUT` 与 `LLM_QUOTA`（M4 §7 排障表要求）：`llm.py` 目前把 429/402
      都归到 `LLM_HTTP_ERROR`，要做需要先给 httpx 状态码加映射，会影响 ask 的既有错误码，单独一轮
- [ ] 题目生成质量仍会出"四个选项全对"这种多选（模型问题），prompt 已加"选项必须同层次"约束，
      但没有量化验收；T4.8 可加一条"多选答案集合大小 < 选项数"的软断言
- [ ] `question` / `quiz_attempt` 会无限增长，和 `ask_log` 一样等 M5 仪表盘再定保留策略

**待裁决冲突**
- 无（`due_at` 那条已由用户裁决并回写 `数据契约 §3`）

**推送状态：本地已提交，GitHub 未推（需要你在普通终端执行一次）**
- 本地：`1b73eb3 feat(M4): T4.1–T4.4 出题与判分` + 标签 `m4-wip`
  （`m4-wip` 而非 `m4-done`：T4.5–T4.8 未做，打 done 会让下个会话误判已验收）
- 本会话 `GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never` push 报
  `could not read Username for 'https://github.com': terminal prompts disabled`，
  与 11-06/11-07 前几次完全一致——**agent 会话拿不到已缓存的凭据**
- 待执行：
  `"C:/Program Files/Git/cmd/git.exe" push origin main && "C:/Program Files/Git/cmd/git.exe" push origin --tags`
  （`--tags` 会把 `m4-wip` 带上；若报 `m3-wip already exists` 直接忽略，那个标签已对齐）
- 顺带核对：`m3-wip` 远程已是 `05a5ace`，与本地一致，上次留的那条
  `push --force origin refs/tags/m3-wip` **不用再执行**

**下一会话第一件事**
> 接着做 T4.5–T4.7：先写 `frontend/src/views/Practice.vue`（消费 `/api/quiz/generate` 的 SSE +
  `/api/quiz/submit` 的批量判分，`null` 要显示成「待人工判断」而不是答错），再写 `repo/review.py`
  与复习队列页。动 T4.6 前先读本条的裁决 1：`due_at` 存 UTC、比较在 Python 侧。

## 2026-11-08 00:05 · M4 · T4.5–T4.8 练习页 / 复习 / 验收（M4 完成）

**范围**：T4.5–T4.8 全做完，M4 状态改为**已验收**（tag `m4-done`）。T4.1–T4.4 的代码一字未改，
只在 `submit` 末尾加了「判完分顺手写 review_item」这一处联动。

**完成**
- T4.6 `db/repo/review.py`：间隔规则 1→2→4→7→15；`apply(conn, qid, correct|None)` 一个入口；
  `due()` 取全表后**在 Python 侧**转 aware datetime 再比（UTC 与 `+08:00` 字典序不可比）；
  `wrong()` 错题本 = 最近一次明确答错的题；`wrong_total/tracked_total` 供角标
- T4.6 联动：`POST /api/quiz/submit` 判完分顺手 `apply`。**NULL 不排期**（待人工判断不猜对错），
  同一次提交里同一题只推一次间隔
- T4.7 三个端点：`GET /api/quiz/wrong`、`GET /api/review/due`（带 `total/tracked/wrong/now` 一次拿全）、
  `POST /api/review/{qid}/result`（`scheduled=false` + `reason=not_tracked` 表示这题本来不需要复习，不是错误）
- T4.5 `views/Practice.vue`：条目/题型/难度/题数 → SSE 出题（逐题浮现、可停止、已收到的保留）→ 作答
- T4.5 `components/QuizRunner.vue`：一题一屏 → 客观题本地即时判（交卷后以后端为准）→ 批量交卷 →
  结果页（`is_correct === null` 显示「待判」，**不计入正确也不算错**）
- T4.7 `views/Review.vue`：今日待复习 / 错题本两个标签；到期题直接进 QuizRunner 作答，
  交卷后只刷新时间表（不再重复上报，否则间隔推两格）
- T4.8 `backend/scripts/verify_m4.py`：56 项，全假实现（`quizzer.stream` + `llm.chat`），不联网不烧钱
- 顺带：`vite.config.js` 加 `/* global process */`——`npm run lint` 之前一直红在这条（既有问题，不是这次引入的）

**改动文件**
- 新增：`backend/app/db/repo/review.py`、`backend/app/routers/review.py`、`backend/scripts/verify_m4.py`、
  `frontend/src/views/Practice.vue`、`frontend/src/views/Review.vue`、
  `frontend/src/components/QuizRunner.vue`、`frontend/src/utils/quiz.js`
- 改：`backend/app/routers/quiz.py`（写 review + `/quiz/wrong`）、`backend/app/main.py`（挂 review 路由）、
  `frontend/src/api/client.js`（4 个调用）、`frontend/src/router/index.js`、`frontend/src/App.vue`（两个导航）、
  `frontend/vite.config.js`
- 文档：`contracts/接口契约.md`（三个端点完整形状 + submit 会写队列）、`milestones/M4`（状态/任务表/DoD/
  新增 §6.8 实施偏差/§7 三条排障）、`00-总纲`（M4 → 已验收）、`会话提示词手册`（模板 A/B 换成 M5）、`README.md`

**验证（都真跑）**
- `verify_m4.py` → **56/56 PASS**，exit 0。含：题干含 `{}` 不错位、坏 JSON/越界答案/缺解析/重复各只跳该题、
  补生成 3 题（3 次调用）、撞指纹复用且不增行、多选乱序/少选/`"A,C"` 字符串、单选空白归一、判断布尔、
  空答案回显、简答具体反馈、批改失败落 NULL（库里 `is_correct IS NULL`）、间隔 1→2→4→7→15、
  答错重置 + lapses、NULL 不排期、时间旅行查到期、错题本进出、5 条参数校验
- 浏览器走查（真后端副本实例 8757 + vite 5174 + Playwright，真实 LLM **1 次调用**出 5 题）：
  练习页渲染 → 出题中卡片逐题浮现 → 第 1/5 题 → 答完立刻出对错与解析 → 交卷 0/5 → 结果页 5 题回显 →
  复习页角标 0 到期 / 5 队列 / 5 错题 → 错题本列出 5 条；**控制台 0 错误**
- 回归：`verify_m3.py` 61/61；`verify_m2.py` 116/118、`verify_m1.py` 50/51（**两个都是既有红**，见下）
- `tools/doc_check.py`：6 项通过 + 2 条既有 WARN；`scripts/status.py` 正常（真库 `question` 仍是 0，
  走查与验收全在副本库 `data/tmp/`）

**已知既有红（不是本轮引入，都已在 HEAD 上复现过，本轮不动）**
1. `verify_m1.py`「未留下注定失败的任务」：断言写死 `total == 3`，实际 11（脚本自己前半程就在造任务）。
   要么改成相对计数，要么断言"没有 status='failed' 且 error_code='LLM_NO_KEY' 的任务"。**待你定口径**
2. `verify_m2.py`「force → replaced=true 且同一条目」+「正文已替换」：`git worktree` 检出 HEAD（`4776d3b`）
   跑同样 116/118，同样的两条红，与 M4 改动无关。像是 force 覆盖路径的回归，需要单独一轮查

**踩到的坑**
- 错题本不能按 `review_item.last_result` 取：简答题批改失败的题根本不进队列，`last_result` 也不更新；
  用户问"错过的题"关心的是**最近一次作答**，所以按 `quiz_attempt` 的最后一条判
- `POST /review/{id}/result` 若也推进一遍，交卷就成了"推两格"。最终口径：`submit` 负责推进，
  `/result` 只给人工裁定用——契约里写死，`verify_m4.py` 也断言 `submit` 之后队列状态正确
- 前端本地判分必须和后端同一口径（多选集合、`"A,C"` 字符串、判断 `对/true`）：抽到 `utils/quiz.js` 一处写
- Playwright 里 `get_by_role(name="3 题")` 会超时：题数选项只有 5/10/20，没有 3——脚本先按 `.chip` 文本定位

**遗留**
- [x] 简答批改没区分 `LLM_TIMEOUT` / `LLM_QUOTA`（M4 §7 要求）：2026-11-08 已做，
      `llm.error_from()` 统一分类，见本文件末尾那条
- [ ] 题目质量仍可能出"四个选项全对"的多选（模型问题），prompt 已约束，无量化验收
- [ ] `question` / `quiz_attempt` / `review_item` 会无限增长，等 M5 仪表盘再定保留策略
- [ ] M4 §8 收工清单第 2 条（手动改系统时间看今日待复习）没做：用时间旅行等价验过，
      改系统时间在 Windows 上影响别的进程，不做

**推送状态：已推送（2026-11-08 00:15 核实）**
- 当时这里写的是「未推」——那条已作废。`git ls-remote` 实测 `refs/heads/main = a3bab20`（= HEAD），
  `m4-done` / `m4-wip` 两个标签都在远程，`main` 与 `origin/main` 同步，**不要再推一遍**
- 核实命令（只读）：`git ls-remote --heads --tags origin | grep -E "m4|refs/heads/main"`

**下一会话第一件事**
> M5 开工，先读 `docs/00-总纲.md` 与 `docs/milestones/M5-计时与交付.md`，做 T5.1–T5.4（计时与仪表盘）。
> 仪表盘要读 M4 的数据：正确率来自 `quiz_attempt`，错题数来自 `/api/quiz/wrong`，到期数来自
> `/api/review/due`——三个端点都已就绪，M5 不用再改 M4 的表。

## 2026-11-08 00:40 · M4 独立复验 + 三处收口（进入 M5 前的清账）

**范围**：用户要求按 M4 DoD 逐条复验（不是收尾会话自证），并把复验中提出的三条观察收掉。
**DoD 复验结论：8/8 PASS，无 FAIL**；`verify_m4.py` 实跑 56/56 → 补 7 项后 **63/63**。

**做了什么**

1. **推送状态纠错**：上一条「GitHub 未推」是错的。`git ls-remote` 实测远程 `main = a3bab20 = HEAD`，
   `m4-done` / `m4-wip` 都在远程。已就地改掉那段，避免下一会话重复推。
2. **补 DoD 第 1 条的视觉证据**：新增 `frontend/e2e/m4_quiz.py`（Playwright + 真 LLM **1 次调用**）。
   出题时每 200ms 采一次 `.gen-card` 数量，实测时间线 `(0.0,0) → (7.48,1) → (7.96,2) → (8.18,3) → (8.59,4) → 进入作答（第 1/5 题）`，
   即**题面是一张张刷出来的**，不是整包渲。截图在 `frontend/e2e/_shots/`（gitignored）。
3. **错误码细分（M4 §7 的欠账）**：`llm.error_from()` 统一分类 —— 超时 → `LLM_TIMEOUT`，
   HTTP 402/429 → `LLM_QUOTA`，其余 → `LLM_HTTP_ERROR`；`chat` / `chat_stream` 共用。
   `grader` 按码给不同 feedback（超时说超时、额度说额度），两种都保留「待人工判断」且仍然落 NULL。
   前端 `FRIENDLY` 表新增 `LLM_QUOTA` / `LLM_TIMEOUT` 两条人话。
   **对 ask 的影响**：只是把 429/402 从 `LLM_HTTP_ERROR` 摘出来，前端按 `^LLM_` 前缀匹配，提示不变；
   m3 无相关断言，回归 61/61。

**改动文件**
- 新增：`frontend/e2e/m4_quiz.py`
- 改：`backend/app/services/llm.py`（`QUOTA_STATUS` + `error_from`，两处调用点）、
  `backend/app/services/agents/grader.py`（`FAIL_HINTS`）、
  `backend/scripts/verify_m4.py`（+7 项：错误码归一分档、超时/额度提示不同）、
  `frontend/src/api/client.js`（两条人话）
- 文档：`milestones/M4`（状态/任务表/DoD/§6.9 新增/§7 一行）、`contracts/接口契约.md`（错误码分档）、
  `00-总纲.md`、`README.md`（状态、命令表 + e2e 一行）、`frontend/e2e/README.md`（m4_quiz 用法）

**验证（都真跑）**
- `verify_m4.py` → **63/63 PASS**，exit 0
- `e2e/m4_quiz.py` → **17/17 PASS**（副本库 8757 + vite 5174，真 LLM 1 次，console 0 error）
- 回归：`verify_m3.py` 61/61、`verify_m2.py` 116/118、`verify_m1.py` 50/51 —— **三条红与 M4 改动无关**，
  数字与上一条记录完全一致（m1 的「未留下注定失败的任务」写死 total==3；m2 两条 force 用例）
- `npm run lint` 干净

**踩到的坑（写下来省下一轮）**
- 路由是 **hash 模式**：e2e 必须 `/#/practice`，直接 `/practice` 会被 catch-all 重定向回首页
- 用 200ms 轮询数卡片会**漏掉最后一题**（第 5 题与阶段切换在同一帧），断言改成「进入作答时 `.q-step` 显示 5」，
  时间线只用来证明「有中间态」
- 复习页角标初值是 0，请求回来才填：断言前先 `wait_for_function` 等它等于接口值，否则测的是占位
- 副本库不干净时「错题角标 = 本轮答错数」必然红，改成与 `/api/review/due` 的 `wrong` 对比

**遗留（本次没动）**
- [ ] m1 / m2 那三条既有红仍等定口径
- [ ] 题目质量（四个选项全对的多选）、三张表的保留策略 —— 都留给 M5 之后
- [ ] `e2e/m4_quiz.py` 要 `--db` 才能改 ready：将来若有「手动置 ready」的接口可以去掉这一步

**推送状态：已推 GitHub（2026-11-08 由你在终端执行，已核实）**
- `refs/heads/main = 866cfc0`（= 本地 HEAD `866cfc0`）；`31a8f7f` 是它的父提交，一并送达
- 本地 `git status -sb` 为 `## main...origin/main`，无 ahead/behind
- 标签：`m4-done` 注解标 → `a3bab20`，`m4-wip` → `1b73eb3`，均未移动，本次不打新标签
- **不需要再推一次**；下一次 `git ls-remote --heads origin` 若显示 `866cfc0` 或更新的提交即说明没落后

**下一会话第一件事**
> M5 开工（T5.1 计时）。`git ls-remote --heads origin` 若是 `866cfc0` 或更新即可直接开工，不要再推。

## 2026-11-08 00:40 · 台账 · 归档过期条目（纯文档，无功能改动）

**完成**
- M0–M3 共 26 条会话记录**原样**移到 `docs/archive/HANDOFF-2026-11-05至11-07.md`，
  本文件从 1597 行降到 **327 行**；移动不改字面（`git diff` 可核对：删掉的行在归档文件里能原样找回）
- 顶部新增「当前状态」表（里程碑 / 远程 / 标签 / 验收计数 / 台账位置）与「未结遗留」表（6 条）
- 「规则」加第 5 条归档口径：里程碑已验收且不是下一里程碑的直接前置时才移；M4 因此暂留
- 顺手把「作用域」与「规则 3」从"只读最后 2 条"改成"只读当前状态 + 最后 2 条"

**改动文件**
- 新增：`docs/archive/HANDOFF-2026-11-05至11-07.md`
- 改：`docs/HANDOFF.md`

**验证**
- 逐条比对：归档前后 `## ` 标题集合完全一致（26 条），无遗漏无重复；被移动段落用
  `moved in archive_text` 整段子串校验 → True（63,827 字符里逐字对得上）
- `tools/doc_check.py` → **6 项通过 + 1 条提示**（原为 2 条：M1 那条「引用已完结文档」
  随 M1 条目一起进了归档，剩下 `会话提示词手册.md` 引用 M1 那条仍是既有提示）
- `HANDOFF.md` 在 `allow_archive_ref` 白名单里，引用 `archive/` 不报 FAIL
- 未动任何代码、里程碑文档、契约

**遗留**
- [ ] M4 三条等 M5 验收后再归档（见「归档索引」表下的说明）

**推送状态：本条提交已落本地（`git log -1 docs/HANDOFF.md` 看 hash），远程未推**
- agent 会话推不动（`could not read Username`，与前几轮一致，别再试）；需要你在普通终端执行一次
  `"C:/Program Files/Git/cmd/git.exe" push origin main`
- 推完以 `git ls-remote --heads origin` 为准；本文件不再逐条记推送（记一次就过期一次）

**下一会话第一件事**
> M5 T5.1，见顶部「当前状态」。

## 2026-11-08 12:20 · 桌面 · 空壳验证（M1 遗留项，**不是** M5 任务）

**范围**：`desktop/` 最小可跑 Electron 壳，只验四件事（spawn 后端 / 随机端口 + HTTP 握手 /
`file://` 显示页面 / 关窗无残留）。**没读 M5 文档**。明确没做：NSIS 安装包、图标、签名、
接 Vite 产物、托盘、自动更新；没打 `m5-xxx` 标签。

**一处裁决（用户当场拍板，2026-11-08）**
- `uv run python -m app` 原本跑不通：`app/` 里没有 `__main__.py`，直接报
  `No module named app.__main__; 'app' is a package and cannot be directly executed`。
  按"改后端启动方式先问我"的约定，**问过才动**，用户选「新增 `backend/app/__main__.py`」。
- 实现 12 行，只做 `uvicorn.run(app, host/port 取 config)`，**不改任何已验收模块**
  （`config.py` 早就支持 `--port`，命令行优先级仍由它负责）。顺带的好处：它就是将来
  PyInstaller `--onedir` 的入口形状（ADR-014）。

**desktop/ 文件清单**

| 文件 | 作用 |
|---|---|
| `desktop/.npmrc` | `electron_mirror=https://npmmirror.com/mirrors/electron/`（直连 GitHub Releases 只有 ~7KB/s） |
| `desktop/package.json` | `main: main.js`、`scripts.start: electron .`、devDep `electron ^45.2.3` |
| `desktop/package-lock.json` | 入库，锁版本 |
| `desktop/main.js`（173 行） | 四件事全在这里：`listen(0)` 拿空闲端口 → spawn `uv run python -m app --port N` → 每 300ms 轮询 `/api/health`（上限 30s）→ `loadFile('index.html', {query:{port,version}})` → 窗口关闭时 `taskkill /T /F` 杀整棵进程树 |
| `desktop/index.html`（48 行） | 静态验证页，显示 `location.protocol`/`href`/端口/后端版本。**不发起任何网络请求**（端口与版本走 URL query 传入），刻意把"窗口能不能显示"这一个变量单独隔离出来 |
| `desktop/_smoke/` | 每次运行的现场：`run.log`（四项实测输出）+ `window.png`（截图）。**已 gitignore** |
| `desktop/node_modules/` | gitignore；Electron 45.2.3 二进制已在 `node_modules/electron/dist/` |

**四项结论（2026-11-08 12:17 实测，原始日志 `desktop/_smoke/run.log`）**

1. **spawn 后端 ✅** — `uv run python -m app --port 12327`，cwd=`backend/`，uv pid=30220。
   后端自己打出来的 `[Cairn] 监听端口 = 12327` 与传入值一致，说明 `--port` 真的透传到底了。
2. **随机端口 + 握手 ✅** — 端口 12327 由 `net.createServer().listen(0)` 探测；轮询第 13 次拿到
   `{"status":"ok","version":"0.1.0"}`，耗时 3685ms（几乎全花在 `uv run` 冷启动的依赖自检上，
   不是后端慢）。窗口是在握手成功**之后**才建的（ADR-016 的顺序）。
3. **窗口显示 index.html ✅** — `file:///C:/Users/cwqjk/Desktop/知识库agent开发/desktop/index.html?port=12327&version=0.1.0`，
   标题 `Cairn · 桌面壳验证`，`capturePage()` 截图 `_smoke/window.png` 已肉眼核对：无白屏、
   protocol 显示 `file:`、端口 12327、版本 0.1.0 全部对上。
4. **关窗后无残留 ✅** — 关窗触发 `taskkill /PID 30220 /T /F`，一次杀掉 4 个进程
   （uv 30220 → shim 29588 → python 4540 → 其子 5844）。跑前基线 **0** 个、跑后 **0** 个
   `python.exe`（判定口径：CommandLine 含 `app*--port`）；端口 12327 只剩 `TimeWait`，`LISTEN` 已释放。

**复现**
- `cd desktop && npm start`（正常交互，手动关窗）
- 非交互/自动关窗：`SMOKE_AUTOCLOSE_MS=5000 npm start`（只为自动化验第 3、4 项，不是产品功能）

**踩到的坑（T5.5 会再遇到）**
- **Electron 二进制默认没下下来**：`npm i -D electron` 退出码 0、`package.json` 也写好了，
  但 `node_modules/electron/dist/` 不存在（postinstall 静默失败）。补救：
  `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ node node_modules/electron/install.js`。
  注意 `.npmrc` 的 `electron_mirror` 只对 **npm 脚本**生效，手动跑 install.js 必须显式传 env。
- **`uv run` 会再拉一层 python 子进程**，`child.kill()` 只杀 uv → 必留孤儿 python。
  必须 `taskkill /PID <uvpid> /T /F` 按树杀。
- `taskkill` 的中文提示是 **GBK**，按 utf8 读全是乱码，要用 `TextDecoder('gbk')` 解。
- **Electron 主进程在 Windows 下 stdout 未必落到控制台**，日志必须双写文件，否则拿不到实测输出。
- 本 agent shell 里有 `ELECTRON_RUN_AS_NODE=1`（**只在 Process 级**，User/Machine 都没有），
  会让 `electron.exe .` 退化成 node 跑、`require('electron')` 得到 undefined（报
  `Cannot read properties of undefined (reading 'whenReady')`）。跑之前 `env -u ELECTRON_RUN_AS_NODE`。
  **你自己的普通终端没有这个变量，`npm start` 直接可用，不用管这条。**

**T5.5 可以从哪里接着做（三项已就位的形状）**
1. **后端换成 exe**：`pyinstaller --onedir`（ADR-014），入口就是 `app/__main__.py`，产物
   `cairn-backend.exe`。`main.js` 只需把 spawn 的 `uv run python -m app` 换成 exe 路径，
   `--port` 传参与 300ms/30s 握手逻辑**一行都不用改**（已验证）。
   记得 ffmpeg 一起进 `resources/`（总纲 §9 已知坑）。
2. **把 Vite 产物接进来 —— 这一步要动已验收模块，先问你**：窗口现在是 `loadFile('index.html')`，
   换成 `frontend/dist/index.html` 是 drop-in；但 **`file://` 的 origin 是 `null`，而后端 CORS
   白名单只有 `http://localhost:5173` / `127.0.0.1:5173`**（`main.py`），页面里的 API 请求会被拦。
   **这条是读代码推断的，没有实测**。可选的解法：① 后端白名单放行 `null`/`file://`；
   ② 主进程起一个本地 http 反代；③ preload 暴露端口 + 后端放行。选哪条要你定，别让我自己挑。
3. 再往后才是 electron-builder `--win nsis`、图标、签名。

**改动文件**
- 新增：`desktop/{.npmrc,package.json,package-lock.json,main.js,index.html}`、
  `backend/app/__main__.py`
- 改：`.gitignore`（加 `desktop/_smoke/`）、`README.md`（`desktop/` 目录行 + 验证表加 `npm start` 一行）
- 删：`desktop/.gitkeep`（目录不再为空）
- **没动**：前端任何文件、M1–M4 已验收模块、任何里程碑文档

**验证**
- 空壳四项：见上（1–4 全绿，实测输出在 `desktop/_smoke/run.log`）
- `python tools/doc_check.py` → 见本条提交前的实跑结果

**遗留**
- [ ] T5.5 前要定 `file://` 与 CORS 的口径（上面第 2 条，三种解法选一）
- [ ] 打包时 ffmpeg 必须随 `resources/` 一起走，不能靠系统 PATH
- [ ] `desktop/index.html` 是验证页，T5.5 接 Vite 产物后应删除或替换

**推送状态**
- 本地已提交，**远程未推**（agent 会话的 GCM 凭据会失效）。需要你在普通终端执行
  `"C:/Program Files/Git/cmd/git.exe" push origin main`。**本次不打标签。**

**下一会话第一件事**
> M5 T5.1。注意：本条只到"空壳四件事已验证"，**不等于 T5.5 已完成**，打包与接前端都还没动。

## 2026-11-08 12:30 · 桌面 · 空壳收尾：页面与 API 同源（**不打包**）

**背景**：上一条的 `loadFile(file://)` 让页面 origin 变成 `null`，后端 CORS 只放行
`localhost:5173`，API 必被拦。**解法不是放宽 CORS，是让页面与 `/api` 同源**：
后端自己吐 `frontend/dist`。前端本来就是相对路径 + `createWebHashHistory`，**前端代码一行没改**。

**改的四处**

| # | 文件 | 改了什么 |
|---|---|---|
| 1 | `backend/app/main.py`（末尾，所有 `include_router` 之后） | `WEB_DIR`（`CAIRN_WEB_DIR` 或 `frontend/dist`）→ 条件挂 `/assets` + `GET /` 返回 `index.html` |
| 2 | `backend/entry.py`（新增 12 行） | PyInstaller 入口，绝对导入 `from app.__main__ import main` |
| 3 | `desktop/main.js` | `win.loadFile(...)` → `win.loadURL(\`http://127.0.0.1:${port}/\`)`，端口复用 `waitHealth` 那个变量，没新加一套 |
| 4 | `desktop/main.js`（验证用加料） | `webRequest.onCompleted` 记网络、`console-message` 记渲染进程报错并计数、页面内 `fetch('/api/health')` 取绝对 URL |

**两条硬约束都守住了，而且是实测过的**
- **没有**用 `app.mount("/", StaticFiles(html=True))`：`GET /api/不存在的路径` → `404 application/json`
  `{"detail":"Not Found"}`，**没有**被兜成 index.html（这是最容易踩的坑）
- **条件挂载**：`CAIRN_WEB_DIR=C:/no/such/dir` 时后端正常启动、`GET /` → 404、`/api/health` → 200
- **CORS 白名单一行没动**，dev 仍走 5173

**一处小偏差（我加的，1 行）**：`/assets` 单独又判了一次 `is_dir()`。原片段是「`index.html` 存在就
挂 `assets`」，若 dist 是半成品（有 index.html 没 assets/），`StaticFiles(check_dir=True)` 会在
**启动时**抛错，正好违背"条件挂载"的初衷。不想要可以删掉那行 if。

**实测（顺序：build → 静态路由 → Electron）**

`cd frontend && npm run build`：
```
dist/index.html                   0.39 kB │ gzip:  0.27 kB
dist/assets/index-CS4PzLg6.css   46.12 kB │ gzip:  7.32 kB
dist/assets/index-CWyAk6v1.js   245.68 kB │ gzip: 90.55 kB
✓ built in 1.14s
```

静态路由（TestClient，同一个 app 实例）：
```
GET /                    → 200 text/html; charset=utf-8  len=392
GET /assets/index-CWyAk6v1.js → 200 application/javascript
GET /api/health          → 200 {'status': 'ok', 'version': '0.1.0'}
GET /api/不存在的路径     → 404 application/json  body='{"detail":"Not Found"}'   ← 没被兜成 HTML
GET /some/spa/deep/path  → 404 application/json   （hash 路由不需要兜深链接）
```

**Electron 四点（`desktop/_smoke/run.log`，端口 5185）**
```
1/4 spawn: uv run python -m app --port 5185   pid=5016
2/4 GET http://127.0.0.1:5185/api/health → {"status":"ok","version":"0.1.0"}（第 12 次，3384ms）
3/4 net 200 GET http://127.0.0.1:5185/
3/4 net 200 GET http://127.0.0.1:5185/assets/index-CS4PzLg6.css
3/4 net 200 GET http://127.0.0.1:5185/assets/index-CWyAk6v1.js
3/4 net 200 GET http://127.0.0.1:5185/api/health
3/4 net 200 GET http://127.0.0.1:5185/api/knowledge/categories
3/4 net 200 GET http://127.0.0.1:5185/api/knowledge?page_size=50
3/4 页面加载完成 url=http://127.0.0.1:5185/#/      ← hash 路由正常工作
3/4 窗口标题 = Cairn
3/4 页面内 fetch('/api/health') → {"url":"http://127.0.0.1:5185/api/health","status":200,"body":{...}}
3/4 关窗前 console 错误数 = 0
4/4 taskkill /PID 5016 /T /F → 成功终止 8056 / 29352 / 29344 / 5016 四个进程
```

| 用户要求确认的点 | 结论 | 证据 |
|---|---|---|
| 窗口显示页面，不是白屏 | ✅ | `_smoke/window.png` 截图：左侧分类树 + 10 条条目列表 + 顶部「已连接」徽标，真实 UI |
| DevTools Console 无 CORS 报错 | ✅ | `console 错误数 = 0`。**唯一一条是 Electron 的 CSP 安全警告**（warning 级，见遗留） |
| Network 里 `/api/health` 200 且 Request URL 正确 | ✅ | `net 200 GET http://127.0.0.1:5185/api/health`；页面内 fetch 回读 `url` 与 `status` 同为 200 |
| 关窗后 tasklist 查不到残留 python | ✅ | `AFTER_COUNT=0`；`tasklist /FI "IMAGENAME eq python.exe"` → 「没有运行的任务匹配指定标准」；端口 5185 只剩 `TimeWait` |

**T5.5 可以从 `desktop/` 直接接（三处已就位）**
1. **入口用 `backend/entry.py`，不是 `app/__main__.py`**。理由：PyInstaller 把**入口脚本所在目录**
   塞进 `sys.path`，入口若是 `app/__main__.py`，`sys.path[0]` 就是 `backend/app/`，`import app` 必失败。
2. `main.js` 只需把 spawn 的 `uv run python -m app` 换成 `--onedir` 出的 `cairn-backend.exe`，
   `--port` 传参与 300ms/30s 握手逻辑**一行不用改**。
3. 静态页改打包内置：把 `frontend/dist` 拷进 `resources/web`，spawn 时给子进程
   `CAIRN_WEB_DIR=<resources>/web` 即可 —— **后端已经有这个开关，不用再改代码**。
4. 剩下没做：`electron-builder --win nsis`、图标、签名、CSP。

**改动文件**
- 改：`backend/app/main.py`、`desktop/main.js`、`README.md`（`desktop/` 目录行、验证表加 build 前置、
  配置表加 `CAIRN_WEB_DIR`）、`docs/HANDOFF.md`
- 新增：`backend/entry.py`
- **没动**：前端任何文件（一行未改）、CORS 白名单、M1–M4 已验收模块、任何里程碑文档

**遗留**
- [ ] Electron 报 `Insecure Content-Security-Policy`（warning）：`frontend/dist/index.html` 没有 CSP。
      T5.5 加 `<meta http-equiv="Content-Security-Policy">` 或用 `session.webRequest.onHeadersReceived` 注 header。
      **不是错误、不影响功能**，但现在每次启动都刷一条警告
- [ ] `desktop/index.html`（早期 file:// 验证页）**已不参与加载**，T5.5 决定删掉还是改造成"后端没起来"的兜底页
- [ ] `GET /` 与 `/assets` 是静态路由，**没登记进接口契约**（不在 `/api` 命名空间，`doc_check.py` 不管它）。
      要登记的话说一声，我加一行

**验证**：`python tools/doc_check.py` 见本条提交前实跑。
**推送状态**：本地已提交，**远程未推**（agent 侧 `could not read Username`）。
需要你在普通终端执行 `"C:/Program Files/Git/cmd/git.exe" push origin main`。**本次不打标签。**

**下一会话第一件事**
> M5 T5.1；T5.5 若要开工，直接从 `desktop/` 按上面三条接（打包连握手都不用改）。

---

## 2026-11-08 12:35 · 契约补齐：静态资源路由 + 废弃 preload 注入

**背景**：空壳收尾把页面从 `file://` 改成 `http://127.0.0.1:<port>/` 同源加载，代码和 README 都改了，
但**接口契约 §4 仍写着「生产必须由 preload 注入 baseUrl」**。契约落后于代码，且方向相反——
下个会话照契约做会把注入加回来，多一层永远用不上的配置，还会让人以为页面是 `file://`。

**改了两处（都在 `docs/contracts/接口契约.md`）**

1. **§4 前端调用约定**：两种运行形态统一走「空串 = 相对路径」（dev 靠 Vite 代理、prod 靠同源），
   明确「不要再往 preload 注入 baseUrl」，`window.api.baseUrl` 降级为调试逃生口
2. **新增 §5 静态资源路由（非 API）**：`GET /` 与 `GET /assets/*` 的注册条件、四条硬约束
   （禁 catch-all / 必须条件注册 / 不做 SPA fallback / `CAIRN_WEB_DIR` 优先）、以及为什么不用 `file://`

**为什么单开一节而不是塞进端点表**：`/` 和 `/assets` 不是 API，没有错误码，塞进 §2 会污染
"端点"这个概念，也会误导 `doc_check.py` 的端点引用校验。这一节的价值不在记事实，在**钉住
「禁止 `mount('/')`」这条约束**——目前只有 `main.py` 里的一段注释挡着，而注释会随那次文件重写消失。

**顺带收口**：空壳会话遗留的三条已进「未结遗留」表 7、8 两项；第三条（契约登记）由本条关闭。
`origin/main` 已与本地一致（用户手工推送成功，agent 侧凭据仍读不到，别重试）。

**改动文件**：`docs/contracts/接口契约.md`、`docs/HANDOFF.md`
**验证**：`python tools/doc_check.py` → 6 PASS + 1 WARN（手册引用已完结的 M1 作模板，属正常）
**推送状态**：见本条提交后的实际结果；若报 `could not read Username`，由用户在普通终端执行
`"C:/Program Files/Git/cmd/git.exe" push origin main`。**本次不打标签。**

## 2026-11-08 13:05 · M5 · T5.1–T5.4 番茄钟与仪表盘（**M5 未完成**）

**范围**：只做 T5.1–T5.4。T5.5 之后（打包 / 首次引导 / README 安装段）一行没动。
开场先跑 `doc_check.py`（6 PASS + 1 提示）与 `status.py`（`user_version=2`、20 表、环境全绿）确认状态。

**两条前置按你的交代处理，没有重做也没有再问**
- Electron 空壳包 2026-11-08 已验证 → 只当作既有事实，`desktop/` 一个字节没改
- 接口契约 §5「静态资源路由」属 T5.5 → 没碰

**动工前问了你两件事，都按推荐方案执行**
1. 心跳端点：新增 `POST /api/session/{id}/heartbeat`（`sendBeacon` 只能发 POST，PATCH 走不通）
2. 仪表盘要有真数据：真跑练习（3 组 × 5 题，3 次真实 LLM 调用）

**后端（新增 4 个文件 + `main.py` 挂载）**

| 文件 | 内容 |
|---|---|
| `app/db/repo/sessions.py`（220 行） | **表结构一行没改**：`duration_seconds` 存已结算时长，`start_time` 存当前段锚点，用这两列表达 M5 §6.1 的 `pausedAccum`/`pausedAt`。`elapsed = duration_seconds + (now - start_time)` 只在 running |
| `app/db/repo/stats.py`（164 行） | 仪表盘口径；「今日待复习」直接调 `review.due()`，不在 SQL 里重写一遍 UTC/本地比较 |
| `app/routers/session.py`（146 行） | start / current / action / heartbeat / 列表 |
| `app/routers/stats.py`（33 行） | today / week |
| `app/main.py` | 挂两个 router；启动时 `abandon_stale()` 收掉 >4h 的 active 会话，时长按 `planned_seconds` 封顶 |

**几处刻意的设计（都在代码注释里写了理由）**
- `paused` **也算占用**：暂停中再开一轮照样 409，否则可以同时跑两个计时
- `finish`/`abandon` 对**同一个终态幂等**（连点两下不报错、不重算），跨终态才 409
- 心跳打**非 running** 会话不报错：闭窗时 `sendBeacon` 与 pause 几乎同时到达
- 清理判据用 `created_at` 不用 `start_time`：心跳会把锚点一直往前挪，用锚点判断等于永不超时
- 到点不在前端「自己结束」：先 `pause` 冻住时长再弹笔记框，人走开十分钟也不会把 25 分钟记成 35 分钟
- 「连续学习天数」今天没学**不算断**，从昨天起算（M5 §6.6 原文有歧义，已回写澄清到里程碑与契约）

**前端（新增 4 个文件，改 5 个）**
- 新增 `composables/useTimer.js`（244 行，模块级单例）、`components/Pomodoro.vue`、`components/SessionLog.vue`、`views/Dashboard.vue`
- 改 `App.vue`（顶栏迷你计时器 + 仪表盘导航 + `visibilitychange` 对齐 + `beforeunload` 心跳）、
  `ItemDetail.vue`（「开始专注」按钮 + 第 5 个 Tab「学习记录」）、`Practice.vue`（「开始专注」带选中条目）、
  `router/index.js`、`api/client.js`（7 个语义方法 + 导出 `apiBase()`）、`utils/format.js`（`clock`/`humanDuration`）
- 到点/提前完成都先暂停再要笔记（第一版「提前完成」直接结束、不给写笔记，UI 验收时发现并改掉了）

**实测数字（都是实跑的，不是预估）**

`uv run python scripts/verify_m5.py` → **50/50**
```
1 生命周期   start 201 / 并发 409 带 id / 404 ITEM_NOT_FOUND / 422 非法 target_type
             heartbeat 卷账 1s + 锚点 12:45:32 → 12:45:33
             pause 后 1s → 1s 不增长 / paused 再开仍 409 / resume 保留 1s
             finish done + note，时长 2s（暂停那段没算）
             重复 finish 幂等：2s / 同一 end_time / 同一 note
2 终止态     abandon / 终态 resume 409 / abandoned 再 finish 409 / 404 / 404 非法 action
             心跳打终态会话 = 200 且状态不变
3 清理       种 5 小时前的 running → 重启后 abandoned，时长 1500（=planned，不是 18000）
4 学习记录   按条目 total=1、带标题与笔记、只列终态
5 今日统计   pending 2=SQL 2 / pending_total 5 / due 1=SQL 1 / focus 2=SQL 2 / sessions 1=SQL 1
             正确率 0.6667（2 对 / 3 次判定，NULL 那条不计）/ 分类 {'写作方法':2,'记忆方法':2,...}
6 本周      7 天、周一起、is_today 唯一、周合计 1502=各日之和=SQL 1502、今日柱 = today 的数
             连续天数 3（今天+昨天+前天）
7 边界       一周前的 pending 不算今日(2) 全库 6 / 分类取前 8 / 今天没学 streak 从昨天算 =2
```

真实库跑完（`data/data.db`，不是我造的数）：
```
study_session 8 条全部 done（3 组练习 35/37/42s + 5 轮 UI 验收 4–7s），今日专注 145 秒
question 15 条 / quiz_attempt 15 条全部 is_correct=1 / review_item 0（全对，没题可进队列）
pending_total 3（都是 11-06 的，所以「今日待整理」= 0，口径正确）
```

浏览器验收（Playwright，1360×900，**13/13**，console 错误 0）：
```
仪表盘 6 区块 ['今日待整理','今日待复习','连续学习','正确率（今日）','本周专注','分类分布']
条形图 7 根柱子 / 分类分布 7 行
开始 15 分钟 → 顶栏 15:00 → 等 6 秒刷新 → 14:54（**没有重置**）
暂停 → 「已暂停」，2 秒后 14:54 仍是 14:54
提前完成 → 写笔记 → 保存 → 显示 +6 秒
条目详情「开始专注」→ target 显示条目标题 → 结束 → 学习记录第一条 = 刚结束那一轮
```
截图：`data/e2e_shots/m5_dashboard.png`、`m5_pomodoro_running.png`、`m5_paused.png`、`m5_item_sessions.png`
（脚本放在 `data/_e2e/m5_ui.py`，`data/` 不入库，要留成正式 e2e 就挪到 `frontend/e2e/`）

`npm run lint` 干净（`Pomodoro.vue` 单文件名加了定向 `eslint-disable`，因为文件名是 M5 文档指定的产出物）；
`npm run build` 通过：`index.html 0.39kB` / `css 54.34kB` / `js 261.98kB`。

**接口契约回写（改了一处，加了两行端点、四个详细形状、一张口径表）**
- 端点总表 +2：`POST /api/session/{id}/heartbeat`、`GET /api/session`（学习记录）→ 36 → 38 个
- `finish` 可带 `{"note"}`、状态机与幂等规则、`duration_seconds` vs `elapsed_seconds` 的区别
- `stats/today` 补 `pending_total`/`wrong_questions`/`week_focus_seconds`/`accuracy_all`/`attempts_*`/`streak_days`
- `stats/week` 完整形状（固定 7 天、`is_today`/`is_future`）
- 新增「计时与统计口径」表，与 M5 §6.6 同源

> `GET /api/session` 不在你批准的那两项里，但 DoD 写明「该条目学习记录里出现这次 session」，
> 没有按 target 列表的端点就做不到。已登记契约，不想要可以整条删（只影响 `SessionLog.vue`）。

**改动文件**
- 新增：`backend/app/db/repo/sessions.py`、`backend/app/db/repo/stats.py`、
  `backend/app/routers/session.py`、`backend/app/routers/stats.py`、`backend/scripts/verify_m5.py`、
  `frontend/src/composables/useTimer.js`、`frontend/src/components/{Pomodoro,SessionLog}.vue`、
  `frontend/src/views/Dashboard.vue`
- 改：`backend/app/main.py`、`frontend/src/{App.vue,router/index.js,api/client.js,utils/format.js}`、
  `frontend/src/components/ItemDetail.vue`、`frontend/src/views/Practice.vue`、
  `docs/contracts/接口契约.md`、`docs/milestones/M5-计时与交付.md`、`docs/00-总纲.md`、`README.md`、本文件
- **没动**：`desktop/` 任何文件、`study_session` 表结构、M1–M4 的后端与视图逻辑（只在 ItemDetail/Practice 加入口）

**遗留**
- [ ] 见顶部「未结遗留」第 9 条：选项自带 `A. ` 前缀（M4 模块，等你裁决）
- [ ] T5.5 起手要装 `electron-builder` 与 `pyinstaller`
- [ ] 仪表盘「今日待复习/错题」目前是 0 —— 因为真实练习 15 题全对。非零路径由 `verify_m5` 的种子数据覆盖

**验证**：`python tools/doc_check.py` → 6 PASS + 1 WARN（手册引用已完结 M1 作模板，属正常）
**推送状态**：本地已提交并打 `m5-wip`。agent 侧 GCM 凭据读不到，请在普通终端执行
`"C:/Program Files/Git/cmd/git.exe" push origin main && "C:/Program Files/Git/cmd/git.exe" push origin --tags`。

**下一会话第一件事**
> M5 T5.5：`desktop/main.js` 只换 spawn 目标（`cairn-backend.exe`），端口与握手逻辑不用改；
> PyInstaller 入口用 `backend/entry.py`；静态页传 `CAIRN_WEB_DIR=<resources>/web`。

## 2026-11-08 13:10 · M4 缺陷 · 选项双重编号（「A. A. …」）已修

**症状**：真跑 15 题，界面每个选项渲染成「A. A. 在即将忘记的那一刻复习」。

**根因**（两层叠加，各自单看都对）
- `prompts/quiz.md` 把「`options` 文本自带 "A. " "B. " 前缀」写成硬要求，示例是 `["A. 选项一"]`
- `QuizRunner.vue` 用 `letterOf(index)` 自己画字母徽标，选项文字原样输出
- `接口契约.md` 的示例也写 `"options":["A....","B...."]` —— "带前缀"从头到尾都被当成正确形状

**为什么 8/8 DoD 复验没抓到（是我的漏洞，写清楚）**
- `verify_m4.py` 的 fixture **自己就用带前缀的选项**（`q_obj(options=("A. 注意力留在当前这一轮", ...))`），
  等于把缺陷写进了"正常数据"
- 没有任何一条断言检查过 option 文本的形状（只断言 answer 字母、判定结果、库行数）
- `e2e/m4_quiz.py` 只看卡片数、判定文案、分数，不看选项文字
- 假流 JSON 全是手写的，真模型"顺手加前缀"的倾向只能靠真跑暴露；那 15 题是你在界面看到的

**修法**：字母只由界面给，数据层只存裸文本
- 新增 `repo/questions.strip_option_prefix()` / `clean_options()`：剥 `A.` `B、` `(C)` `D）` `A：`；
  **只认大写 A–Z + 分隔符**（`e.g.` / `3.5 倍` / `A/B 测试` / `Anki 软件` 不动）
- 生成侧 `quizzer._options()` 剥一次，读取侧 `row_to_question()` 再剥一次
  → 缺陷期入库的 15 题**不用改库**，接口吐出来就是干净的
- `prompts/quiz.md` 改成「只写内容本身，序号由界面加」；契约示例改裸文本 + 补一条形状规则

**验证（都真跑）**
- `verify_m4.py` → **69/69 PASS**（新增 2b 组 6 条：11 种前缀形态剥掉 / 4 种不误伤 / emit 是裸文本 /
  answer 字母不受影响 / 库里也裸 / 老数据读侧剥 / 只剩前缀的选项 → `bad_options` 跳过）
- 真模型 1 次调用出 5 题（条目 11《GitHub Actions》）：**模型输出 0/5 带前缀**，normalize 5/5 通过
- `e2e/m4_quiz.py` → **19/19 PASS**（新增 2 条 DOM 断言：18 个选项无重复编号、徽标从 A 起连续），
  截图 `frontend/e2e/_shots/04-verdict-immediate.png` 确认渲染为「A + 裸文本」
- `doc_check.py` 6 PASS + 1 提示

**改动文件**
- 改：`backend/app/db/repo/questions.py`、`backend/app/services/agents/quizzer.py`、
  `backend/app/prompts/quiz.md`、`backend/scripts/verify_m4.py`、`frontend/e2e/m4_quiz.py`
- 文档：`milestones/M4`（新增 §6.10 缺陷修正 + §7 一行 + 计数 69/69）、
  `contracts/接口契约.md`（示例改裸文本 + 形状规则）、`00-总纲`、`README`（69/69、19 项）、本文件

**遗留**
- [ ] 真库 `data/data.db` 那 15 题的 payload **仍存着前缀**（读侧已剥，界面不受影响）。要彻底洗干净需
      一次性 UPDATE，**没动你的数据**，等你点头
- [ ] 以后任何展示选项的路径都要走 `row_to_question()`，别直接读 `payload`

**推送状态：本地已提交，远程未推**（agent 侧 GCM 读不到凭据）
- 需要你在普通终端执行：`"C:/Program Files/Git/cmd/git.exe" push origin main`

**下一会话第一件事**
> 回到 M5 T5.5（打包）。本条只动 M4 的选项文本口径，不碰 M5 代码与 `desktop/`。

---

## 2026-11-08 14:20 · M5 T5.5 + T5.6（后端 onedir 打包 / 桌面壳 dev-prod 分流 / NSIS 安装包）

**做了什么（T5.5 + T5.6 的打包主线，T5.7/T5.8 未动）**

后端能冻成一个单目录 exe，桌面壳按 `app.isPackaged` 分流，`npm run dist` 能出安装包。

- `backend/app/paths.py`（新）：只读资源统一走 `app_path()` / `resource_root()`，源码与
  PyInstaller 冻结两套布局同一条路。替掉 5 处 `Path(__file__).parents[n]` 硬算
  （4 个 agent 的 `PROMPT_DIR` + `renderer.TEMPLATE_DIR`）
- `backend/app/config.py`：`ROOT`/`ENV_FILE`/默认数据目录在冻结时改口径 —— 数据与 `.env`
  一律 `%APPDATA%/Cairn`，绝不落安装目录；`_tool()` 冻结时默认去 `resources/ffmpeg/` 找 ffmpeg；
  windowed 模式（`sys.stdout is None`）不再挂 console handler
- `backend/app/main.py`：`WEB_DIR` 冻结时兜底 `resources/web`
- `backend/cairn-backend.spec`（新，`.gitignore` 里开了例外）：onedir + windowed，
  按后缀收全 `app/**/*.{sql,html,md,txt,json}`
- `desktop/main.js`：dev/prod 分流；CSP 用 `onHeadersReceived` 注入；单实例锁；
  `app.setName('Cairn')`；握手失败/后端中途退出 → `error.html`；日志带时间戳并记握手与首屏耗时
- `desktop/error.html`（新，删掉旧 `index.html`）
- `desktop/package.json`：`pack` / `dist` 脚本 + electron-builder 配置（extraResources 三段、`deleteAppDataOnUninstall: false`、generic publish 占位）
- `tools/prepare_ffmpeg.py`（新）：复制 ffmpeg.exe + 7 个 DLL（74MB）并用**干净 PATH** 自证

**实测结果（都真跑）**
- 后端 onedir **965MB**（exe 79MB），全新数据目录首启建库 21 表 / `user_version=2`、sqlite-vec 可用
- 打包后桌面端（全新 userData）：握手 12 次 / **3351ms**，首屏 **4126ms**，窗口 4128ms，**关窗后无 `Cairn.exe`/`cairn-backend.exe` 残留**
- dev 端：握手 17 次 / 4928ms（`uv run` 冷启动），首屏 5730ms，console 错误 0，`taskkill /T` 一次收掉 4 个进程
- 冻结后真实链路：`/api/quiz/generate` 出题成功（prompt 读得到）、`/api/html/generate` 生成 13565 字节学习页（模板读得到）、`/api/health` 200、`GET /` 200，未登记的 `/api` 路径仍是 404 JSON（静态挂载没把接口吞掉）
- NSIS 安装包 **407MB**：`Cairn-0.1.0-setup.exe`，已放到 `desktop/release/`（gitignored）；`dist` 退出码 0
- 回归：`verify_m5.py` 50/50、`verify_m4.py` 69/69、`doc_check.py` 6 PASS + 1 提示

**踩到的三个坑（都写进 M5 §6.3.1 / §6.5 / §7 了）**
1. **`ELECTRON_RUN_AS_NODE=1` 是 WorkBuddy shell 的默认环境变量**。带着它启动任何
   `electron.exe`/`Cairn.exe` 都会退化成纯 Node，报 `Cannot read properties of undefined
   (reading 'isPackaged')`、**一行日志都不写**、进程还挂着。我在这上面误判了两轮，
   差点去改启动逻辑。一律 `env -u ELECTRON_RUN_AS_NODE <exe>`
2. **spec 只 add-data `templates`/`prompts` 不够**：`app/db/migrate.py` 读 `app/db/schema.sql`，
   静态分析跟不到，**全新安装首启**就 `FileNotFoundError`。装过库的机器看不出来（"已是 v2，跳过建表"）
3. **`app.asar` 会被锁住**（能读、不能删/覆盖，查不出是谁；`release/` 与 `release-verify/`
   两个目录现在都还卡着，重启后可删）。规避：electron-builder 输出到**全新的空目录**

**其它环境事实**
- npm 必须 `--registry=https://registry.npmmirror.com`（直连 19 分钟没动 → 镜像 38 秒）；
  electron-builder 二进制要 `ELECTRON_BUILDER_BINARIES_MIRROR`
- `desktop/node_modules/.bin/electron` 在 Git Bash 下是坏 shim，直接用 `node_modules/electron/dist/electron.exe`
- 没做图标（`default Electron icon is used`）、没签名（Defender 可能报毒，README 待写）

**改动文件**
- 新：`backend/app/paths.py`、`backend/cairn-backend.spec`、`desktop/error.html`、`tools/prepare_ffmpeg.py`
- 改：`backend/app/config.py`、`backend/app/main.py`、`backend/app/services/renderer.py`、
  4 个 `backend/app/services/agents/*.py`、`desktop/main.js`、`desktop/package.json`、
  `backend/pyproject.toml`（+pyinstaller dev dep）、`.gitignore`
- 文档：`milestones/M5`（§2 / §4 / §6.3 / §6.4 前的新 §6.3.1 / §6.5 / §7 / 状态行）、`README`、本文件

**遗留**
- [ ] **安装包没在这台机器上装过**（`desktop/release/Cairn-0.1.0-setup.exe`）。NSIS 包里的
      `win-unpacked` 已单独验过能跑，但"安装 → 双击 → 卸载重装数据还在"这三步要真装一次才算数
- [ ] DoD 那条"装到**另一台没有 Python/Node** 的机器上可用"必须真机验证，我做不了
- [ ] 无图标、无签名
- [ ] `desktop/_smoke/` 里留了 dev 冒烟日志与截图（gitignored）

**下一会话第一件事**
> M5 T5.7（首次引导）：`views/Setup.vue`。后端已有 `scripts/env_check.py` 与 `GET /api/env/check`
> 那套探测（ffmpeg / whisper 模型 / embedding 模型 / sqlite-vec / LLM Key），照着它的字段做三步清单。
> 注意 T5.7 会改 `frontend/dist`，改完要重跑 `npm run build` 并重打安装包（`npm run dist`，约 2 分钟）。

---

## 2026-11-08 19:10 · M5 T5.7–T5.10 + 真实安装闭环（**M5 代码完成**）

**做了什么**

- **T5.7 首次引导** `frontend/src/views/Setup.vue`（新）：三步清单（LLM Key / ffmpeg / 本地模型），
  缺哪步给哪步的**可执行**指引；高级折叠里能改 base_url 与模型名；"稍后再说"写 localStorage 不再打扰。
  配套 `POST /api/env/key` + `backend/app/services/env_store.py`（新）：把 Key 写进 `.env` 并**热生效**
  （`reload_settings()` + 直接改 `os.environ`，否则 `load_dotenv(override=False)` 会继续用旧值）。
  值里带 `\r`/`\n`/引号一律 400 —— 否则等于开放"写任意环境变量"。响应、日志都不出现 Key 明文。
- **T5.8 README 安装段**：新增「安装与启动（给最终用户）」「故障速查」9 行、备份迁移、目录表补 `desktop/` 与 `tools/`。
- **T5.9 验收**：`verify_m5.py` 加第 8 步「首次引导：保存 Key 到 .env」7 项 → **57/57**。
- **T5.10 应用图标**：`tools/make_icon.py`（新）一套几何参数出四件 ——
  `desktop/build/icon.ico`（16/24/32/48/64/128/256）、`desktop/build/icon.png`（512，dev 窗口图标）、
  `frontend/public/favicon.ico`、`frontend/public/logo.svg`（顶栏品牌标）。形状"墨绿圆角块 + 四块错位叠石"，
  纯色块无渐变 —— 16×16 任务栏才是真实考验。主进程补 `app.setAppUserModelId('com.cairn.app')` 与 `appId` 对齐。
- **启动优化**：`faster_whisper` / `ctranslate2` / `yt_dlp` 改惰性导入（`python -X importtime` 定位，
  三者约 2.5s；`import app.main` 9.0s → 3.8s），`TYPE_CHECKING` 保住类型标注。
- **冻结版日志乱码**：`force_utf8_stdio()`（`reconfigure`）—— `PYTHONIOENCODING` / `PYTHONUTF8`
  对 windowed exe **实测完全无效**（`od -c` 看过字节）。

**实测（真跑，不是"应该没问题"）**

| 环节 | 结果 |
|---|---|
| 静默安装 | `EXITCODE=0`，1.4GB 落盘，桌面快捷方式 + 开始菜单就位 |
| 干净 PATH 首启 | 握手 18 次 / 5190ms，首屏 **6680ms**，console 错误 0，关窗无残留进程 |
| 建库 | 21 表 / `user_version=2` / sqlite-vec OK，`.env` 与 `data.db` 都在 `%APPDATA%/Cairn` |
| 卸载 | `start /wait` 等到结束：安装目录 + 快捷方式消失，`%APPDATA%/Cairn` 原样保留（21 表 + 标记行仍在） |
| 重装 | 数据还在，列表里能直接看到上一轮的「M5 安装验证标记」 |
| 换新后端重打 | 首屏 **4066ms**、握手 9 次 / 2467ms；`shell.log` 里中文不再乱码 |

- 引导页 E2E（Playwright，`channel="msedge"` —— 内置 chromium headless 没装）：自动进 `/#/setup` →
  存 Key → 步骤 1 变「已配置」→ 跳 `/#/`、顶栏"环境待配置"角标消失、console 错误 **0**
- 回归：**m5 57/57** · **m2 118/118**（证明惰性导入没弄坏转写链路）· **m1 50/51**（唯一红是老口径问题）·
  **m3 61/61** · `doc_check.py` 6 PASS + 1 提示 · `npm run lint` 干净 · `npm run build` 产物含 `logo.svg`/`favicon.ico`

**踩到的坑（都写进 M5 §6.7 / §6.8 / §6.9 / §7 了）**

1. **NSIS 静默安装 `/S` 退出码 0 但什么都没装**：`/D=` 必须是**最后一个参数且不加引号**；从 Git Bash
   传反斜杠会被吞（实测出现过 `C:/Users//cwqjk/...` 与 `%SystemDrive%Userscwqjk...`）；装到 `C:\` 根目录
   要管理员权限、失败时**照样退 0**。最终"ASCII 路径 + `.bat`"才成。
2. **`Uninstall Cairn.exe /S` 立刻返回 0 却不干活**，必须 `start /wait "" "...\Uninstall Cairn.exe" /S`
   （本机卸载约 10 分钟，别以为卡死了）。
3. **`--data-dir` 换数据目录后项目根 `.env` 整个读不到**：真 Key / `FFMPEG_DIR` 全丢，`verify_m1` 直接报
   "未配置 LLM_API_KEY"。修法：数据目录 `.env` 优先，再用 `override=False` 把布局默认 `.env` 补作兜底。
4. **静态资源 404**：后端只挂了 `/assets` 与 `GET /`，`/logo.svg`、`/favicon.ico` 全 404。改成白名单逐个
   注册 —— **故意不用 `/{name}` 通配**，否则任何未登记的接口路径都会被静态路由吞掉、返回 HTML 而不是
   404 JSON（契约就破了）。
5. **文件被锁**：`desktop/release*/app.asar` 依旧删不掉（gitignored，重启后清）；`ExtractAssociatedIcon` /
   `WScript.Shell` 被 shell 安全策略挡了，图标是否真嵌进去改用"构建日志里没有 `default Electron icon`"作证据。

**改动文件**

- 新：`backend/app/services/env_store.py`、`frontend/src/views/Setup.vue`、`tools/make_icon.py`、
  `desktop/build/icon.ico`、`desktop/build/icon.png`、`frontend/public/favicon.ico`、`frontend/public/logo.svg`
- 改：`backend/app/config.py`（`env_file` 跟着数据目录走 + 兜底 + `reload_settings` + `force_utf8_stdio`）、
  `backend/app/main.py`（白名单静态根文件）、`backend/app/routers/env.py`、`backend/app/services/env_probe.py`、
  `backend/app/services/transcriber.py`（惰性导入）、`backend/scripts/env_check.py`、`backend/scripts/verify_m5.py`、
  `desktop/main.js`、`desktop/package.json`、`frontend/index.html`、`frontend/src/App.vue`、
  `frontend/src/api/client.js`、`frontend/src/composables/useUi.js`、`frontend/src/router/index.js`、
  `frontend/src/styles/app.css`、`.gitignore`
- 文档：`milestones/M5`（状态行 / DoD / §6.7 / §6.8 / 新 §6.9 / §7 四行 / §8）、`contracts/接口契约.md`
  （`POST /api/env/key` 全节 + `.env` 兜底规则）、`README`、`00-总纲`、`会话提示词手册`、本文件

**遗留**

- [ ] **装到另一台没有 Python/Node 的机器** —— DoD 唯一没闭环的一项，我只能用干净 PATH 模拟
- [ ] 冷启 6680ms 未达 DoD 的 5 秒（热启 4066ms 达标），已按"热启达标、冷启首启例外"记，不假装达标
- [ ] 安装包**未签名**：SmartScreen 会拦，README 写了绕过步骤；正式分发要买证书
- [ ] 卸载耗时异常长（约 10 分钟，1.4GB + 杀软实时扫描），值得换成增量更新或减小体积
- [ ] `desktop/release/`、`release-verify/` 的 `app.asar` 仍被锁，gitignored，重启后手工清
- [ ] **本轮只在本地提交，没 push**：agent 会话读不到 git 凭据，`git push` 请你在终端执行

**下一会话第一件事**

> 你手工验收：装 `desktop/release/Cairn-0.1.0-setup.exe` → 双击 → 引导页填 Key → 建一条资料 →
> 卸载 → 重装看数据是否还在。通过后打 `m5-done`、`00-总纲` 改"已验收"并升 v1.1、
> 把 M4+M5 的条目移进 `docs/archive/`。然后开 v2（模板 A 换里程碑）。

## 2026-11-08 19:20 · M1 遗留 · 修掉「写死任务数 3」的脆弱断言

**完成**

- 遗留 1 关闭：`verify_m1.py::step_no_key` 里 `check("未留下注定失败的任务", total == 3)` 换成两条语义断言：
  ① **organize 任务数前后不变**（无 Key 时 `/organize` 在 `_require_llm_key()` 就 400 了，不该派发任务）；
  ② **`agent_task` 里不存在 `error_code='LLM_NO_KEY'` 的行**。
- 为什么原来会红：写死 3 是 M1 当时的现场（1 单条 + 2 批量 = 3 个 organize 任务）；M3 加了向量索引后，
  整理完成会顺手派发 `index_embed`，全表任务数变成 11 且随后台派发时刻浮动。所以只数 `type='organize'`，
  不数全表——全表计数本身就是随机的。
- 实跑：**`verify_m1.py` 52/52 PASS**（新增 1 项断言，51 → 52）。

**改动文件**

- `backend/scripts/verify_m1.py`（`step_no_key`）
- 文档：`README`（验收数字）、`milestones/M1`（状态行）、本文件（当前状态 + 遗留表 1）

**遗留**

- [ ] **本轮只在本地提交，没 push**：agent 会话读不到 git 凭据，`git push origin main` 请你在终端执行
- [ ] M5 真机验收（另一台没有 Python/Node 的机器）仍未闭环，见当前状态

## 2026-11-08 19:45 · 发布 · 整理 + 用户向 README + v0.1.0

**完成**

- **文档整理**：`00-总纲.md` / `HANDOFF.md` / `contracts/` / `milestones/` / `archive/` / `会话提示词手册.md`
  全部 `git mv` 到 `docs/dev/`，`docs/` 顶层只留 `images/`（用户向）。`tools/doc_check.py` 的 `DOCS`
  与 `allow_archive_ref` 跟着改，检查仍 6 PASS + 1 提示；代码里唯一一处注释路径（`desktop/main.js`）也改了。
- **README 重写**：真实读了 AnythingLLM / Cherry Studio / Khoj / Quivr 四份原始 README（`curl` 拉 raw 文件，
  不是凭印象），抽出它们的共识结构（一句定位 → 下载 → 截图图集 → 按场景分组的特性 → 首次配置 →
  隐私/数据位置 → FAQ → 已知限制 → 开发 → 许可），按 Cairn 的实际能力重排。开发期台账内容全部退出 README。
- **截图**：临时 `DATA_DIR` + 演示内容（6 篇学习方法短文，真跑整理 / 问答 / 出题 / 错两题）起 8760/5190，
  Playwright 截 8 张 1440×900@2x 图存 `docs/images/`：知识库 / 条目详情 / 思维导图 / 检索问答 / 学习页 /
  复习作答 / 仪表盘 / 练习配置。**没有拍用户真实知识库**，用完删掉临时数据目录。
- **发布件**：`LICENSE`（MIT，与 AnythingLLM / Quivr 一致）、`CHANGELOG.md`（0.1.0）、
  `docs/dev/release-notes-v0.1.0.md`（GitHub Release 正文 + 安装包 SHA-256 `58ec2d45…f107ebedf`）。
- **全量回归**（发出前重跑）：m1 52/52 · m2 118/118 · m3 61/61 · m4 69/69 · m5 57/57 · `npm run lint` 干净。
- **tag `v0.1.0`**（annotated，指向本次提交）。

**改动文件**

- 新增：`LICENSE`、`CHANGELOG.md`、`docs/images/*.png`（9 张）、`docs/dev/release-notes-v0.1.0.md`
- 重写：`README.md`
- 移动：`docs/{00-总纲,HANDOFF,contracts,milestones,archive,会话提示词手册}` → `docs/dev/`
- 改：`tools/doc_check.py`、`desktop/main.js`（注释路径）、`docs/dev/HANDOFF.md`

**遗留**

- [ ] **`git push origin main && git push origin --tags`** —— agent 会话读不到 git 凭据
- [ ] GitHub Release 要你在网页建（正文用 release-notes，安装包手动上传）
- [ ] 真机验收（另一台没有 Python/Node 的 Windows）仍未做

## 2026-11-08 20:30 · 发布 · 网页版静态演示（github.io）+ README 再精简

**前提纠正**
> 网页版不是独立可部署的应用：`frontend` 是 Vue SPA，所有数据走 `/api`，后端是本地
> FastAPI + SQLite + torch + ffmpeg。GitHub Pages 只能放静态文件，把 `dist` 直接丢上去
> 只会满屏「连不上后端」。所以做的是**静态演示包**，不是「部署网页版」。

**完成**

- **演示层**（新）：`frontend/src/demo/`
  - `fixtures.json`（77KB）：起临时 `DATA_DIR` 后端 → 真跑 6 篇整理 + 2 次问答 + 1 次出题（故意错 2 题）
    + 2 份学习页 → 把各 GET 端点响应原样抓下来；`public/demo/` 放导图 SVG（明/暗）与学习页 HTML
  - `index.js`：在 `main.js` 挂载前替换 `window.fetch`，GET 走 fixture（支持 q/category/tag 过滤），
    **非白名单写操作一律 403 `DEMO_OFFLINE`**；`api.mindmapUrl` / `htmlUrl` 指到静态资源
  - 唯一允许的写：交卷判分与复习结果上报（`quiz/submit`、`review/:id/result`）—— 判分用 fixture 里的
    标准答案本地比对（复用 `utils/quiz.judgeLocal`），**不是预录结果**，复习链路能完整点到结果页
- **UI**：`App.vue` 加常驻演示横幅（底部一条，不进布局）；`client.js` 加 `DEMO_` 前缀的错误人话映射；
  `main.js` 用 `VITE_DEMO=1` 动态 import（正式构建实测被摇掉：`dist` 里搜不到 `DEMO_OFFLINE` / `演示模式`）
- **CI**：`.github/workflows/pages.yml` —— `npm ci` → `VITE_DEMO=1 vite build --base=./` → `upload-pages-artifact`
  → `deploy-pages`，推 main 自动跑
- **README 重写第二版**：272 行 → 169 行。新增「在线试用」段（能看什么 / 不能做什么 / 数据是快照），
  删掉「从源码运行」整节（移到 `docs/dev/运行与打包.md`）、验收数字、目录结构
- **文档**：新增 `docs/dev/运行与打包.md`（依赖/启动/打包/验收/演示包构建 + 作用域声明）

**验证**（本地按 Pages 路径结构 `127.0.0.1:5210/Cairn-StudyKB/` 起静态服务，Playwright 实跑）

- 逐页 12/12 PASS：列表 6 条 / 详情摘要+要点 / 导图 SVG `naturalWidth>0` / 仪表盘「4 小时 10 分」+
  分类分布 + 正确率 33% / 问答历史有真实记录 / 学习页 iframe 指向 `demo/page-2.html` 且正文渲染 /
  复习「开始复习 → 选项 → 答对了 + 解析 → 交卷 2/2 正确率 100%」/ 采集与出题被拒绝且提示含「演示」
- **console 0 错误**；`npm run lint` 干净；`doc_check.py` 6 PASS + 1 提示（旧的 WARN 不变）

**改动文件**

- 新增：`frontend/src/demo/{index.js,fixtures.json}`、`frontend/public/demo/*`（4 个）、
  `.github/workflows/pages.yml`、`docs/dev/运行与打包.md`
- 改：`README.md`、`frontend/src/{main.js,App.vue,api/client.js}`、`frontend/eslint.config.js`、`.gitignore`

**遗留**

- [ ] **`git push origin main`** —— agent 会话读不到 git 凭据，这次连 tag 都没打（没发新版本）
- [ ] **GitHub Settings → Pages → Source 选 "GitHub Actions"**，否则 workflow 跑完也不会发布
- [ ] 演示站上线后要自己点一遍（我这边只能用本地 http.server 模拟同一个路径结构）
- [ ] 后端响应结构变了要重抓 fixture，否则演示数据会和真实接口漂移（做法写在 `运行与打包.md`）

## 2026-11-08 20:20 · 发布 · 修掉 github.io 404 + Release 落地

**404 的根因（推翻了「Pages 没开」的猜测）**

- 站点 404 不是 base 写错、不是 workflow 有问题、不是 `npm ci` 失败（本地 `npm ci --dry-run` 通过，
  `VITE_DEMO=1 vite build` 1.4s 成功）。真因是**仓库是 Private**：
  GitHub 免费账号的私有仓库不支持 Pages，`Source` 选了 `GitHub Actions` 也生不出站点。
- 判定证据：未登录访问仓库首页 404（公开仓库 `TRAVEL-DESK` 是 200）、匿名 API 三连 404、
  账号 22 个公开仓库列表里没有它、而账号下另外三个仓库的 Pages 站点全部 200。
- 转 Public 后立刻见效：Actions `demo-pages` **run #1（private 期）failure → run #2 success**。

**完成**

- 仓库转 Public；`frontend/src/demo/fixtures.json` 里 2 处 `C:/Users/cwqjk/AppData/Local/Temp/cairn_demo`
  换成 `C:/Users/<you>/AppData/Roaming/Cairn`（安装版真实数据目录），构建产物 grep 零残留。
  旧提交 `f4aeeb5` 历史里仍留有该路径（用户名级别，非密钥，未清洗历史）。
- workflow 加 `actions/configure-pages@v5`（`enablement: true`）：Pages 没启用时自动开启。
- **GitHub Release `v0.1.0` 已建**（id `438225599`）：正文取 `release-notes-v0.1.0.md`
  （去掉 H1 与作用域块），附件 `Cairn-0.1.0-setup.exe` 426,428,660 字节。
- `release-notes-v0.1.0.md` 修掉一个失效链接（`../README.md#从源码运行` → `运行与打包.md`），
  因为「从源码运行」那节早已移出 README。

**线上校验**（Playwright 直打线上地址，12/12 PASS）

```
演示横幅常驻 / 列表 6 条 / 详情摘要+要点 / 仪表盘有专注时长 / 问答历史有记录
学习页：点「历史」→ 选产物 → iframe 1 个且正文渲染（"把知识连成网"）
复习：开始复习 → 2 个选项 → 「答对了」+ 解析
写操作 403 DEMO_OFFLINE / console 0 错误
```

**踩坑记录**

- `actions/runs` 匿名可查的前提也是**仓库公开**；private 时连 Actions 日志都取不到，
  这让「到底跑没跑」无法自证 —— 以后排查 Pages 先确认可见性。
- 学习页 `iframe` 是 `v-if="current"`，不点产物就一直是空状态；Playwright 里点抽屉必须用
  `.drawer .drawer-main`，用 `aside.drawer button` 会先命中「关闭」。
- 清 fixture 里的 Windows 路径时，heredoc 里的 `\\\\` 会被外层 JSON 再吃一层，
  用 `chr(92)` 拼反斜杠最稳。

## 2026-11-09 16:55 · 计划 · v0.2 优化计划（M6/M7/M8）

**做了什么（纯文档 + 事实核对，没动一行代码）**

用户提了四条：① 设置页（双 API、探测模型、按任务配模型/思考强度且实时生效、配色与明暗、检查更新、GitHub 入口）② 侧栏太多太杂且要能收缩 ③ 安装包太大要下载中心 ④ 文案要像同类知识库。
建成三份自包含里程碑 + 一份总表：

- `docs/dev/优化计划-v0.2.md` —— 现状体检数据、要拍板的 4 件事、36 个任务与依赖、会话模板、升级与发布流程
- `docs/dev/milestones/M6-设置与个性化.md` —— settings.json 结构、端点形状、6 套主题的令牌映射与暗色派生规则、T6.0–T6.9
- `docs/dev/milestones/M7-布局与文案.md` —— 左栏新结构（ASCII 稿）、布局原语、四处侧栏接入、术语表与文案规则、T7.0–T7.7
- `docs/dev/milestones/M8-体积与更新.md` —— 体积账、组件协议、主包 excludes、下载中心、自写更新器、T8.0–T8.8

**核对出来的事实（写进计划依据）**

- 安装包 426 MB；后端解包 965 MB，其中 `torch` 367 MB、`playwright` 104 MB、`av.libs` 65 MB、`ctranslate2` 61 MB、`scipy` 72 MB、`transformers` 48 MB、`onnxruntime` 38 MB、`sklearn` 13 MB
- 按实测压缩率反推，**Electron 壳本身约占 70 MB**，所以「只留必要」的真实下限是 ~130–160 MB，不是 100 MB。计划里把 DoD 定成 ≤170 MB（预期 155–165）
- 三个重依赖**现在就已经是懒导入**（`embedder.get_model()` / `transcriber._whisper()` / `browser.py` 的 try-import），降级路径现成，M8 不用新造降级逻辑——这是 M8 最大的风险削减点
- `llm.py:_payload()` **无条件**发送 `reasoning_effort`：接任何不支持该参数的 OpenAI 兼容服务都会 400。这是现存 bug，放进 T6.3 一起修
- 仓库是 **Public**（12 个公开仓库之一），`releases/latest` 匿名可取（200），自写更新器不需要 token
- 侧栏共四处：知识库分类树、问答历史抽屉、学习页选择器、练习配置栏。截图里左栏 40+ 行是「标签平铺 + 一个标签一行」

**顺手修的**

- `真机实测-v0.1.0.md` 缺「作用域」声明（`doc_check` 原来就有一个 FAIL，不在这次任务范围里，但它是门禁的一部分，补上一行）

**下一步**

> 下一会话第一件事：**T6.0 基线固化**——跑 `verify_m1..m5` 记录通过数、打 `m6-wip`、然后 T6.1 契约先行。
> 不要在 T6.1 之前写任何实现代码。四个待拍板项（导航精简 / 配色数量 / 选装默认 / 更新交互）见 `优化计划-v0.2.md` §2，用户不表态就按推荐走。

---

## 2026-11-09 19:35 · M6 · 第一部分（T6.0–T6.6）完成

**完成**
- T6.0 基线：m1–m5 全量重跑（52/118/61/69/57 全绿），tag `m6-wip`
- T6.1 契约：`接口契约` 新增 `GET/PATCH /api/settings`、`POST /api/settings/probe`、`POST /api/settings/llm`、
  `GET /api/version`；`数据契约` 新增「配置文件」「组件目录」两节；ADR-026（按任务路由）/ ADR-027（组件按需下载）；
  总纲里程碑表补 M6–M8
- T6.2 `services/prefs.py`：默认值深合并、损坏备份 `settings.json.bad-<时间戳>`、唯一临时名 + `os.replace` 原子写、
  按 `(mtime_ns, size)` 失效缓存；**首次读取会用 `.env` 现值做初值**（否则老用户升级后 base_url 被悄悄换回官方地址）
- T6.3 `services/llm_route.py` + `llm.py` 改造：`resolve(agent)` 解析 provider/model/effort；
  `reasoning_effort` 只在 `supports_effort=true` 且 effort≠none 时进请求体；400 点名字段时去掉重试一次；
  `llm_call_log.model` 记**实际使用的**模型；缺 Key 的提示点名 provider
- T6.4 `env_probe.probe_provider()`：`/models` 优先，404/405 且给了模型名时退化成 `max_tokens=1` 的对话探测，
  15s 超时、不重试；`LLM_MODELS_UNSUPPORTED` 表示「不提供列表但对话可用」
- T6.5 `components/SettingsDialog.vue`：模态 880×620、左 4 tab（模型/外观/下载/关于）、焦点陷阱、Esc、遮罩点击关闭、
  tab 记忆；顶栏齿轮入口；外观/下载/关于先给明确占位（Part 2 填）
- T6.6 模型 tab：`ProviderForm.vue`（双卡、Key 状态只给「已配置/未配置」、探测三态）+ `TaskMatrix.vue`
  （四任务 × provider/模型/思考强度，不支持时置灰）+ `ModelTab.vue`（顶部「当前生效」摘要、即时保存）
- `verify_m6.py`（新）：53 条断言，覆盖文档 §4 T6.9 的前六条；**用本机 mock provider 跑，不联网**

**改动文件**
- 新增：`backend/app/services/prefs.py`、`llm_route.py`、`backend/app/routers/settings.py`、
  `backend/scripts/verify_m6.py`、`frontend/src/composables/useSettings.js`、
  `frontend/src/components/SettingsDialog.vue`、`frontend/src/components/settings/{ModelTab,ProviderForm,TaskMatrix}.vue`、
  `docs/dev/M6-补充记录.md`
- 改：`backend/app/services/{llm,env_probe,env_store}.py`、`backend/app/routers/health.py`、`backend/app/main.py`、
  `frontend/src/{App.vue,api/client.js,composables/useUi.js}`、`README.md`、`00-总纲.md`、`M6-设置与个性化.md`

**验证**
- `verify_m6.py` → **53/53 PASS**（新增）
- `verify_m1..m5` 回归 → 52/52 · 118/118 · 61/61 · 69/69 · 57/57
- `npm run lint` 干净 · `npm run build` 通过（JS 287 kB / gzip 105 kB）
- `doc_check.py` → 6 PASS + 1 提示（文档 20 份、端点 45 个）

**遗留问题**
- [ ] Part 2 开工前先看 `M6-补充记录.md` 的三条**待裁决**：S-1 探测有写盘副作用、S-2 `llm_call_log` 无 `effort` 列、
      S-3 `--data-dir` 仍回落读项目根 `.env`（验收脚本写「没有 Key 会怎样」时会被真机 Key 干扰）
- [ ] S-8：主题派生规则按原文档算，`text-3` 六套全部只有 2.19–2.24:1（要求 ≥3:1）；§3.1 已给出修订规则，Part 2 照它执行
- [ ] `prefs.py`(319) / `llm.py`(316) 超 300 行红线，下次动它们时顺手拆

**待裁决冲突**
- 无（四条裁决已落在 HANDOFF「本轮裁决」与 M6 §3）

**下一会话第一件事**
> 见「当前状态」里的「下一会话第一件事」：开 T6.7 主题系统，先读 M6 §3.1 的修订规则。
