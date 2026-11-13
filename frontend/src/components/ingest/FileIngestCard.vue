<script setup>
import { computed, onBeforeUnmount, onMounted, reactive } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { useUi } from '../../composables/useUi'
import { fileSize } from '../../utils/format'
import OcrProgress from './OcrProgress.vue'

/**
 * 一个文件的采集卡片（T9.8）：上传 → 落盘 → 排队读字 → 已识别 / 部分 / 缺组件。
 *
 * **两段进度，不许合成一条**：上传是前端能精确算的（XHR 事件），读字是后端页数决定的
 * （`/api/knowledge/{id}/ocr` 的 `done_pages`）。上传 100% 只代表原件存住了，
 * 真正的等待在后面 —— 合成一条会出现「100% 卡住八分钟」这种最让人想重启的形态。
 *
 * 一个卡片一生只处理**一个**文件：三个文件同时传就是三个卡片各跑各的，
 * 进度天然互不干扰（这也是拆组件的主要理由，不是为好看）。
 */
const props = defineProps({
  file: { type: Object, required: true },
})
const emit = defineEmits(['open', 'gone', 'phase', 'saved'])

const { openSettings } = useUi()

// 与后端 `services/files.py` 的白名单同一份；这里拦一次是为了不给后端白传 200 MB
const ALLOWED = ['docx', 'pdf', 'pptx', 'xlsx', 'txt', 'md', 'png', 'jpg', 'jpeg', 'webp']
const LEGACY = { doc: 'docx', wps: 'docx', ppt: 'pptx', xls: 'xlsx', xlt: 'xlsx' }
// 要识别组件的格式（ADR-033）：不装就读不出字，其余走抽取，跟组件无关
const OCR_EXT = ['pdf', 'png', 'jpg', 'jpeg', 'webp']

const ext = ((props.file.name.split('.').pop() || '')).toLowerCase()
const isOcr = OCR_EXT.includes(ext)
const POLL_MS = 2000
const POLL_LIMIT = 30 * 60 * 1000

const state = reactive({
  phase: 'checking',        // checking|uploading|reading|done|partial|failed|needComponent|cancelled|unsupported
  pct: 0,                   // 上传百分比，只在上传段有意义
  itemId: null,
  duplicated: false,
  ocr: { status: '', done: 0, total: 0, failed: 0 },
  error: '',
})

let ctl = null
let timer = null
let startedAt = 0

const size = computed(() => fileSize(props.file.size))
const label = computed(() => (isOcr ? '识别' : '读取'))
const hasItem = computed(() => Boolean(state.itemId))

/** 主句：一句话说清"现在在哪一步"，状态机变了一定要跟着改 */
const headline = computed(() => {
  switch (state.phase) {
    case 'checking':
      return '正在检查…'
    case 'uploading':
      return `上传中 ${state.pct}%`
    case 'reading':
      return state.duplicated ? '已经在知识库里了，正在读字' : '已存好，正在读字'
    case 'done':
      return state.duplicated
        ? `已经在知识库里了，已${label.value} ${state.ocr.total} 页`
        : `已${label.value} ${state.ocr.total} 页`
    case 'partial':
      // 两种原因都走这一条：缺页（没认出来）与只读了前一部分（xlsx 200 行、txt 100 万字）。
      // 界面上不猜是哪种 —— `/ocr` 只回状态和页数，猜错比说得含糊更糟。
      return state.ocr.failed
        ? `有 ${state.ocr.failed} 页没${label.value}出来`
        : '内容不全'
    case 'failed':
      return '没读成'
    case 'needComponent':
      return '已存好，但读不出字'
    case 'cancelled':
      return '已取消，没存进知识库'
    case 'unsupported':
      return '这个格式传不了'
    default:
      return ''
  }
})

/** 补充句：只在需要解释"为什么"或"下一步做什么"时出现 */
const detail = computed(() => {
  switch (state.phase) {
    case 'reading':
      return isOcr
        ? '页面多的文件要几分钟。可以关掉面板，读完了会在任务里看到。'
        : '读完就能搜到、能整理了。'
    case 'partial':
      return '认出来的部分照样能搜到、能整理；没读到的部分不在里面。'
    case 'failed':
      return state.error || '原因在任务里，可以重读一次。'
    case 'needComponent':
      return '读 PDF 与图片要先用「本地识别」。装完回来点「重读」就行，原件已经存好了。'
    case 'cancelled':
      return '上传到一半就停了，什么都没留下。'
    case 'unsupported':
      return state.error
    default:
      return ''
  }
})

function setPhase(phase) {
  state.phase = phase
  emit('phase', phase)
}

function clearTimer() {
  if (timer) clearTimeout(timer)
  timer = null
}

/** 白名单外直接判掉：LEGACY 给「另存为」，其余给能传的格式清单 */
function precheck() {
  if (ALLOWED.includes(ext)) return true
  const target = LEGACY[ext]
  state.error = target
    ? `不认 .${ext}。另存为 .${target} 再传，内容不会变`
    : `不认 .${ext || '这个'} 格式。可以传 Word、PDF、PPT、Excel、图片、文本`
  setPhase('unsupported')
  return false
}

async function start() {
  if (!precheck()) return
  clearTimer()
  state.pct = 0
  state.error = ''
  setPhase('uploading')
  ctl = new AbortController()
  try {
    const res = await api.uploadFile(props.file, {
      onProgress: (pct) => {
        state.pct = pct
      },
      signal: ctl.signal,
    })
    onSaved(res)
  } catch (err) {
    if (err?.name === 'AbortError') {
      setPhase('cancelled')
      return
    }
    state.error = friendlyMessage(err)
    setPhase('failed')
  } finally {
    ctl = null
  }
}

