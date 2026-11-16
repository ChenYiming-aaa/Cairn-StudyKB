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
    hint: '这条要站点登录才读得到。到采集面板的「文件与链接」里登录，回来再重试。',
  },
  FETCH_BLOCKED: {
    label: '去登录', go: 'login',
    hint: '站点把这次请求拦下了，多半还是要登录；不登录直接重试，结果不会变。',
  },
  COMPONENT_MISSING: {
    label: '去装组件', go: 'downloads',
    hint: '缺识别组件。先去设置里装「文字识别」，装完回到这里重试。',
  },
  OCR_MISSING: {
    label: '去装组件', go: 'downloads',
    hint: '缺识别组件。先去设置里装「文字识别」，装完回到这里重试。',
  },
  LLM_NO_KEY: {
    label: '去配模型', go: 'model',
    hint: '还没配模型 Key。先去设置 → 模型里填上，再重试。',
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
      <h2>任务中心</h2>
      <span class="sub">最近 50 条 · 共 {{ total }}</span>
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
      <li v-for="task in tasks" :key="task.id" class="row">
        <div class="row-main">
          <span class="badge" :class="statusView(task.status)[1]">{{ statusView(task.status)[0] }}</span>
          <span class="type">{{ typeText(task.type) }}</span>
          <span v-if="task.stage" class="stage">{{ STAGE_TEXT[task.stage] || task.stage }}</span>
          <span class="pct">{{ task.progress }}%</span>
          <div class="grow" />
          <button
            v-if="task.status === 'done' && itemIdOf(task)"
            class="btn btn-sm"
            type="button"
            @click="openTaskItem(task)"
          >去看这条</button>
          <span class="time">{{ shortTime(task.created_at) }}</span>
        </div>

        <div v-if="task.status === 'running' || task.status === 'queued'" class="bar">
          <i :style="{ width: task.progress + '%' }" />
        </div>

        <div v-if="task.error_msg" class="row-error">
          <span class="err-text">{{ cleanError(task.error_msg) }}</span>
          <code v-if="task.error_code" class="code">{{ task.error_code }}</code>
          <!-- 能修的先给「去修」：这些码直接重试必然再失败（没登录 / 没装组件 / 没配 Key） -->
          <button
            v-if="fixOf(task)"
            class="btn btn-sm"
            type="button"
            @click="applyFix(task)"
          >{{ fixOf(task).label }}</button>
          <button
            v-else-if="task.status === 'failed'"
            class="btn btn-sm"
            type="button"
            :disabled="retrying === task.id"
            @click="retry(task)"
          >
            {{ retrying === task.id ? '重新排队…' : '重试' }}
          </button>
        </div>
        <p v-if="fixOf(task)" class="row-hint">{{ fixOf(task).hint }}</p>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.tasks {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-6);
}

.tasks-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.tasks-head h2 {
  font-size: var(--fs-lg);
}

.sub {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
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

.bar {
  height: 4px;
  margin-top: var(--space-2);
  border-radius: 2px;
  background: var(--c-bg-2);
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--c-primary);
  transition: width 0.3s ease;
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

.code {
  color: var(--c-text-3);
  font-family: var(--font-mono);
}

/* 失败原因的下一步：只在这条真的能修的时候出现（见 FAILURE_FIX） */
.row-hint {
  margin-top: var(--space-1);
  font-size: var(--fs-xs);
  line-height: 1.5;
  color: var(--c-text-2);
}
</style>
