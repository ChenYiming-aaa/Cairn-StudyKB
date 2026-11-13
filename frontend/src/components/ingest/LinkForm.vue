<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref } from 'vue'

import { api, friendlyMessage, pollTask } from '../../api/client'
import AuthBox from './AuthBox.vue'

/**
 * 「文件与链接」里的链接区（T9.8）：网页正文 / 视频转录两条路。
 *
 * 两者都是「派任务 + 轮询」：差别只在调哪个端点，阶段文案集中在 `STAGE_TEXT` 一张表里，
 * 后端 `stage` 一改这里就得跟着改（接口契约 §3）。
 */
const emit = defineEmits(['existing', 'ingested', 'open'])

// 后端 stage → 人话（与 fetch_url / transcribe_video 的实际取值一致）
const STAGE_TEXT = {
  fetching: '抓取网页正文',
  saving: '写入知识库',
  metadata: '读取视频信息',
  downloading: '下载音频',
  transcribing: '语音识别中',
}

const link = reactive({ url: '', kind: 'web', model: 'small' })
const task = ref(null)          // { id, status, progress, stage, error_code, error_msg, output_json }
const submitting = ref(false)
const errorText = ref('')
const urlInput = ref(null)

let stopPoll = null

const busy = computed(() => task.value?.status === 'queued' || task.value?.status === 'running')
const done = computed(() => task.value?.status === 'done')
const failed = computed(() => task.value?.status === 'failed')
const progress = computed(() => task.value?.progress ?? 0)
const stageLabel = computed(() => STAGE_TEXT[task.value?.stage] || '正在采集')
const canSubmit = computed(() => link.url.trim().length > 0 && !submitting.value && !busy.value)

/** 任务结果里的条目 id —— 「去看看」跳转要用（web/video 两种任务都写 item_id） */
const resultItemId = computed(() => task.value?.output_json?.item_id || null)

/** 卡在 30% 多半是在加载（或首次下载）模型，说清楚省得用户以为卡死。 */
const waitHint = computed(() => {
  const stage = task.value?.stage
  const at = task.value?.progress ?? 0
  if (stage === 'transcribing' && at <= 30) return '正在加载语音模型，首次使用要下载（small 约 500MB）…'
  if (stage === 'downloading' || stage === 'metadata') return '正在读取视频信息并下载音频…'
  return ''
})

/** 任务因为「要登录 / 被拦」失败时，把话说在登录框里 */
const authHint = computed(() => {
  const code = task.value?.error_code
  if (code === 'FETCH_BLOCKED') return '这条被站点拦下了，多半要登录。登录后再点一次采集。'
  if (code === 'FETCH_LOGIN_REQUIRED') return '这条要登录后才能看。先登录，再点一次采集。'
  return ''
})

/** 后端 error_msg 形如 "FetchError: 该视频没有音轨…"，去掉类名前缀只留人话。 */
function cleanError(msg) {
  return String(msg || '').replace(/^[A-Za-z]+(Error|Exception):\s*/, '') || '采集失败'
}

/** 丢掉上一轮结果。切网页↔视频 / 继续采集都要调，
 *  否则「已入库」会跟着串到下一个入口（T2.8 实测 bug）。 */
function clearTask() {
  stopPoll?.()
  stopPoll = null
  task.value = null
  errorText.value = ''
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

async function submit() {
  if (!canSubmit.value) return
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

/** 「继续采集」：清空结果与链接，光标回到输入框 */
function again() {
  clearTask()
  link.url = ''
  nextTick(() => urlInput.value?.focus())
}

onBeforeUnmount(() => {
  stopPoll?.()
})
</script>

<template>
  <div>
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
        @keyup.enter="submit"
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
          {{ task.output_json?.source === 'subtitle' ? '已用视频自带的字幕，没有跑语音识别。' : '已存进知识库。' }}
        </template>
      </p>
      <p v-else-if="waitHint" class="wait-msg">{{ waitHint }}</p>
    </section>

    <AuthBox :hint="authHint" />

    <div class="foot">
      <span v-if="errorText" class="error">{{ errorText }}</span>
      <span v-if="busy" class="hint">关掉面板任务会继续跑</span>
      <div class="grow" />
      <button v-if="failed" class="btn" type="button" :disabled="submitting" @click="retry">
        重试
      </button>
      <template v-if="done">
        <button class="btn" type="button" @click="again">继续采集</button>
        <button
          class="btn btn-primary"
          type="button"
          :disabled="!resultItemId"
          @click="emit('open', resultItemId)"
        >
          去看看
        </button>
      </template>
      <button
        v-else
        class="btn btn-primary"
        type="button"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ busy ? '正在采集…' : '开始采集' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
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
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.progress-box {
  margin-top: var(--space-4);
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

.foot {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-4);
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