/** 后端落盘即排队：`running` 就有得等，`pending` 且没有 task_id 才是"没装组件" */
function onSaved(res) {
  state.itemId = res.item_id
  emit('saved', res.item_id)
  state.pct = 100
  state.duplicated = Boolean(res.duplicated)
  state.ocr.total = Number(res.page_count || 0)
  const status = res.ocr_status || 'none'

  if (status === 'running' || (status === 'pending' && res.task_id)) {
    startedAt = Date.now()
    setPhase('reading')
    poll()
    return
  }
  if (status === 'pending') {
    // 抽取格式一定能排队，走到这里是后端异常；PDF/图片则是"没装识别组件"
    if (isOcr) {
      setPhase('needComponent')
    } else {
      state.error = '这份文件没能排上读字，点「重读」再试一次。'
      setPhase('failed')
    }
    return
  }
  if (status === 'none') {
    state.error = '原件存好了，但这类文件读不出文字。'
    setPhase('unsupported')
    return
  }
  settle(status)
}

function settle(status) {
  if (status === 'done' || status === 'partial') {
    setPhase(status)
    return
  }
  if (!state.error) state.error = '原因在任务里，可以重读一次。'
  setPhase('failed')
}

async function poll() {
  clearTimer()
  try {
    const data = await api.ocrProgress(state.itemId)
    state.ocr.status = data.status || ''
    state.ocr.done = Number(data.done_pages || 0)
    state.ocr.total = Number(data.total_pages || state.ocr.total || 0)
    state.ocr.failed = (data.failed_pages || []).length

    if (data.status === 'done' || data.status === 'partial') {
      settle(data.status)
      return
    }
    if (data.status === 'failed') {
      state.error = '读到一半断了。原因在任务里，可以重读一次。'
      setPhase('failed')
      return
    }
    if (Date.now() - startedAt > POLL_LIMIT) {
      state.error = '等了半小时还没读完。它可能还在后台跑，去任务里看看。'
      setPhase('failed')
      return
    }
    timer = setTimeout(poll, POLL_MS)
  } catch (err) {
    state.error = friendlyMessage(err)
    setPhase('failed')
  }
}

/** 重读：原件已在库就重新排队；上传都没成的话，从头再传一遍 */
async function retry() {
  if (!hasItem.value) return start()
  state.error = ''
  startedAt = Date.now()
  setPhase('reading')
  try {
    await api.reocr(state.itemId)
    poll()
  } catch (err) {
    if (err?.code === 'OCR_RUNNING') {
      // 上一轮其实还在跑（比如另一个窗口点的）：别报错，接着看进度
      poll()
      return
    }
    state.error = friendlyMessage(err)
    setPhase('failed')
  }
}

function cancel() {
  ctl?.abort()
}

onMounted(() => {
  start()
})

onBeforeUnmount(() => {
  clearTimer()
  // 面板关掉 = 这次上传作废：XHR 一断，后端的临时文件会被删掉，不会留半份内容
  ctl?.abort()
})
</script>

<template>
  <div class="card" :class="state.phase">
    <div class="card-body">
      <div class="card-line">
        <span class="card-name" :title="file.name">{{ file.name }}</span>
        <span class="card-size">{{ size }}</span>
      </div>
      <p class="card-state">{{ headline }}</p>
      <OcrProgress
        v-if="state.phase === 'reading'"
        :done="state.ocr.done"
        :total="state.ocr.total"
        :label="label"
      />
      <div v-else-if="state.phase === 'uploading'" class="bar">
        <i :style="{ width: state.pct + '%' }" />
      </div>
      <p v-if="detail" class="card-detail">{{ detail }}</p>
    </div>

    <div class="card-acts">
      <button
        v-if="state.phase === 'uploading'"
        class="btn btn-sm"
        type="button"
        @click="cancel"
      >
        取消
      </button>
      <button
        v-else-if="state.phase === 'needComponent'"
        class="btn btn-sm"
        type="button"
        @click="openSettings('downloads')"
      >
        去设置
      </button>
      <template v-else-if="state.phase === 'failed' || state.phase === 'cancelled'">
        <button class="btn btn-sm" type="button" @click="retry">
          {{ hasItem ? '重读' : '重新上传' }}
        </button>
      </template>
      <template v-else-if="state.phase === 'partial'">
        <button class="btn btn-sm" type="button" @click="retry">重读</button>
        <button class="btn btn-sm" type="button" @click="emit('open', state.itemId)">去看看</button>
      </template>
      <template v-else-if="state.phase === 'done'">
        <button class="btn btn-sm" type="button" @click="emit('open', state.itemId)">去看看</button>
      </template>
      <button
        v-else-if="state.phase === 'unsupported'"
        class="btn btn-sm"
        type="button"
        @click="emit('gone')"
      >
        移除
      </button>
    </div>
  </div>
</template>

<style scoped>
.card {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
}

.card.needComponent,
.card.failed {
  border-color: var(--c-warning-border);
}

.card-body {
  flex: 1;
  min-width: 0;
}

.card-line {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.card-name {
  min-width: 0;
  overflow: hidden;
  font-size: var(--fs-sm);
  color: var(--c-text-1);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-size {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.card-state {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

.card.done .card-state {
  color: var(--c-success-ink);
}

/* 部分页没认出来是「有东西但不完整」，不能跟完整成功一个颜色 */
.card.partial .card-state {
  color: var(--c-warning-ink);
}

.card.failed .card-state,
.card.unsupported .card-state {
  color: var(--c-danger-ink);
}

.card.needComponent .card-state {
  color: var(--c-warning-ink);
}

.card-detail {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--c-text-3);
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
  transition: width 0.2s linear;
}

.card-acts {
  display: flex;
  flex: none;
  gap: var(--space-2);
}
</style>
