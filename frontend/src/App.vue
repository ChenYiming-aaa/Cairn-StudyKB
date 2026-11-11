<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, friendlyMessage } from './api/client'
import IngestPanel from './components/IngestPanel.vue'
import Pomodoro from './components/Pomodoro.vue'
import RailToggle from './components/RailToggle.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import { installResponsiveLayout, useLayout } from './composables/useLayout'
import { useSettings } from './composables/useSettings'
import { useTasks } from './composables/useTasks'
import { useTheme } from './composables/useTheme'
import { useTimer } from './composables/useTimer'
import { useToast } from './composables/useToast'
import { useUi } from './composables/useUi'
import { clock } from './utils/format'

const router = useRouter()
const route = useRoute()
const { toasts, error: toastError, ok: toastOk, info: toastInfo, dismiss } = useToast()
const {
  pasteOpen, openPaste, closePaste, requestRefresh, openItem, refreshTick,
  // T5.7：环境自检结果在顶栏与引导页之间共用一份
  envBlocking, setupDismissed, loadEnv,
  // T6.5：设置窗口（模态）由顶栏齿轮打开，状态在 useUi 里共享
  openSettings,
} = useUi()
// 顶栏迷你计时器（T5.3）：状态在 useTimer 单例里，和番茄钟面板共用同一个计时
const { isActive, isRunning, remainingSeconds, openPanel, restore, beacon } = useTimer()
// 主题（T6.7）：localStorage 已经在 theme-boot.js 里上过一次，这里用后端的真源对齐
const { load: loadSettings } = useSettings()
const { adopt: adoptAppearance } = useTheme()
// T7.0：Ctrl+B 收左栏，Ctrl+Shift+B 收条目列表（T7.2 起列表按钮在顶栏）
const { toggle, isPanelCollapsed, setPanel } = useLayout()
// T7.4：任务挪到右侧图标组，角标是「未完成」（排队 + 进行中）
const { activeTasks, refreshTasks } = useTasks()

const backend = ref('checking')
// 「列表」折叠按钮只在有条目列表的页面出现（知识库），别的页面按它没意义
const hasList = computed(() => route.path === '/')
// 静态演示版（github.io）：数据是抓下来的 fixture，生成类操作会返回 DEMO_OFFLINE。
// 正式构建里 VITE_DEMO 未设，这个常量恒为 false，整块提示被摇掉。
const isDemo = import.meta.env.VITE_DEMO === '1'
// 恢复入口：`visibilitychange` 会临时挂监听，保存引用以便卸载时摘掉
let onVisible = null
let uninstallResponsive = null

