<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'

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
const emit = defineEmits(['close', 'created', 'existing', 'ingested', 'open'])

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

const task = ref(null)          // { id, status, progress, stage, error_code, error_msg, output_json }
const submitting = ref(false)
const errorText = ref('')
const draggedOver = ref(false)
const fileInput = ref(null)
const urlInput = ref(null)

let stopPoll = null

const busy = computed(() => task.value?.status === 'queued' || task.value?.status === 'running')
const done = computed(() => task.value?.status === 'done')
const failed = computed(() => task.value?.status === 'failed')
const progress = computed(() => task.value?.progress ?? 0)
const stageLabel = computed(() => STAGE_TEXT[task.value?.stage] || '正在采集')
const words = computed(() => paste.content.trim().length)
const canPaste = computed(() => words.value > 0 && !submitting.value)
const canLink = computed(() => link.url.trim().length > 0 && !submitting.value && !busy.value)

/** 任务结果里的条目 id —— 「去看看」跳转要用（web/video 两种任务都写 item_id） */
const resultItemId = computed(() => task.value?.output_json?.item_id || null)

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

/** 丢掉上一轮结果。切 tab / 切网页↔视频 / 继续采集都要调，
 *  否则「已入库」会跟着串到下一个入口（T2.8 实测 bug）。 */
function clearTask() {
  stopPoll?.()
  stopPoll = null
  task.value = null
  errorText.value = ''
}

function switchMode(key) {
  if (busy.value || key === mode.value) return
  mode.value = key
  clearTask()
}

function switchKind(kind) {
  if (busy.value || kind === link.kind) return
  link.kind = kind
  // 网页地址和视频地址不通用：留着上一条只会让人误点「开始采集」白跑一趟
  link.url = ''
  link.model = 'small'
  clearTask()
  nextTick(() => urlInput.value?.focus())
}

/** 「继续采集」：清空结果与链接，光标回到输入框，留在当前入口 */
function continueCollect() {
  clearTask()
  link.url = ''
  nextTick(() => urlInput.value?.focus())
}

/** 「去看看」：交给 App 关面板并跳到该条目 */
function goSee() {
  if (!resultItemId.value) return
  emit('open', resultItemId.value)
}

watch(() => props.open, (open) => {
  if (open) {
    reset()
    refreshAuth()          // 打开面板先同步登录态，避免「已登录」显示成旧的
  }
})

onBeforeUnmount(() => {
  stopPoll?.()
  clearTimeout(authPoll)
})

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
      // 同一 URL 已在库里：不派任务，但也**不要**把面板直接关掉 ——
      // 用户要的是「去看看」，一句 toast 顶不上，而且面板一消失就像没采成。
      // 就地摆成完成态，按钮与正常入库完全一致。
      stopPoll?.()
      stopPoll = null
      task.value = {
        id: '',
        status: 'done',
        progress: 100,
        stage: 'saving',
        output_json: { item_id: res.existing_item_id, duplicated: true },
      }
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

// ── 站点登录 ───────────────────────────────────────────────
/**
 * 只有「需要登录才给内容」的站点用得上：B 站字幕、知乎受限页。
 * 点登录由后端弹一个独立浏览器窗口（不是用户日常那个），登录态存在后端自己的
 * profile 里，导出成 cookies.txt 给 yt-dlp 和网页抓取共用。
 */
const auth = reactive({
  open: false,
  sites: {},
  busy: false,
  message: '',
  browserAvailable: true,
  login: { status: 'idle', site: '' },
})

const loggedInLabels = computed(() =>
  Object.values(auth.sites).filter((s) => s.logged_in).map((s) => s.label)
)

const authSummary = computed(() =>
  loggedInLabels.value.length ? `已登录 ${loggedInLabels.value.join('、')}` : '均未登录'
)

const authHint = computed(() => {
  // 任务因为"要登录/被拦"失败时，把话说在这儿，省得用户去别处找原因
  const code = task.value?.error_code
  if (code === 'FETCH_BLOCKED') return '这条被站点拦下了，多半要登录。登录后再点一次采集。'
  if (code === 'FETCH_LOGIN_REQUIRED') return '这条要登录后才能看。先登录，再点一次采集。'
  return ''
})

let authPoll = null

