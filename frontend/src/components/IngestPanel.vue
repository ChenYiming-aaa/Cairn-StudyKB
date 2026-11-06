<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'

import { api, friendlyMessage, pollTask } from '../api/client'

/**
 * 采集面板（T2.8）：三个入口 —— 粘贴文本 / 链接（网页或视频）/ 拖入 txt。
 *
 * 网页与视频走同一条「派任务 + 轮询」的路，差别只在调哪个端点；
 * 阶段文案集中在一张表里，后端 `stage` 一改这里就该跟着改（接口契约 §3）。
 */
const props = defineProps({
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'created', 'existing', 'ingested'])

const MODES = [
  { key: 'paste', label: '粘贴文本' },
  { key: 'link', label: '链接采集' },
  { key: 'file', label: '拖入文件' },
]

// 后端 stage → 人话（与 fetch_url / transcribe_video 的实际取值一致）
const STAGE_TEXT = {
  fetching: '抓取网页正文',
  saving: '写入知识库',
  metadata: '读取视频信息',
  downloading: '下载音频',
  transcribing: '语音识别中',
}

const mode = ref('paste')
const paste = reactive({ title: '', content: '' })
const link = reactive({ url: '', kind: 'web', model: 'small' })

const task = ref(null)          // { id, status, progress, stage, error_code, error_msg }
const submitting = ref(false)
const errorText = ref('')
const draggedOver = ref(false)
const fileInput = ref(null)

let stopPoll = null

const busy = computed(() => task.value?.status === 'queued' || task.value?.status === 'running')
const done = computed(() => task.value?.status === 'done')
const failed = computed(() => task.value?.status === 'failed')
const progress = computed(() => task.value?.progress ?? 0)
const stageLabel = computed(() => STAGE_TEXT[task.value?.stage] || '处理中')
const words = computed(() => paste.content.trim().length)
const canPaste = computed(() => words.value > 0 && !submitting.value)
const canLink = computed(() => link.url.trim().length > 0 && !submitting.value && !busy.value)

/** 卡在 30% 多半是在加载（或首次下载）模型，说清楚省得用户以为卡死。 */
const waitHint = computed(() => {
  const stage = task.value?.stage
  const progress = task.value?.progress ?? 0
  if (stage === 'transcribing' && progress <= 30) return '正在加载语音模型，首次使用要下载（small 约 500MB）…'
  if (stage === 'downloading' || stage === 'metadata') return '正在读取视频信息并下载音频…'
  return ''
})

/** 后端 error_msg 形如 "FetchError: 该视频没有音轨…"，去掉类名前缀只留人话。 */
function cleanError(msg) {
  return String(msg || '').replace(/^[A-Za-z]+(Error|Exception):\s*/, '') || '采集失败'
}

function reset() {
  mode.value = 'paste'
  paste.title = ''
  paste.content = ''
  link.url = ''
  link.kind = 'web'
  link.model = 'small'
  task.value = null
  submitting.value = false
  errorText.value = ''
  stopPoll?.()
  stopPoll = null
}

watch(() => props.open, (open) => {
  if (open) reset()
})

onBeforeUnmount(() => stopPoll?.())

function tryClose() {
  // 任务在跑也可以关：后端线程池照常跑，任务中心能看到结果
  emit('close')
}

// ── 粘贴 / 拖文件 ──────────────────────────────────────────
async function submitPaste() {
  if (!canPaste.value) return
  submitting.value = true
  errorText.value = ''
  try {
    const payload = { raw_content: paste.content }
    if (paste.title.trim()) payload.title = paste.title.trim()
    emit('created', await api.createItem(payload))
  } catch (err) {
    errorText.value = friendlyMessage(err)
  } finally {
    submitting.value = false
  }
}

async function readFile(file) {
  if (!file) return false
  const ok = /\.(txt|md|markdown)$/i.test(file.name)
  if (!ok) {
    errorText.value = '只支持 .txt / .md 文本文件；其他格式请直接复制内容粘贴'
    return false
  }
  try {
    paste.content = await file.text()
    paste.title = file.name.replace(/\.[^.]+$/, '').slice(0, 40)
    mode.value = 'paste'
    errorText.value = ''
    return true
  } catch {
    errorText.value = '读取文件失败，请重试或改用粘贴'
    return false
  }
}

function onDrop(event) {
  draggedOver.value = false
  readFile(event.dataTransfer?.files?.[0])
}