/** 输入框里按 Ctrl+B 是「加粗」之类的编辑器语义，不该折叠侧栏 */
function isTyping(target) {
  if (!target || !target.tagName) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

function onKeydown(event) {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return
  if (isTyping(event.target)) return
  const key = String(event.key).toLowerCase()
  if (key === 'b') {
    event.preventDefault()
    toggle(event.shiftKey ? 'list' : 'sidebar')
    return
  }
  // T7.3：问答历史的入口键统一成 Ctrl+H（和列表/左栏一样是「收展一个侧栏」）
  if (key === 'h' && route.path === '/ask') {
    event.preventDefault()
    setPanel('chat', !isPanelCollapsed('chat'))
  }
}

onMounted(async () => {
  try {
    await api.health()
    backend.value = 'ok'
  } catch (err) {
    backend.value = 'down'
    toastError(friendlyMessage(err))
  }

  // T5.7：缺 Key / 缺 ffmpeg 时把用户送到引导页。只在**本机从没配过**时自动跳一次，
  // 点过「稍后再说」就不再打扰——顶栏那个黄色状态点会一直留着，随时能回去。
  await loadEnv()
  // 外观（主题/明暗/字号）的真源在 settings.json：首次启动或换机器时以它为准
  await loadSettings()
  adoptAppearance()
  const onSetup = router.currentRoute.value.path === '/setup'
  if (!onSetup && envBlocking.value.length && !setupDismissed.value) {
    router.push('/setup')
  }

  // T5.2：刷新/重启后把进行中的那一轮接回来
  await restore()

  // T7.4：任务角标先对齐一次，之后靠 refreshTick / 切页 / 有未完成时的轮询更新
  refreshTasks()

  // 从后台切回来时用服务端状态对齐一次（系统休眠、长时间挂起会让本地时钟松）
  onVisible = () => {
    if (document.visibilityState === 'visible') restore()
  }
  document.addEventListener('visibilitychange', onVisible)
  window.addEventListener('beforeunload', beacon)
  window.addEventListener('keydown', onKeydown)
  // 窗口 < 1200 自动收左栏（用户自己动过就不再抢方向盘）
  uninstallResponsive = installResponsiveLayout()
})

onBeforeUnmount(() => {
  if (onVisible) document.removeEventListener('visibilitychange', onVisible)
  window.removeEventListener('beforeunload', beacon)
  window.removeEventListener('keydown', onKeydown)
  if (uninstallResponsive) uninstallResponsive()
})

// 采集/整理落库、切页之后都可能有新任务进来，这两种时机顺手对齐角标
watch(refreshTick, refreshTasks)
watch(() => route.path, refreshTasks)

function onCreated(result) {
  closePaste()
  requestRefresh()
  toastOk(result.duplicated ? `这条已经在知识库里了，已帮你定位到「${result.title}」` : `「${result.title}」已存进知识库`)
}

/** 链接已在库里：**不关面板**，面板会切成完成态让用户自己点「去看看」 */
function onExisting() {
  requestRefresh()
  toastInfo('这条已经在知识库里了，已帮你定位到它')
}

/** 网页抓取 / 视频转录落库完成：刷新列表，但**不关面板**——让用户看到「已存进」再自己关 */
function onIngested() {
  requestRefresh()
  toastOk('已存进知识库')
}

/** 「去看看」：关面板 → 切到知识库 → 选中刚入库的条目 */
function onOpen(itemId) {
  closePaste()
  requestRefresh()
  if (!itemId) return
  router.push('/')
  openItem(itemId)
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <img class="brand-mark" src="/logo.svg" alt="" width="22" height="22" />
        Cairn
        <small>个人知识库</small>
      </div>
      <!-- 左栏折叠（T7.0）：和左栏里的窄条按钮是同一个状态 -->
      <RailToggle target="sidebar" />
      <!-- 列表折叠（T7.2）：只在知识库页有意义；收起后列宽 0，这是它的恢复入口 -->
      <RailToggle v-if="hasList" target="list" />
      <nav class="nav">
        <router-link to="/" class="nav-item" exact-active-class="on">知识库</router-link>
        <router-link to="/ask" class="nav-item" active-class="on">检索</router-link>
        <router-link to="/pages" class="nav-item" active-class="on">学习</router-link>
        <router-link to="/practice" class="nav-item" active-class="on">练习</router-link>
        <router-link to="/review" class="nav-item" active-class="on">复习</router-link>
      </nav>
      <div class="topbar-spacer" />
      <!-- 待配置（T5.7）：只在缺 Key / 缺 ffmpeg 时出现，配好就消失 -->
      <button
        v-if="envBlocking.length"
        class="env-flag"
        type="button"
        title="还有一项没配好，点了去补"
        @click="router.push('/setup')"
      >
        <i class="dot" />
        还差一步
      </button>
      <!-- 右侧顺序固定（T7.4）：连接状态 · 任务 · 专注 · 采集 · 齿轮 -->
      <span class="conn" :class="backend" :title="backend === 'ok' ? '后端已连接' : '后端未连接'">
        <i class="dot" />
        <span class="conn-text">{{ backend === 'ok' ? '已连接' : backend === 'down' ? '未连接' : '连接中' }}</span>
      </span>
      <!-- 任务（T7.4）：从导航挪过来，角标是未完成数量；仪表盘入口在知识库的「今日」条 -->
      <button
        class="btn btn-sm btn-ghost task-btn"
        type="button"
        title="任务中心：采集和整理跑到哪了"
        @click="router.push('/tasks')"
      >
        任务
        <span v-if="activeTasks" class="task-count">{{ activeTasks }}</span>
      </button>
      <!-- 迷你计时器（T5.3）：任何页面都能看到剩余时间，点一下打开番茄钟面板 -->
      <button v-if="isActive" class="mini-timer" type="button" @click="openPanel()">
        <i class="mini-dot" :class="{ paused: !isRunning }" />
        <span class="mini-clock">{{ clock(remainingSeconds) }}</span>
      </button>
      <button v-else class="btn btn-sm btn-ghost" type="button" @click="openPanel()">专注</button>
      <button class="btn btn-primary" type="button" @click="openPaste()">＋ 采集内容</button>
      <!-- 设置入口（T6.5）：模态窗口，不新增路由；齿轮固定放最后 -->
      <button
        class="btn btn-sm btn-ghost gear"
        type="button"
        title="设置：模型、外观、下载、关于"
        aria-label="设置"
        @click="openSettings()"
      >
        <span aria-hidden="true">⚙</span>
      </button>
    </header>

    <router-view />

    <Pomodoro />
    <SettingsDialog />

    <IngestPanel
      :open="pasteOpen"
      @close="closePaste()"
      @created="onCreated"
      @existing="onExisting"
      @ingested="onIngested"
      @open="onOpen"
    />

    <div class="toast-stack">
      <div
        v-for="item in toasts"
        :key="item.id"
        class="toast"
        :class="item.kind"
        @click="dismiss(item.id)"
      >
        {{ item.message }}
      </div>
    </div>

    <!-- 静态演示横幅：常驻，不参与布局，避免遮挡内容 -->
    <div v-if="isDemo" class="demo-bar">
      <b>演示模式</b>
      <span>这里的内容是预先准备好的，不能新增或生成。装桌面版即可完整使用。</span>
      <a href="https://github.com/ChenYiming-aaa/Cairn-StudyKB/releases" target="_blank" rel="noreferrer">
        下载桌面版
      </a>
    </div>
  </div>
</template>

<style scoped>
.nav {
  display: flex;
  gap: var(--space-1);
  margin-left: var(--space-4);
  /* T7.4：导航永不换行 —— 1280 与 1024 都要保持一行，宁可收字距 */
  flex: none;
  white-space: nowrap;
}

.nav-item {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  text-decoration: none;
}

.nav-item:hover {
  background: var(--c-bg-2);
}

.nav-item.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.conn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.conn.ok {
  color: var(--c-success-ink);
}

.conn.down {
  color: var(--c-danger-ink);
}

/* 任务角标（T7.4）：未完成数量。用主色实心的小胶囊，和左侧「环境待配置」的黄点区分开 */
.task-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.task-count {
  min-width: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--c-primary);
  color: var(--c-on-primary);
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* 1024 宽（窗口下限 960）：导航仍要一行，先把不承载信息的字收掉 */
@media (max-width: 1100px) {
  .topbar {
    gap: var(--space-2);
    padding: 0 var(--space-4);
  }

  .brand small {
    display: none;
  }

  .conn-text {
    display: none;
  }

  .nav {
    margin-left: var(--space-2);
  }

  .nav-item {
    padding-left: var(--space-2);
    padding-right: var(--space-2);
  }
}

/* 环境待配置：用警示色但保持低饱和，别把顶栏变成报警灯 */
.env-flag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-right: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--c-warning-border);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.env-flag .dot {
  background: var(--c-warning);
}

.env-flag:hover {
  border-color: var(--c-warning);
}

/* 齿轮：图标按钮，视觉重量要低于「采集内容」，所以用 ghost */
.gear {
  padding: var(--space-1) var(--space-2);
  font-size: var(--fs-lg);
  line-height: 1;
  color: var(--c-text-2);
}

.mini-timer {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-right: var(--space-2);
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--c-primary);
  border-radius: var(--radius-sm);
  background: var(--c-primary-soft);
  cursor: pointer;
}