/** 拉一次状态，返回 login.status 供轮询判断是否继续。 */
async function refreshAuth() {
  try {
    const data = await api.authStatus()
    auth.sites = data.sites || {}
    auth.browserAvailable = data.browser_available !== false
    const login = data.login || { status: 'idle', site: '' }
    auth.login = login
    if (login.message) auth.message = login.message
    return login.status
  } catch {
    return 'idle'          // 状态拿不到不该打断采集，静默即可
  }
}

function pollAuth() {
  clearTimeout(authPoll)
  const tick = async () => {
    const status = await refreshAuth()
    auth.busy = status === 'running'
    if (status === 'running') authPoll = setTimeout(tick, 1200)
  }
  authPoll = setTimeout(tick, 600)
}

async function startLogin(site) {
  auth.message = ''
  try {
    const res = await api.authLogin(site)
    auth.login = res
    auth.busy = res.status === 'running'
    if (res.message) auth.message = res.message
    if (auth.busy) pollAuth()
  } catch (err) {
    auth.message = friendlyMessage(err)
  }
}

function loginLabel(key, site) {
  if (auth.busy && auth.login?.site === key) return '等待登录…'
  return site.logged_in ? '重新登录' : '登录'
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
            @click="switchMode(m.key)"
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
            <span class="field-label">标题（可留空，整理后由模型生成）</span>
            <input v-model="paste.title" class="input" type="text" maxlength="40" placeholder="可留空，整理时会自动生成标题" />
          </label>
          <label class="field">
            <span class="field-label">正文</span>
            <textarea
              v-model="paste.content"
              class="textarea"
              rows="12"
              placeholder="粘贴正文，800 字以上整理效果更好"
              autofocus
            />
          </label>
        </template>

        <!-- 链接 -->
        <template v-else-if="mode === 'link'">
          <div class="seg">
            <button
              class="seg-item"
              :class="{ on: link.kind === 'web' }"
              type="button"
              :disabled="busy"
              @click="switchKind('web')"
            >
              网页正文
            </button>
            <button
              class="seg-item"
              :class="{ on: link.kind === 'video' }"
              type="button"
              :disabled="busy"
              @click="switchKind('video')"
            >
              视频转录
            </button>
          </div>

          <label class="field">
            <span class="field-label">链接</span>
            <input
              ref="urlInput"
              v-model="link.url"
              class="input"
              type="url"
              :placeholder="link.kind === 'video' ? '视频页地址，例如 https://www.bilibili.com/video/BV...' : '文章地址，例如 https://example.com/post'"
              @keyup.enter="submitLink"
            />
          </label>

          <label v-if="link.kind === 'video'" class="field">
            <span class="field-label">识别精度</span>
            <select v-model="link.model" class="input">
              <option value="tiny">tiny（最快，适合试水）</option>
              <option value="base">base</option>
              <option value="small">small（默认）</option>
              <option value="medium">medium</option>
            </select>
          </label>

          <p class="note">
            {{ link.kind === 'video'
              ? '先下音频再转录，耗时约等于视频长度。首次使用要下载识别模型（约 500MB）。'
              : '只保留正文，导航和版权声明会被去掉。需要登录、要滚动才出内容的页面可能抓不到，改用粘贴更稳。' }}
          </p>

          <!-- 站点登录：只在需要时展开，不占正常采集的视线 -->
          <section class="auth">
            <button class="auth-head" type="button" @click="auth.open = !auth.open">
              <span class="auth-dot" :class="{ on: loggedInLabels.length > 0 }" />
              <span class="auth-title">站点登录</span>
              <span class="auth-sum">{{ authSummary }}</span>
              <span class="auth-more">{{ auth.open ? '收起' : '展开' }}</span>
            </button>

            <div v-if="auth.open" class="auth-body">
              <p class="auth-tip">
                B 站字幕、知乎受限页这类要登录的站点，在这里登一次就行。点「登录」会开一个独立窗口，登完自动保存，不影响你日常用的浏览器。
              </p>
              <p v-if="!auth.browserAvailable" class="auth-warn">
                站点登录暂时用不了：还没装浏览器组件。去「设置 → 下载」装上「网页渲染」就能用。
              </p>
              <div v-else class="auth-list">
                <div v-for="(site, key) in auth.sites" :key="key" class="auth-item">
                  <span class="auth-name">{{ site.label }}</span>
                  <span class="auth-state" :class="{ on: site.logged_in }">
                    {{ site.logged_in ? '已登录' : '未登录' }}
                  </span>
                  <button
                    class="btn btn-sm"
                    type="button"
                    :disabled="auth.busy"
                    @click="startLogin(key)"
                  >
                    {{ loginLabel(key, site) }}
                  </button>
                </div>
              </div>
              <p v-if="authHint" class="auth-warn">{{ authHint }}</p>
              <p v-if="auth.message" class="auth-msg">{{ auth.message }}</p>
            </div>
          </section>
        </template>

        <!-- 文件 -->
        <template v-else>
          <div class="dropzone" @click="fileInput?.click()">
            <p class="drop-title">把 .txt / .md 拖到这里</p>
            <p class="drop-hint">或点击选择文件。读入后转成文本，可以先改标题再保存</p>
            <input ref="fileInput" class="hidden" type="file" accept=".txt,.md,.markdown" @change="onPickFile" />
          </div>
        </template>

        <!-- 进度 / 结果 -->
        <section v-if="task" class="progress-box" :class="task.status">
          <div class="progress-head">
            <span class="progress-stage">
              {{ done ? '已存进知识库' : failed ? '采集失败' : stageLabel }}
            </span>
            <span class="progress-pct">{{ progress }}%</span>
          </div>
          <div class="bar"><i :style="{ width: progress + '%' }" /></div>
          <p v-if="failed" class="fail-msg">
            {{ cleanError(task.error_msg) }}
            <span v-if="task.error_code" class="code">{{ task.error_code }}</span>
          </p>
          <p v-else-if="done" class="ok-msg">
            <template v-if="task.output_json?.duplicated">
              这条已经在知识库里了，没有重复添加。
            </template>
            <template v-else>
              {{ task.output_json?.source === 'subtitle' ? '已用视频自带的字幕入库（没有跑语音识别）。' : '已入库。' }}
              可以继续采集下一条，或点「去看看」打开它。
            </template>
          </p>
          <p v-else-if="waitHint" class="wait-msg">{{ waitHint }}</p>
        </section>

        <div class="dialog-foot">
          <span v-if="mode === 'paste'" class="hint">{{ words }} 字</span>
          <span v-if="errorText" class="error">{{ errorText }}</span>
          <!-- 5.1：按钮只是关面板，任务照跑。以前写「取消」，用户会以为本次采集被终止 -->
          <span v-if="!done && !failed" class="hint">关掉面板任务会继续跑</span>
          <div class="grow" />
          <button class="btn" type="button" @click="done ? continueCollect() : tryClose()">
            {{ done ? '继续采集' : '关闭' }}
          </button>
          <button v-if="failed" class="btn" type="button" :disabled="submitting" @click="retry">
            重试
          </button>
          <button
            v-if="done"
            class="btn btn-primary"
            type="button"
            :disabled="!resultItemId"
            @click="goSee"
          >
            去看看
          </button>
          <button
            v-else-if="mode === 'paste'"
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
  color: var(--c-primary-ink);
}

