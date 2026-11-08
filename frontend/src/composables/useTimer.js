/**
 * 番茄钟状态（T5.1 / T5.2）——**模块级单例**，所以顶栏迷你计时器、番茄钟面板、
 * 条目详情页看到的是同一个计时，切换路由不会各算一套。
 *
 * 三条硬约束（M5 §1 / §6.1）：
 * 1. **只存时间点，不累加计数**。`elapsed = 服务端已结算时长 + (now - 本段锚点)`，
 *    `setInterval` 只负责触发重算，后台标签页掉帧只会让画面晚刷新，不会少算时间。
 * 2. **刷新/重启能恢复**：挂载时 `GET /api/session/current`，服务端算好 `elapsed_seconds`
 *    交给前端当新锚点，所以刷新前后同一时刻的剩余时间是同一个数。
 * 3. **强杀不丢时长**：running 时每 15 秒心跳一次（服务端卷账 + 重置锚点），
 *    闭窗前再用 `sendBeacon` 补一次（异步 fetch 会被杀掉）。
 *
 * 到点不在前端「自己结束」：先 `pause` 把时长冻住，再弹「写一句笔记」，
 * 用户保存时才 `finish`。这样走开十分钟也不会把 25 分钟记成 35 分钟。
 */
import { computed, ref, watch } from 'vue'

import { api, apiBase, friendlyMessage } from '../api/client'

const HEARTBEAT_MS = 15000
export const PRESETS = [15, 25, 50]         // 专注时长预设（分钟）
export const BREAK_SECONDS = 300            // 结束后默认休息 5 分钟（纯前端，不落库）

const session = ref(null)                   // 服务端返回的 session（含 status/planned/target）
const baseSeconds = ref(0)                  // 已结算时长
const anchorMs = ref(Date.now())            // 本段锚点（本地时钟）
const clock = ref(Date.now())               // 每秒推进一次，唯一的重算触发器
const panelOpen = ref(false)
const noteOpen = ref(false)                 // 到点/提前完成后的「写一句笔记」
const error = ref('')
const lastFinished = ref(null)              // 刚结束的一轮，用于面板上的结果卡

let tickTimer = null
let beatTimer = null

const isActive = computed(() => Boolean(session.value))
const isRunning = computed(() => session.value?.status === 'running')
const isPaused = computed(() => session.value?.status === 'paused')
const plannedSeconds = computed(() => Number(session.value?.planned_seconds || 0))

/** 有效秒数（暂停不计）。与后端 `sessions.elapsed_seconds` 同一套公式。 */
const elapsedSeconds = computed(() => {
  if (!isRunning.value) return baseSeconds.value
  const delta = Math.max(0, (clock.value - anchorMs.value) / 1000)
  return baseSeconds.value + delta
})

const remainingSeconds = computed(() =>
  Math.max(0, plannedSeconds.value - Math.floor(elapsedSeconds.value))
)

const progress = computed(() =>
  plannedSeconds.value ? Math.min(1, elapsedSeconds.value / plannedSeconds.value) : 0
)

/** 服务端快照 → 本地状态。`elapsed_seconds` 是服务端此刻算好的有效时长。 */
function adopt(payload) {
  session.value = payload
  baseSeconds.value = Number(payload.elapsed_seconds ?? payload.duration_seconds ?? 0)
  anchorMs.value = Date.now()
  clock.value = Date.now()
  ensureTimers()
}

function clear() {
  session.value = null
  baseSeconds.value = 0
  noteOpen.value = false
  stopTimers()
}

function ensureTimers() {
  if (session.value && !tickTimer) {
    tickTimer = setInterval(() => {
      clock.value = Date.now()
    }, 1000)
  }
  if (isRunning.value && !beatTimer) {
    beatTimer = setInterval(sendHeartbeat, HEARTBEAT_MS)
  }
  if (!isRunning.value && beatTimer) {
    clearInterval(beatTimer)
    beatTimer = null
  }
}

