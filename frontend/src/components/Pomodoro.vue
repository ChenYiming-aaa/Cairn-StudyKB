<!-- eslint-disable vue/multi-word-component-names -- 文件名是 M5 文档指定的产出物，改名会让文档与代码再对不上一次 -->
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { BREAK_SECONDS, PRESETS, useTimer } from '../composables/useTimer'
import { clock as fmtClock, humanDuration } from '../utils/format'

/**
 * 番茄钟面板（T5.1）。倒计时**不在这里算**——所有时间都来自 `useTimer` 的时间戳口径，
 * 本组件只负责画和发指令。
 *
 * 面板三种形态：
 *   开始前（没有 session）→ 选时长（25/5 可配，默认 25）
 *   进行中              → 倒计时 / 暂停 / 提前完成 / 放弃
 *   到点或提前完成后     → 写一句笔记 → 保存；保存后可以顺手休息 5 分钟
 */
const {
  session,
  panelOpen,
  noteOpen,
  lastFinished,
  isActive,
  isRunning,
  isPaused,
  plannedSeconds,
  elapsedSeconds,
  remainingSeconds,
  progress,
  error,
  start,
  pause,
  resume,
  finish,
  requestNote,
  abandon,
  closePanel,
  dismissNote,
} = useTimer()

const minutes = ref(25)
const note = ref('')
const busy = ref(false)
/** 休息计时器是纯前端的，不写库：休息不是学习时长，记进去只会污染统计 */
const breakLeft = ref(null)
let breakTimer = null

const targetLabel = computed(() => {
  const target = session.value
  if (!target) return ''
  if (target.target_title) return target.target_title
  return target.target_type === 'item' ? `内容 #${target.target_id}` : '自由专注'
})

const plannedLabel = computed(() => `${Math.round(plannedSeconds.value / 60)} 分钟`)

const canSave = computed(() => note.value.trim().length <= 200)

function pick(value) {
  minutes.value = value
}

async function startFree() {
  busy.value = true
  await start({ target_type: 'free', target_id: null, planned_seconds: minutes.value * 60 })
  busy.value = false
}

async function onPause() {
  busy.value = true
  await pause()
  busy.value = false
}

async function onResume() {
  busy.value = true
  await resume()
  busy.value = false
}

/** 提前完成 = 现在就把这一轮收掉；先冻住时长，再让用户写笔记（和到点是同一套流程） */
async function onEarlyFinish() {
  busy.value = true
  await requestNote()
  busy.value = false
}

async function onAbandon() {
  if (!window.confirm('放弃这一轮？已用时间会记为「已放弃」，不算进专注统计。')) return
  busy.value = true
  await abandon()
  note.value = ''
  busy.value = false
}

async function onSaveNote() {
  busy.value = true
  await finish(note.value.trim())
  note.value = ''
  busy.value = false
}

function skipNote() {
  dismissNote()
  finish('')
}

function startBreak() {
  breakLeft.value = BREAK_SECONDS
  if (breakTimer) clearInterval(breakTimer)
  breakTimer = setInterval(() => {
    breakLeft.value = Math.max(0, breakLeft.value - 1)
    if (breakLeft.value === 0) stopBreak()
  }, 1000)
}

function stopBreak() {
  if (breakTimer) clearInterval(breakTimer)
  breakTimer = null
  breakLeft.value = null
}

// 面板关掉就停掉本地休息计时，别在后台空转
watch(panelOpen, (open) => {
  if (!open) {
    stopBreak()
    note.value = ''
  }
})

onBeforeUnmount(stopBreak)
</script>

