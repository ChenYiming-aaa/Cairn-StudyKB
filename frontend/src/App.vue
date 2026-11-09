<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage } from './api/client'
import IngestPanel from './components/IngestPanel.vue'
import Pomodoro from './components/Pomodoro.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import { useTimer } from './composables/useTimer'
import { useToast } from './composables/useToast'
import { useUi } from './composables/useUi'
import { clock } from './utils/format'

const router = useRouter()
const { toasts, error: toastError, ok: toastOk, info: toastInfo, dismiss } = useToast()
const {
  pasteOpen, openPaste, closePaste, requestRefresh, openItem,
  // T5.7：环境自检结果在顶栏与引导页之间共用一份
  envBlocking, setupDismissed, loadEnv,
  // T6.5：设置窗口（模态）由顶栏齿轮打开，状态在 useUi 里共享
  openSettings,
} = useUi()
// 顶栏迷你计时器（T5.3）：状态在 useTimer 单例里，和番茄钟面板共用同一个计时
const { isActive, isRunning, remainingSeconds, openPanel, restore, beacon } = useTimer()

const backend = ref('checking')
// 静态演示版（github.io）：数据是抓下来的 fixture，生成类操作会返回 DEMO_OFFLINE。
// 正式构建里 VITE_DEMO 未设，这个常量恒为 false，整块提示被摇掉。
const isDemo = import.meta.env.VITE_DEMO === '1'
// 恢复入口：`visibilitychange` 会临时挂监听，保存引用以便卸载时摘掉
let onVisible = null

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
  const onSetup = router.currentRoute.value.path === '/setup'
  if (!onSetup && envBlocking.value.length && !setupDismissed.value) {
    router.push('/setup')
  }

  // T5.2：刷新/重启后把进行中的那一轮接回来
  await restore()

  // 从后台切回来时用服务端状态对齐一次（系统休眠、长时间挂起会让本地时钟松）
  onVisible = () => {
    if (document.visibilityState === 'visible') restore()
  }
  document.addEventListener('visibilitychange', onVisible)
  window.addEventListener('beforeunload', beacon)
})

onBeforeUnmount(() => {
  if (onVisible) document.removeEventListener('visibilitychange', onVisible)
  window.removeEventListener('beforeunload', beacon)
})

function onCreated(result) {
  closePaste()
  requestRefresh()
  toastOk(result.duplicated ? `内容已存在，已定位到「${result.title}」` : `已加入「${result.title}」`)
}

/** 链接已在库里：**不关面板**，面板会切成完成态让用户自己点「去看看」 */
function onExisting(itemId) {
  requestRefresh()
  toastInfo(`该链接已在知识库中（条目 #${itemId}）`)
}

/** 网页抓取 / 视频转录落库完成：刷新列表，但**不关面板**——让用户看到「已入库」再自己关 */
function onIngested() {
  requestRefresh()
  toastOk('采集完成，已加入知识库')
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
      <nav class="nav">
        <router-link to="/" class="nav-item" exact-active-class="on">知识库</router-link>
        <router-link to="/dashboard" class="nav-item" active-class="on">仪表盘</router-link>
        <router-link to="/ask" class="nav-item" active-class="on">检索问答</router-link>
        <router-link to="/pages" class="nav-item" active-class="on">学习页</router-link>
        <router-link to="/practice" class="nav-item" active-class="on">练习</router-link>
        <router-link to="/review" class="nav-item" active-class="on">复习</router-link>
        <router-link to="/tasks" class="nav-item" active-class="on">任务</router-link>
      </nav>
      <span class="conn" :class="backend" :title="backend === 'ok' ? '后端已连接' : '后端未连接'">
        <i class="dot" />
        {{ backend === 'ok' ? '已连接' : backend === 'down' ? '未连接' : '连接中' }}
      </span>
      <div class="topbar-spacer" />
      <!-- 环境待配置（T5.7）：只在缺 Key / 缺 ffmpeg 时出现，配好就消失 -->
      <button
        v-if="envBlocking.length"
        class="env-flag"
        type="button"
        title="有必填项还没配好，点开看清单"
        @click="router.push('/setup')"
      >
        <i class="dot" />
        环境待配置
      </button>
      <!-- 迷你计时器（T5.3）：任何页面都能看到剩余时间，点一下打开番茄钟面板 -->
      <button v-if="isActive" class="mini-timer" type="button" @click="openPanel()">
        <i class="mini-dot" :class="{ paused: !isRunning }" />
        <span class="mini-clock">{{ clock(remainingSeconds) }}</span>
      </button>
      <button v-else class="btn btn-sm btn-ghost" type="button" @click="openPanel()">专注</button>
      <!-- 设置入口（T6.5）：模态窗口，不新增路由 -->
      <button
        class="btn btn-sm btn-ghost gear"
        type="button"
        title="设置：模型、外观"
        aria-label="设置"
        @click="openSettings()"
      >
        <span aria-hidden="true">⚙</span>
      </button>
      <button class="btn btn-primary" type="button" @click="openPaste()">＋ 采集内容</button>
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
      <span>页面用的是预置样例数据（真跑一遍整理/问答/出题后抓取的）。整理、采集、出题、问答需要本地后端。</span>
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
  color: var(--c-primary);
}

.conn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.conn.ok {
  color: var(--c-success);
}

.conn.down {
  color: var(--c-danger);
}

/* 环境待配置：用警示色但保持低饱和，别把顶栏变成报警灯 */
.env-flag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-right: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: 1px solid #ecd9b8;
  border-radius: var(--radius-sm);
  background: #fbf1e2;
  color: var(--c-warning);
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
  color: var(--c-primary);
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
  background: #fbf1e2;
  border-top: 1px solid #ecd9b8;
  color: var(--c-warning);
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
  color: var(--c-primary);
  text-decoration: none;
  border-bottom: 1px solid currentColor;
}
</style>
