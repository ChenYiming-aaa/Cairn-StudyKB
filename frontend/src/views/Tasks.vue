<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api, friendlyMessage } from '../api/client'
import { useToast } from '../composables/useToast'
import { shortTime } from '../utils/format'

/**
 * 任务中心（T2.9）：最近 50 条任务，失败可重试。
 *
 * 刷新策略：有 queued/running 时每 2 秒轻量轮询（列表接口本身只查 50 行，代价很小）；
 * 全部落定就停，不留后台定时器。
 */
const toast = useToast()

const tasks = ref([])
const total = ref(0)
const loading = ref(false)
const errorText = ref('')
const retrying = ref('')

const TYPE_TEXT = {
  fetch_url: '网页采集',
  transcribe_video: '视频转录',
  organize: '整理',
  index_embed: '向量索引',
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
    toast.ok('已重新排队，马上开始')
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
    <p v-else-if="!tasks.length" class="empty">还没有任务。点顶栏「＋ 采集内容」采一条，这里就有记录了。</p>

    <ul v-else class="rows">
      <li v-for="task in tasks" :key="task.id" class="row">
        <div class="row-main">
          <span class="badge" :class="statusView(task.status)[1]">{{ statusView(task.status)[0] }}</span>
          <span class="type">{{ typeText(task.type) }}</span>
          <span v-if="task.stage" class="stage">{{ STAGE_TEXT[task.stage] || task.stage }}</span>
          <span class="pct">{{ task.progress }}%</span>
          <div class="grow" />
          <span class="time">{{ shortTime(task.created_at) }}</span>
        </div>

        <div v-if="task.status === 'running' || task.status === 'queued'" class="bar">
          <i :style="{ width: task.progress + '%' }" />
        </div>

        <div v-if="task.error_msg" class="row-error">
          <span class="err-text">{{ cleanError(task.error_msg) }}</span>
          <code v-if="task.error_code" class="code">{{ task.error_code }}</code>
          <button
            v-if="task.status === 'failed'"
            class="btn btn-sm"
            type="button"
            :disabled="retrying === task.id"
            @click="retry(task)"
          >
            {{ retrying === task.id ? '重新排队…' : '重试' }}
          </button>
        </div>
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

.error {
  color: var(--c-danger);
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
  color: var(--c-danger);
}

.err-text {
  flex: 1;
}

.code {
  color: var(--c-text-3);
  font-family: var(--font-mono);
}
</style>