<template>
  <div v-if="panelOpen" class="overlay" @click.self="closePanel()">
    <section class="card">
      <header class="card-head">
        <span class="card-title">专注</span>
        <button class="btn btn-sm btn-ghost" type="button" @click="closePanel()">收起</button>
      </header>

      <!-- ① 刚结束的一轮 -->
      <div v-if="lastFinished" class="body done-body">
        <p class="done-title">
          {{ lastFinished.abandoned ? '这一轮已放弃' : '这一轮完成' }}
        </p>
        <p class="done-time" :class="{ muted: lastFinished.abandoned }">
          {{ lastFinished.abandoned ? '不计入专注统计' : `+${humanDuration(lastFinished.elapsed_seconds)}` }}
        </p>
        <p v-if="lastFinished.note" class="done-note">「{{ lastFinished.note }}」</p>

        <div v-if="breakLeft === null" class="done-actions">
          <button v-if="!lastFinished.abandoned" class="btn btn-primary btn-sm" type="button" @click="startBreak">
            休息 5 分钟
          </button>
          <button class="btn btn-sm" type="button" @click="closePanel()">结束</button>
        </div>
        <div v-else class="break-box">
          <span class="break-time">{{ fmtClock(breakLeft) }}</span>
          <button class="btn btn-sm btn-ghost" type="button" @click="stopBreak()">跳过休息</button>
        </div>
      </div>

      <!-- ② 进行中 -->
      <div v-else-if="isActive" class="body">
        <p class="target" :title="targetLabel">{{ targetLabel }}</p>
        <p class="countdown" :class="{ paused: isPaused }">{{ fmtClock(remainingSeconds) }}</p>
        <div class="bar">
          <i :style="{ width: `${Math.round(progress * 100)}%` }" />
        </div>
        <p class="hint">
          计划 {{ plannedLabel }} · 已用 {{ humanDuration(elapsedSeconds) }}
          <template v-if="isPaused"> · 已暂停</template>
        </p>

        <!-- 到点/提前完成后的笔记框 -->
        <div v-if="noteOpen" class="note-box">
          <p class="note-label">写一句笔记，记下刚才弄懂了什么（可跳过）</p>
          <textarea
            v-model="note"
            class="textarea note-area"
            rows="3"
            maxlength="200"
            placeholder="例：番茄钟的关键是铃响就停，不是凑满 25 分钟"
          />
          <div class="note-actions">
            <button class="btn btn-primary btn-sm" type="button" :disabled="busy || !canSave" @click="onSaveNote">
              保存并结束
            </button>
            <button class="btn btn-sm btn-ghost" type="button" :disabled="busy" @click="skipNote">跳过</button>
          </div>
        </div>

        <div v-else class="actions">
          <button v-if="isRunning" class="btn btn-sm" type="button" :disabled="busy" @click="onPause">暂停</button>
          <button v-else class="btn btn-primary btn-sm" type="button" :disabled="busy" @click="onResume">
            继续
          </button>
          <button class="btn btn-sm" type="button" :disabled="busy" @click="onEarlyFinish">提前完成</button>
          <button class="btn btn-sm btn-danger" type="button" :disabled="busy" @click="onAbandon">放弃</button>
        </div>
      </div>

      <!-- ③ 开始前 -->
      <div v-else class="body">
        <p class="target">选一个时长开始</p>
        <div class="presets">
          <button
            v-for="value in PRESETS"
            :key="value"
            class="preset"
            type="button"
            :class="{ on: minutes === value }"
            @click="pick(value)"
          >
            {{ value }} 分钟
          </button>
        </div>
        <p class="hint">从点下开始那一刻算起，刷新或切页都不会重置。关掉再打开，会接着上一轮。</p>
        <div class="actions">
          <button class="btn btn-primary" type="button" :disabled="busy" @click="startFree">
            开始专注
          </button>
        </div>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding: calc(var(--h-topbar) + var(--space-2)) var(--space-6) 0 0;
  background: rgba(35, 33, 28, 0.12);
}

.card {
  width: 320px;
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  box-shadow: var(--shadow-md);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  letter-spacing: 0.08em;
}

.body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-2);
}

.target {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.countdown {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 44px;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
  color: var(--c-text-1);
}

.countdown.paused {
  color: var(--c-text-3);
}

.bar {
  height: 6px;
  overflow: hidden;
  border-radius: 3px;
  background: var(--c-bg-2);
}

.bar i {
  display: block;
  height: 100%;
  background: var(--c-primary);
  transition: width 0.9s linear;
}

.hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.actions,
.done-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
  padding-top: var(--space-1);
}

.presets {
  display: flex;
  gap: var(--space-2);
}

.preset {
  flex: 1;
  padding: var(--space-2) 0;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  cursor: pointer;
}

.preset.on {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.note-box {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--c-border);
}

.note-label {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

.note-area {
  resize: vertical;
  min-height: 68px;
}

.note-actions {
  display: flex;
  gap: var(--space-2);
}

.done-body {
  align-items: flex-start;
}

.done-title {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.done-time {
  margin: 0;
  font-size: 30px;
  font-family: var(--font-mono);
  color: var(--c-success-ink);
}

.done-time.muted {
  font-size: var(--fs-lg);
  color: var(--c-text-3);
}

.done-note {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.break-box {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.break-time {
  font-family: var(--font-mono);
  font-size: 26px;
  color: var(--c-primary-ink);
}

.error {
  margin: 0;
  padding-top: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-danger-ink);
}
</style>