function onPickFile(event) {
  readFile(event.target.files?.[0])
  event.target.value = ''          // 允许重复选同一个文件
}

// ── 链接采集 ───────────────────────────────────────────────
function watchTask(id) {
  stopPoll?.()
  task.value = { id, status: 'queued', progress: 0, stage: '' }
  stopPoll = pollTask(id, {
    onUpdate: (t) => {
      task.value = { id, ...t }
      if (t.status === 'done') emit('ingested', t)
    },
  })
}

async function submitLink() {
  if (!canLink.value) return
  submitting.value = true
  errorText.value = ''
  try {
    const url = link.url.trim()
    const res = link.kind === 'video'
      ? await api.ingestVideo({ url, model: link.model })
      : await api.ingestUrl({ url })
    if (!res.task_id) {
      // 同一 URL 已在库里：不派任务，直接把用户带到已有条目
      emit('existing', res.existing_item_id)
      return
    }
    watchTask(res.task_id)
  } catch (err) {
    errorText.value = friendlyMessage(err)
  } finally {
    submitting.value = false
  }
}

async function retry() {
  if (!task.value?.id) return
  submitting.value = true
  errorText.value = ''
  try {
    const res = await api.retryTask(task.value.id)
    watchTask(res.task_id)
  } catch (err) {
    errorText.value = friendlyMessage(err)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div v-if="open" class="mask" @click.self="tryClose" @keydown.esc="tryClose">
    <div
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-label="采集内容"
      :class="{ drag: draggedOver }"
      @dragover.prevent="draggedOver = true"
      @dragleave.self="draggedOver = false"
      @drop.prevent="onDrop"
    >
      <header class="dialog-head">
        <h2>采集内容</h2>
        <nav class="tabs">
          <button
            v-for="m in MODES"
            :key="m.key"
            class="tab"
            :class="{ on: mode === m.key }"
            type="button"
            :disabled="busy"
            @click="mode = m.key"
          >
            {{ m.label }}
          </button>
        </nav>
        <div class="grow" />
        <button class="btn btn-ghost btn-sm" type="button" @click="tryClose">关闭</button>
      </header>

      <div class="dialog-body">
        <!-- 粘贴 -->
        <template v-if="mode === 'paste'">
          <label class="field">
            <span class="field-label">标题（可留空，整理后由 AI 生成）</span>
            <input v-model="paste.title" class="input" type="text" maxlength="40" placeholder="可留空，整理时会自动生成标题" />
          </label>
          <label class="field">
            <span class="field-label">正文</span>
            <textarea
              v-model="paste.content"
              class="textarea"
              rows="12"
              placeholder="把要整理的段落粘进来，800 字以上效果最好；也可以直接把 .txt 拖到窗口里"
              autofocus
            />
          </label>
        </template>

        <!-- 链接 -->
        <template v-else-if="mode === 'link'">
          <div class="seg">
            <button class="seg-item" :class="{ on: link.kind === 'web' }" type="button" @click="link.kind = 'web'">
              网页正文
            </button>
            <button class="seg-item" :class="{ on: link.kind === 'video' }" type="button" @click="link.kind = 'video'">
              视频转录
            </button>
          </div>

          <label class="field">
            <span class="field-label">链接</span>
            <input
              v-model="link.url"
              class="input"
              type="url"
              :placeholder="link.kind === 'video' ? '视频页地址，例如 https://www.bilibili.com/video/BV...' : '文章地址，例如 https://example.com/post'"
              @keyup.enter="submitLink"
            />
          </label>

          <label v-if="link.kind === 'video'" class="field">
            <span class="field-label">模型（越大越准，也越慢）</span>
            <select v-model="link.model" class="input">
              <option value="tiny">tiny（最快，适合试水）</option>
              <option value="base">base</option>
              <option value="small">small（默认）</option>
              <option value="medium">medium</option>
            </select>
          </label>

          <p class="note">
            {{ link.kind === 'video'
              ? '视频会先下音频再转录，1 分钟视频大约 1 分钟；首次使用要下载模型（small 约 500MB）。'
              : '只抓正文，导航与版权声明会被过滤；动态渲染的页面可能抓不到，建议改用粘贴。' }}
          </p>
        </template>

        <!-- 文件 -->
        <template v-else>
          <div class="dropzone" @click="fileInput?.click()">
            <p class="drop-title">把 .txt / .md 拖到这里</p>
            <p class="drop-hint">或点击选择文件；读入后会转到「粘贴文本」，可先改标题再入库</p>
            <input ref="fileInput" class="hidden" type="file" accept=".txt,.md,.markdown" @change="onPickFile" />
          </div>
        </template>

        <!-- 进度 / 结果 -->
        <section v-if="task" class="progress-box" :class="task.status">
          <div class="progress-head">
            <span class="progress-stage">
              {{ done ? '已入库' : failed ? '采集失败' : stageLabel }}
            </span>
            <span class="progress-pct">{{ progress }}%</span>
          </div>
          <div class="bar"><i :style="{ width: progress + '%' }" /></div>
          <p v-if="failed" class="fail-msg">
            {{ cleanError(task.error_msg) }}
            <span v-if="task.error_code" class="code">{{ task.error_code }}</span>
          </p>
          <p v-else-if="done" class="ok-msg">已入库，关闭本窗口即可在列表里看到它。</p>
          <p v-else-if="waitHint" class="wait-msg">{{ waitHint }}</p>
        </section>

        <div class="dialog-foot">
          <span v-if="mode === 'paste'" class="hint">{{ words }} 字</span>
          <span v-if="errorText" class="error">{{ errorText }}</span>
          <div class="grow" />
          <button class="btn" type="button" @click="tryClose">取消</button>
          <button v-if="failed" class="btn" type="button" :disabled="submitting" @click="retry">
            重试
          </button>
          <button
            v-if="mode === 'paste'"
            class="btn btn-primary"
            type="button"
            :disabled="!canPaste"
            @click="submitPaste"
          >
            {{ submitting ? '正在保存…' : '加入知识库' }}
          </button>
          <button
            v-else-if="mode === 'link'"
            class="btn btn-primary"
            type="button"
            :disabled="!canLink"
            @click="submitLink"
          >
            {{ busy ? '正在采集…' : '开始采集' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(35, 33, 28, 0.32);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  z-index: 50;
}

.dialog {
  width: min(720px, 100%);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg-1);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  overflow: hidden;
  transition: outline-color 0.15s;
  outline: 2px dashed transparent;
  outline-offset: -8px;
}

.dialog.drag {
  outline-color: var(--c-primary);
}

.dialog-head {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--c-border);
}

.dialog-head h2 {
  font-size: var(--fs-lg);
}

.tabs {
  display: flex;
  gap: var(--space-1);
  background: var(--c-bg-2);
  padding: 3px;
  border-radius: var(--radius-sm);
}

.tab {
  padding: var(--space-1) var(--space-3);
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.tab.on {
  background: var(--c-bg-1);
  color: var(--c-text-1);
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.08));
}

