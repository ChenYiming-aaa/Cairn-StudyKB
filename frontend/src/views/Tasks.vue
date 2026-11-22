<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage } from '../api/client'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'
import { shortTime } from '../utils/format'

/**
 * 任务中心（T2.9）：最近 50 条任务，失败可重试。
 *
 * 2026-11-17 改版：从「按任务类型平铺」改成「按我做的事归组」（见 `INTENT_OF`）。
 * 一个采集 = 抓正文 + 补索引两步，原来占两行、两个类型名，用户要自己拼起来。
 *
 * 刷新策略：有 queued/running 时每 2 秒轻量轮询（列表接口本身只查 50 行，代价很小）；
 * 全部落定就停，不留后台定时器。
 *
 * 「完成」不是终点：任务跑完用户最想知道的是**刚才那条内容在哪**。接口一直带
 * `output_json.item_id`（采集/转录/整理/补索引都有），这里直接给一个「去看这条」，
 * 不然用户要自己回忆标题、回知识库翻列表。
 */
const toast = useToast()
const router = useRouter()
const { openItem, openPaste, openSettings } = useUi()

const tasks = ref([])
const total = ref(0)
const loading = ref(false)
const errorText = ref('')
const retrying = ref('')

const TYPE_TEXT = {
  fetch_url: '网页采集',
  transcribe_video: '视频转录',
  organize: '整理',
  index_embed: '建立搜索索引',
  // 6-4：组件安装也走任务队列，没有这一项时任务中心直接露出 `component_install`
  component_install: '安装组件',
}

const STAGE_TEXT = {
  fetching: '抓取正文',
  saving: '写入知识库',
  metadata: '读取信息',
  downloading: '下载音频',
  transcribing: '语音识别',
}

const STATUS = {
  queued: ['排队中', 'badge-pending'],
  running: ['进行中', 'badge-organizing'],
  done: ['完成', 'badge-ready'],
  failed: ['失败', 'badge-failed'],
}

let timer = null

const hasActive = computed(() =>
  tasks.value.some((t) => t.status === 'queued' || t.status === 'running')
)

/**
 * 按「我做的事」归组（2026-11-17）。
 *
 * 原来是把 6 种任务类型按时间平铺，用户为了确认「我刚贴的链接好了没」，
 * 得先读懂「网页采集」和「建立搜索索引」的区别；而单人本地库同时通常只有 1 条在跑，
 * 50 条平铺是给机器状态看的。
 *
 * 用户的问题永远是「我刚才那件事成了没」，所以：
 * - `index_embed` 并进「收内容」——它是采集的一步，不是另一件事；
 * - 同一条内容的同类工作归一行（抓取 + 补索引 + 重读）；
 * - 内部阶段（抓取正文 / 写入知识库 / 语音识别）收进展开里，需要排查才看。
 */
const INTENT_OF = {
  fetch_url: 'collect',
  transcribe_video: 'collect',
  ocr_pages: 'collect',
  extract_text: 'collect',
  index_embed: 'collect',
  organize: 'organize',
  component_install: 'install',
}
const INTENT_TEXT = { collect: '收内容', organize: '整理内容', install: '安装组件', other: '其他' }
// 曾经每种任务还带一句解释（「让模型写标题、摘要和笔记」），单条一组时贴在行下面：
// 一屏七行「整理内容」就有七句同样的解释，而做的事点「N 步」就能展开看。2026-11-22 删。
const STATUS_RANK = { failed: 3, running: 2, queued: 1, done: 0 }

/** 一行代表的一件事：状态取最「卡住」的那个，进度取正在跑的那个 */
function foldGroup(intent, itemId, list) {
  const status = list.reduce(
    (worst, task) => (STATUS_RANK[task.status] > STATUS_RANK[worst] ? task.status : worst),
    'done',
  )
  const active = list.find((task) => task.status === 'running')
  const failed = list.find((task) => task.status === 'failed')
  return {
    key: `${intent}:${itemId ?? list[0].id}`,
    intent,
    label: INTENT_TEXT[intent] || INTENT_TEXT.other,
    itemId,
    status,
    progress: status === 'done' ? 100 : (active?.progress ?? 0),
    failed,
    latest: list[0],
    count: list.length,
    tasks: list,
  }
}

const groups = computed(() => {
  const map = new Map()
  tasks.value.forEach((task, index) => {
    const intent = INTENT_OF[task.type] || 'other'
    const itemId = itemIdOf(task)
    // 还没有 item_id（抓取刚排队、内容尚未落库）时各自成组，避免把两件事并成一件
    const key = itemId ? `${intent}:${itemId}` : `${intent}:task-${task.id}`
    if (!map.has(key)) map.set(key, { intent, itemId, list: [], order: index })
    map.get(key).list.push(task)
  })
  // 顺序沿用接口给的「新 → 旧」：组取它里面最新那条任务的位置
  return [...map.values()]
    .sort((a, b) => a.order - b.order)
    .map(({ intent, itemId, list }) => foldGroup(intent, itemId, list))
})