function stopTimers() {
  if (tickTimer) clearInterval(tickTimer)
  if (beatTimer) clearInterval(beatTimer)
  tickTimer = null
  beatTimer = null
}

/** 心跳：服务端会把已过时间卷进 duration_seconds 并把锚点挪到当下 */
async function sendHeartbeat() {
  const id = session.value?.id
  if (!id || document.hidden) return
  try {
    const fresh = await api.sessionHeartbeat(id)
    if (fresh?.status) adopt(fresh)
  } catch {
    // 心跳失败不打扰用户：下一次会重试，真的丢了也只是少记一个 15 秒
  }
}

/** 恢复：刷新、切回窗口、应用重启后都走这一个入口 */
async function restore() {
  try {
    const data = await api.sessionCurrent()
    if (data?.session) {
      adopt(data.session)
      if (data.session.status === 'running') noteOpen.value = false
    }
    return data?.session || null
  } catch {
    return null
  }
}

/**
 * 开始一轮。返回 session；失败返回 null 并把原因放 `error`。
 * 409（已有计时在跑）时会顺手接管那一个——用户看不到「已经有一个计时」这种废话错误。
 */
async function start(payload) {
  error.value = ''
  lastFinished.value = null
  noteOpen.value = false
  try {
    const created = await api.sessionStart(payload)
    adopt(created)
    panelOpen.value = true
    return created
  } catch (err) {
    if (err?.code === 'SESSION_ALREADY_RUNNING') {
      const existing = await restore()
      panelOpen.value = true
      if (existing) return existing
    }
    error.value = friendlyMessage(err)
    return null
  }
}

async function run(action, payload) {
  const id = session.value?.id
  if (!id) return null
  error.value = ''
  try {
    const fresh = await api.sessionAction(id, action, payload)
    adopt(fresh)
    return fresh
  } catch (err) {
    // 状态冲突（比如另一处已经结束了这一轮）：重新拉一次真实状态，别让界面卡在假象上
    if (err?.code === 'SESSION_STATE' || err?.code === 'SESSION_NOT_FOUND') await restore()
    error.value = friendlyMessage(err)
    return null
  }
}

const pause = () => run('pause')
const resume = () => run('resume')

/** 结束并落库；`note` 就是「写一句笔记」，可空 */
async function finish(note = '') {
  const done = await run('finish', { note: note || null })
  if (done) {
    lastFinished.value = done
    noteOpen.value = false
    clear()
    panelOpen.value = true          // 面板留着显示结果卡，用户自己关
  }
  return done
}

async function abandon() {
  const done = await run('abandon')
  if (done) {
    lastFinished.value = { ...done, abandoned: true }
    noteOpen.value = false
    clear()
    panelOpen.value = true
  }
  return done
}

/** 提前完成：先暂停把时长冻住，再把「写一句笔记」交给用户（可跳过） */
async function requestNote() {
  if (isRunning.value) await pause()
  noteOpen.value = true
  return session.value
}

/** 闭窗兜底：`sendBeacon` 只能发 POST，所以心跳端点特意做成 POST */
function beacon() {
  const id = session.value?.id
  if (!id || !isRunning.value) return
  try {
    navigator.sendBeacon?.(`${apiBase()}/api/session/${id}/heartbeat`)
  } catch {
    // 浏览器不支持就算了，15 秒心跳已经覆盖大部分情况
  }
}

// 到点：先冻住时长，再要笔记。这个 watch 放模块级，所以在任何页面都生效。
watch(remainingSeconds, (value) => {
  if (value === 0 && isRunning.value && !noteOpen.value) {
    noteOpen.value = true
    pause()
  }
})

export function useTimer() {
  return {
    session,
    error,
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
    start,
    restore,
    pause,
    resume,
    finish,
    requestNote,
    abandon,
    beacon,
    openPanel: () => {
      panelOpen.value = true
    },
    closePanel: () => {
      panelOpen.value = false
      lastFinished.value = null
    },
    dismissNote: () => {
      noteOpen.value = false
    },
  }
}