.tab:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dialog-body {
  padding: var(--space-4) var(--space-6) var(--space-6);
  overflow: auto;
}

.field {
  display: block;
  margin-bottom: var(--space-4);
}

.field-label {
  display: block;
  margin-bottom: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.seg {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  margin-bottom: var(--space-4);
  background: var(--c-bg-2);
  border-radius: var(--radius-sm);
}

.seg-item {
  padding: var(--space-1) var(--space-3);
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.seg-item.on {
  background: var(--c-primary-soft);
  color: var(--c-primary);
}

.note {
  margin: 0 0 var(--space-4);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 200px;
  padding: var(--space-6);
  border: 1px dashed var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  cursor: pointer;
  text-align: center;
}

.drop-title {
  margin: 0;
  font-size: var(--fs-md);
  color: var(--c-text-1);
}

.drop-hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.hidden {
  display: none;
}

.progress-box {
  margin-bottom: var(--space-4);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
}

.progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.bar {
  height: 6px;
  border-radius: 3px;
  background: var(--c-bg-2);
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--c-primary);
  transition: width 0.3s ease;
}

.progress-box.failed .bar i {
  background: var(--c-danger);
}

.fail-msg,
.ok-msg,
.wait-msg {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
}

.fail-msg {
  color: var(--c-danger);
}

.ok-msg {
  color: var(--c-success);
}

.wait-msg {
  color: var(--c-text-3);
}

.code {
  margin-left: var(--space-2);
  color: var(--c-text-3);
  font-family: var(--font-mono, monospace);
}

.dialog-foot {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.grow {
  flex: 1;
}

.hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.error {
  font-size: var(--fs-xs);
  color: var(--c-danger);
}
</style>