/** 展开态按组 key 存：默认收起，只有想排查的人才需要看内部阶段 */
const opened = ref({})
function toggleGroup(key) {
  opened.value = { ...opened.value, [key]: !opened.value[key] }
}

function typeText(type) {
  return TYPE_TEXT[type] || type
}

function statusView(status) {
  return STATUS[status] || [status || '未知', 'badge-soft']
}

function cleanError(msg) {
  return String(msg || '').replace(/^[A-Za-z]+(Error|Exception):\s*/, '')
}

/** 失败之后**真正能解决它**的那一步。没配上的码仍然只给「重试」。 */
const FAILURE_FIX = {
  FETCH_LOGIN_REQUIRED: {
    label: '去登录', go: 'login',
    hint: '这条要站点登录才读得到',
  },
  FETCH_BLOCKED: {
    label: '去登录', go: 'login',
    hint: '站点拦下了，多半要登录',
  },
  COMPONENT_MISSING: {
    label: '去装组件', go: 'downloads',
    hint: '缺「文字识别」组件',
  },
  OCR_MISSING: {
    label: '去装组件', go: 'downloads',
    hint: '缺「文字识别」组件',
  },
  LLM_NO_KEY: {
    label: '去配模型', go: 'model',
    hint: '还没配模型 Key',
  },
}

function fixOf(task) {
  return task.status === 'failed' ? FAILURE_FIX[task.error_code] || null : null
}

/** 「去登录」把采集面板打开（登录区就在里面）；另外两个直接开到对应设置页 */
function applyFix(task) {
  const fix = fixOf(task)
  if (!fix) return
  if (fix.go === 'login') openPaste()
  else openSettings(fix.go)
}

/** 成功的任务带 `item_id`（采集 / 转录 / 整理 / 补索引都有）：顺手把用户送到那条内容 */
function itemIdOf(task) {
  const out = task.output_json || {}
  const id = out.item_id || out.existing_item_id
  return id ? Number(id) : null
}

function openTaskItem(task) {
  const id = itemIdOf(task)
  if (!id) return
  openItem(id)
  router.push('/')
}

async function load() {
  loading.value = tasks.value.length === 0
  errorText.value = ''
  try {
    const data = await api.listTasks({ limit: 50 })
    tasks.value = data.items || []
    total.value = data.total || 0
    schedule()
  } catch (err) {
    errorText.value = friendlyMessage(err)
  } finally {
    loading.value = false
  }
}

function schedule() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (!hasActive.value) return
  timer = setTimeout(() => {
    timer = null
    load()
  }, 2000)
}

async function retry(task) {
  retrying.value = task.id
  try {
    await api.retryTask(task.id)
    toast.ok('已重新开始，进度会在这里更新')
    await load()
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    retrying.value = ''
  }
}

onMounted(load)
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
  timer = null
})
</script>