.mini-clock {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  color: var(--c-primary-ink);
}

.mini-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-primary);
  animation: breathe 1.6s ease-in-out infinite;
}

.mini-dot.paused {
  background: var(--c-text-3);
  animation: none;
}

@keyframes breathe {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.25;
  }
}

.toast-stack {
  position: fixed;
  right: var(--space-6);
  bottom: var(--space-6);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  z-index: 60;
}

.toast {
  max-width: 380px;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  border: 1px solid var(--c-border);
  border-left-width: 3px;
  box-shadow: var(--shadow-md);
  font-size: var(--fs-sm);
  cursor: pointer;
  animation: slide-in 0.18s ease;
}

.toast.ok {
  border-left-color: var(--c-success);
}

.toast.error {
  border-left-color: var(--c-danger);
}

.toast.info {
  border-left-color: var(--c-primary);
}

@keyframes slide-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

/* 演示模式横幅：贴底部一条，不进布局，避免把界面挤变形 */
.demo-bar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 55;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: 6px var(--space-4);
  background: var(--c-warning-soft);
  border-top: 1px solid var(--c-warning-border);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
  line-height: 1.4;
  text-align: center;
}

.demo-bar b {
  font-weight: 600;
}

.demo-bar span {
  color: var(--c-text-2);
}

.demo-bar a {
  color: var(--c-primary-ink);
  text-decoration: none;
  border-bottom: 1px solid currentColor;
}
</style>