.seg-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.note {
  margin: 0 0 var(--space-4);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

/* ── 站点登录 ─────────────────────────────────────────── */
.auth {
  margin: 0 0 var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.auth-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 0;
  background: var(--c-bg-0);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  cursor: pointer;
  text-align: left;
}

.auth-head:hover {
  background: var(--c-bg-2);
}

.auth-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-border);
}

.auth-dot.on {
  background: var(--c-success);
}

.auth-title {
  color: var(--c-text-1);
}

.auth-sum {
  color: var(--c-text-3);
}

.auth-more {
  margin-left: auto;
  color: var(--c-text-3);
}

.auth-body {
  padding: var(--space-3);
  border-top: 1px solid var(--c-border);
}

.auth-tip {
  margin: 0 0 var(--space-3);
  font-size: var(--fs-xs);
  line-height: 1.65;
  color: var(--c-text-3);
}

.auth-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.auth-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
}

.auth-name {
  min-width: 48px;
  color: var(--c-text-1);
}

.auth-state {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.auth-state.on {
  color: var(--c-success-ink);
}

.auth-item .btn {
  margin-left: auto;
}

.auth-msg,
.auth-warn {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  line-height: 1.6;
}

.auth-msg {
  color: var(--c-text-2);
}

.auth-warn {
  color: var(--c-warning-ink);
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
  color: var(--c-danger-ink);
}

.ok-msg {
  color: var(--c-success-ink);
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
  color: var(--c-danger-ink);
}
</style>
