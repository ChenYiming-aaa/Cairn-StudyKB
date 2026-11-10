/**
 * 更新器状态（T8.5）：**模块级单例**，不是每个组件一份。
 *
 * 为什么不做成组件内的 ref：设置窗口切 tab 会卸载「关于」页，关窗口更是整块卸载。
 * 下载 170 MB 的中途被卸载掉，主进程还在下，界面回来却显示「未检查」—— 用户会以为断了。
 * 状态挂在模块上，下载与进度就跟着 **主进程** 的生命周期走，与窗口无关。
 *
 * 所有网络动作都在主进程（`desktop/updater.js`），这里只发 IPC 与展示。
 * `window.cairn` 不存在时（浏览器里跑 vite、静态演示页）状态是 `unavailable`，
 * 界面如实写「桌面版才能检查更新」，不放一个点了没反应的按钮。
 */
import { computed, ref } from 'vue'

const bridge = typeof window !== 'undefined' ? window.cairn : null
const canUpdate = Boolean(bridge && bridge.update)

// unavailable | idle | checking | latest | available | downloading | ready | error
const state = ref(canUpdate ? 'idle' : 'unavailable')
const result = ref(null)          // check() 的完整返回（latest / notes / size / htmlUrl）
const progress = ref({ got: 0, total: 0, pct: 0 })
const error = ref(null)           // { message, manualUrl, code }
const verify = ref('')            // 下载后拿到的校验方式：'sha256' | 'size'

const current = computed(() => result.value?.current || bridge?.app?.version || '')
const latest = computed(() => result.value?.latest || '')
// Release body 是 Markdown，这里不做完整渲染（20 行说明不值得引一个渲染器），
// 只把标题井号和列表符号压成人能读的样子 —— 否则界面上直接露出 `### 本次更新`。
const notes = computed(() => String(result.value?.notes || '')
  .split(/\r?\n/)
  .map((line) => line.replace(/^#{1,6}\s*/, '').replace(/^[-*]\s+/, '· ').trimEnd())
  .join('\n')
  .trim())
const manualUrl = computed(
  () => error.value?.manualUrl || result.value?.htmlUrl || 'https://github.com/ChenYiming-aaa/Cairn-StudyKB/releases',
)

let listening = false

/** 进度事件只订一次：多个组件同时挂载时不会重复累加 */
function listen() {
  if (listening || !canUpdate) return
  listening = true
  bridge.update.onProgress((p) => {
    if (state.value !== 'downloading') return
    progress.value = p
  })
}

function fmtBytes(n) {
  const size = Number(n) || 0
  if (size <= 0) return '—'
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`
  return `${(size / (1024 * 1024)).toFixed(0)} MB`
}

async function check() {
  if (!canUpdate) return
  listen()
  state.value = 'checking'
  error.value = null
  const r = await bridge.update.check()
  if (!r || !r.ok) {
    state.value = 'error'
    error.value = { message: r?.message || '检查更新失败。', manualUrl: r?.manualUrl, code: r?.code || '' }
    return
  }
  result.value = r
  state.value = r.hasUpdate ? 'available' : 'latest'
}

async function download() {
  if (!canUpdate) return
  listen()
  state.value = 'downloading'
  progress.value = { got: 0, total: result.value?.size || 0, pct: 0 }
  error.value = null
  const r = await bridge.update.download()
  if (r && r.ok) {
    verify.value = r.verify || 'size'
    state.value = 'ready'
    return
  }
  // 取消不算错误：回到「可下载」，让用户看见自己点的那一下生效了
  if (r && r.code === 'CANCELLED') {
    state.value = 'available'
    progress.value = { got: 0, total: result.value?.size || 0, pct: 0 }
    return
  }
  state.value = 'error'
  error.value = { message: r?.message || '下载失败。', manualUrl: result.value?.htmlUrl, code: r?.code || '' }
}

async function cancel() {
  if (!canUpdate) return
  await bridge.update.cancel()
}

async function install() {
  if (!canUpdate) return
  const r = await bridge.update.install()
  if (r && r.ok) return                     // 主进程会退出，界面不必再变
  state.value = 'error'
  error.value = { message: r?.message || '打不开安装程序。', manualUrl: result.value?.htmlUrl, code: r?.code || '' }
}

/** 手动下载：交给系统浏览器（主进程的 windowOpenHandler 会把外链丢出去） */
function openManual() {
  window.open(manualUrl.value, '_blank', 'noopener')
}

export function useUpdater() {
  return {
    canUpdate,
    state,
    result,
    progress,
    error,
    verify,
    current,
    latest,
    notes,
    manualUrl,
    fmtBytes,
    check,
    download,
    cancel,
    install,
    openManual,
  }
}