<template>
  <div class="tasks">
    <header class="tasks-head">
      <div class="head-text">
        <h1 class="page-title">任务中心</h1>
        <p class="page-sub">按事归组 · 最近 50 条 · 共 {{ total }}</p>
      </div>
      <div class="grow" />
      <button class="btn btn-sm" type="button" :disabled="loading" @click="load">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </header>

    <p v-if="errorText" class="error">{{ errorText }}</p>

    <p v-if="loading" class="empty">加载中…</p>
    <div v-else-if="!tasks.length" class="empty">
      <p>还没有任务。采一条内容，这里就有记录了。</p>
      <button class="btn btn-sm" type="button" @click="openPaste()">＋ 采集内容</button>
    </div>

    <ul v-else class="rows">
      <li v-for="group in groups" :key="group.key" class="row">
        <div class="row-main">
          <span class="badge" :class="statusView(group.status)[1]">
            {{ statusView(group.status)[0] }}
          </span>
          <span class="type">{{ group.label }}</span>
          <button
            v-if="group.count > 1"
            class="steps"
            type="button"
            :aria-expanded="Boolean(opened[group.key])"
            @click="toggleGroup(group.key)"
          >{{ group.count }} 步</button>
          <span class="pct">{{ group.progress }}%</span>
          <div class="grow" />
          <button
            v-if="group.status === 'done' && group.itemId"
            class="btn btn-sm"
            type="button"
            @click="openTaskItem(group.latest)"
          >去看这条</button>
          <span class="time">{{ shortTime(group.latest.created_at) }}</span>
        </div>

        <div v-if="group.status === 'running' || group.status === 'queued'" class="progress-bar">
          <i :style="{ '--p': group.progress / 100 }" />
        </div>

        <!-- 失败信息只给组里第一条失败的：同一个错误连报几行只会让人以为坏了更多东西 -->
        <div v-if="group.failed" class="row-error">
          <!-- 错误码挂在 title 上而不是摆成文字：它是给报问题用的内部标识
               （`LLM_HTTP_ERROR` 这种），摆在句尾既帮不上忙，也违反文案规范
               「界面不出现 LLM 字样」。要排查时鼠标停一下就能看到。 -->
          <span
            class="err-text"
            :title="group.failed.error_code ? `错误码 ${group.failed.error_code}` : null"
          >{{ cleanError(group.failed.error_msg) }}</span>
          <button
            v-if="fixOf(group.failed)"
            class="btn btn-sm"
            type="button"
            @click="applyFix(group.failed)"
          >{{ fixOf(group.failed).label }}</button>
          <button
            v-else
            class="btn btn-sm"
            type="button"
            :disabled="retrying === group.failed.id"
            @click="retry(group.failed)"
          >
            {{ retrying === group.failed.id ? '重新排队…' : '重试' }}
          </button>
        </div>
        <p v-if="group.failed && fixOf(group.failed)" class="row-hint">{{ fixOf(group.failed).hint }}</p>

        <!-- 内部阶段：点「N 步」才展开。常态下这一行不占屏 -->
        <ul v-if="opened[group.key]" class="sub-rows">
          <li v-for="task in group.tasks" :key="task.id" class="sub-row">
            <span class="badge badge-soft">{{ statusView(task.status)[0] }}</span>
            <span class="type">{{ typeText(task.type) }}</span>
            <span v-if="task.stage" class="stage">{{ STAGE_TEXT[task.stage] || task.stage }}</span>
            <span class="pct">{{ task.progress }}%</span>
            <div class="grow" />
            <button
              v-if="task.status === 'failed'"
              class="btn btn-sm"
              type="button"
              :disabled="retrying === task.id"
              @click="retry(task)"
            >{{ retrying === task.id ? '重新排队…' : '重试' }}</button>
            <span class="time">{{ shortTime(task.created_at) }}</span>
          </li>
        </ul>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.tasks {
  flex: 1;
  min-height: 0;
  overflow: auto;
  /* 与其余几页同一套页面内边距：标题落在 y=68（原本 24px 全向 → 68+8），
     换页时标题会跳 8px */
  padding: var(--space-4) var(--space-6) var(--space-8);
}

/* 标题与副题竖排、与其余七页同一套（page-title / page-sub 在 app.css）。
   原先这里是把 h2（fs-lg）+ 一行小字按 baseline 横排在同一行 ——
   同是「页面第一眼」，别的页是 20px 标题压 13px 副题，这里读起来像一条列表的工具条。 */
.tasks-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.head-text {
  min-width: 0;
}

.grow {
  flex: 1;
}

.empty {
  color: var(--c-text-3);
  font-size: var(--fs-sm);
}

.empty p {
  margin-bottom: var(--space-2);
}

.error {
  color: var(--c-danger-ink);
  font-size: var(--fs-sm);
}

.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  overflow: hidden;
}

.row {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--c-border);
}

.row:last-child {
  border-bottom: 0;
}

.row-main {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: var(--fs-sm);
}

.type {
  color: var(--c-text-1);
}

.stage {
  color: var(--c-text-2);
}

.pct {
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.time {
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}

/* 进度条走 app.css 的 .progress-bar；这里只补本页的行间距。
   批量整理时一屏会有 N 行同时走，所以填充在那边刻意用 transform 而不是 width */
.progress-bar {
  margin-top: var(--space-2);
}

.row-error {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-danger-ink);
}

.err-text {
  flex: 1;
}

/* 失败原因的下一步：只在这条真的能修的时候出现（见 FAILURE_FIX） */
.row-hint {
  margin-top: var(--space-1);
  font-size: var(--fs-xs);
  line-height: 1.5;
  color: var(--c-text-2);
}

/* 「N 步」：一个可点的徽标样按钮，不是装饰。组里只有一条时不出现 */
.steps {
  padding: 2px var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: 999px;
  background: var(--c-bg-2);
  font: inherit;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  cursor: pointer;
}

.steps:hover {
  color: var(--c-text-1);
  border-color: var(--c-primary-border);
}

/* 展开后看到的内部阶段：缩进 + 更小的字，明确它是「这件事里面的几步」 */
.sub-rows {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: var(--space-2) 0 0 var(--space-4);
  border-top: 1px dashed var(--c-border);
}

.sub-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  font-size: var(--fs-xs);
}

.sub-row .type {
  color: var(--c-text-2);
}
</style>
