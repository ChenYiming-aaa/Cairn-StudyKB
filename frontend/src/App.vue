<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, friendlyMessage } from './api/client'
import IngestPanel from './components/IngestPanel.vue'
import RailToggle from './components/RailToggle.vue'
import SettingsDialog from './components/SettingsDialog.vue'
import Icon from './ui/Icon.vue'
import { installResponsiveLayout, useLayout } from './composables/useLayout'
import { useComponentInstall } from './composables/useComponentInstall'
import { useSettings } from './composables/useSettings'
import { useTasks } from './composables/useTasks'
import { useTheme } from './composables/useTheme'
import { useToast } from './composables/useToast'
import { useUi } from './composables/useUi'

const router = useRouter()
const route = useRoute()
const { toasts, error: toastError, ok: toastOk, info: toastInfo, dismiss } = useToast()
const {
  pasteOpen, pasteSeed, openPaste, closePaste, requestRefresh, openItem, refreshTick,
  // T5.7：环境自检结果在顶栏与引导页之间共用一份
  envBlocking, setupDismissed, loadEnv,
  // T6.5：设置窗口（模态）由顶栏齿轮打开，状态在 useUi 里共享
  openSettings,
} = useUi()
// 主题（T6.7）：localStorage 已经在 theme-boot.js 里上过一次，这里用后端的真源对齐
const { load: loadSettings } = useSettings()
const { adopt: adoptAppearance } = useTheme()
// T7.0：Ctrl+B 收左栏，Ctrl+Shift+B 收条目列表（T7.2 起列表按钮在顶栏）
const { toggle, isPanelCollapsed, setPanel } = useLayout()
// T7.4：任务挪到右侧图标组，角标是「未完成」（排队 + 进行中）
const { activeTasks, refreshTasks } = useTasks()
// 6-4：组件装完的全局通知（只在下载中有轮询）
const { watchNow } = useComponentInstall()

const backend = ref('checking')
const toastStack = ref(null)
// 「列表」折叠按钮只在有条目列表的页面出现（知识库），别的页面按它没意义
const hasList = computed(() => route.path === '/')
// 静态演示版（github.io）：数据是抓下来的 fixture，生成类操作会返回 DEMO_OFFLINE。
// 正式构建里 VITE_DEMO 未设，这个常量恒为 false，整块提示被摇掉。
const isDemo = import.meta.env.VITE_DEMO === '1'
let uninstallResponsive = null

/** 顶栏连接状态的可读文案（与图标一起构成「不只是颜色」的状态表达） */
const connText = computed(() =>
  backend.value === 'ok' ? '已连接' : backend.value === 'down' ? '未连接' : '连接中'
)

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

  // T7.4：任务角标先对齐一次，之后靠 refreshTick / 切页 / 有未完成时的轮询更新
  refreshTasks()

  // 6-4：如果上一轮有组件没下完（或重启前正在装），从这里接管轮询；
  // 没在装就只问一次，不常驻
  watchNow()

  window.addEventListener('keydown', onKeydown)
  // 窗口 < 1200 自动收左栏（用户自己动过就不再抢方向盘）
  uninstallResponsive = installResponsiveLayout()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (uninstallResponsive) uninstallResponsive()
})

// 采集/整理落库、切页之后都可能有新任务进来，这两种时机顺手对齐角标
watch(refreshTick, refreshTasks)
watch(() => route.path, refreshTasks)

// 有提示才把通知区放进顶层，最后一条消失就收起来：
// 常开的 popover 会一直占着顶层，且空容器在顶层没有意义
watch(
  () => toasts.value.length,
  (count) => {
    const node = toastStack.value
    if (!node) return
    if (count && !node.matches(':popover-open')) node.showPopover()
    else if (!count && node.matches(':popover-open')) node.hidePopover()
  }
)

/** 提示的图标：与文案一起表达结果，不让颜色单独扛 */
const TOAST_ICON = { ok: 'check', error: 'alert', info: 'info' }

function onCreated(result) {
  closePaste()
  requestRefresh()
  toastOk(result.duplicated ? `这条已经在知识库里了，已帮你定位到「${result.title}」` : `「${result.title}」已存进知识库`)
  // 存完直接把用户送到那一条：以前只弹一句就关面板，用户还得自己回列表里翻。
  // 文件与链接两条路都有「去看看」，只有粘贴这条路没有 —— 现在三处一致。
  if (!result || !result.id) return
  router.push('/')
  openItem(result.id)
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
        <span class="brand-name">Cairn</span>
        <small>个人知识库</small>
      </div>

      <!-- 左栏折叠（T7.0）：和左栏里的窄条按钮是同一个状态 -->
      <RailToggle target="sidebar" />
      <!-- 列表折叠（T7.2）：只在知识库页有意义；收起后列宽 0，这是它的恢复入口 -->
      <RailToggle v-if="hasList" target="list" />

      <nav class="nav" aria-label="主导航">
        <router-link to="/" class="nav-item" exact-active-class="on">
          <Icon name="library" :size="16" />
          <span>知识库</span>
        </router-link>
        <router-link to="/ask" class="nav-item" active-class="on">
          <Icon name="search" :size="16" />
          <span>检索</span>
        </router-link>
        <!-- 「导出」而不是「学习」：这一页做的是把几条内容装订成一份离线文件，
             不是「在这里学」——叫「学习」会让用户点进来找一个不存在的学习流程。
             页面标题仍是「学习页」，那是产物名（文案规范 §1 术语表） -->
        <router-link to="/pages" class="nav-item" active-class="on">
          <Icon name="export" :size="16" />
          <span>导出</span>
        </router-link>
        <router-link to="/practice" class="nav-item" active-class="on">
          <Icon name="practice" :size="16" />
          <span>练习</span>
        </router-link>
        <router-link to="/review" class="nav-item" active-class="on">
          <Icon name="review" :size="16" />
          <span>复习</span>
        </router-link>
        <!-- 试用（只在演示站注册）：用自己的 Key 真跑一遍整理 / 追问 / 出题 -->
        <router-link v-if="isDemo" to="/try" class="nav-item" active-class="on">
          <Icon name="play" :size="16" />
          <span>试用</span>
        </router-link>
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
        <Icon name="alert" :size="16" />
        还差一步
      </button>

      <!-- 右侧顺序固定（T7.4）：连接状态 · 任务 · 采集 · 齿轮
           （「专注」计时器 2026-11-17 移除，见 docs/dev/功能价值审计-2026-11-17.md） -->
      <span class="conn" :class="backend" :title="backend === 'ok' ? '服务已连接' : '服务未连接'">
        <Icon name="signal" :size="16" />
        <span class="conn-text">{{ connText }}</span>
      </span>

      <!-- 任务（T7.4）：从导航挪过来，角标是未完成数量；仪表盘入口在知识库的「今日」条 -->
      <button
        class="nav-action"
        type="button"
        title="任务中心：采集和整理跑到哪了"
        aria-label="任务"
        @click="router.push('/tasks')"
      >
        <Icon name="tasks" :size="16" />
        <span>任务</span>
        <span v-if="activeTasks" class="task-count" :aria-label="`${activeTasks} 项未完成`">
          {{ activeTasks }}
        </span>
      </button>

      <!-- aria-label 与可见文字一致：窄窗（<1180）会把文字收掉，没有它按钮就没有可访问名称 -->
      <button
        class="nav-action nav-action-primary"
        type="button"
        aria-label="采集内容"
        @click="openPaste()"
      >
        <Icon name="plus" :size="16" />
        <span>采集内容</span>
      </button>

      <!-- 设置入口（T6.5）：模态窗口，不新增路由；齿轮固定放最后 -->
      <button
        class="nav-icon"
        type="button"
        title="设置：模型、外观、下载、关于"
        aria-label="设置"
        @click="openSettings()"
      >
        <Icon name="settings" :size="20" />
      </button>
    </header>

    <router-view />

    <SettingsDialog />

    <IngestPanel
      :open="pasteOpen"
      :seed="pasteSeed"
      @close="closePaste()"
      @created="onCreated"
      @existing="onExisting"
      @ingested="onIngested"
      @uploaded="requestRefresh"
      @open="onOpen"
    />

    <!-- 通知条：`popover="manual"` 把它放进顶层，否则会掉在模态遮罩下面（层叠上下文里 z-index
         已经管不了顶层元素了）。manual 而非 auto：点别处不该把还没读到的提示关掉。 -->
    <div
      ref="toastStack"
      class="toast-stack"
      popover="manual"
      role="region"
      aria-label="操作结果"
      aria-live="polite"
    >
      <div
        v-for="item in toasts"
        :key="item.id"
        class="toast"
        :class="item.kind"
        @click="dismiss(item.id)"
      >
        <Icon :name="TOAST_ICON[item.kind] || 'info'" :size="16" />
        <span class="toast-text">{{ item.message }}</span>
      </div>
    </div>

    <!-- 静态演示横幅：常驻，不参与布局，避免遮挡内容 -->
    <div v-if="isDemo" class="demo-bar">
      <b>演示模式</b>
      <span>这里的内容是预先准备好的，不能新增或生成。</span>
      <router-link to="/try" class="demo-cta">用自己的 Key 真跑一遍</router-link>
      <span class="demo-sep">·</span>
      <a href="https://github.com/ChenYiming-aaa/Cairn-StudyKB/releases" target="_blank" rel="noreferrer">
        下载桌面版
      </a>
    </div>
  </div>
</template>

<style scoped>
/* ── 顶栏 ──
   52px 高度不变（useLayout 与各页面的 scroll-margin 都依赖 --h-topbar）。
   层级靠「字重 + 图标 + 间距」建立，不靠加边框。 */
.topbar {
  gap: var(--space-3);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: var(--ls-title);
  color: var(--c-text-1);
}

.brand-name {
  display: block;
  line-height: 1;
}

.brand small {
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--c-text-3);
  letter-spacing: 0;
}

/* ── 导航 ── */
.nav {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: var(--space-3);
  flex: none;
  white-space: nowrap;
}

.nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--c-text-2);
  text-decoration: none;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.nav-item:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.nav-item:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* 选中态：底色 + 主色文字 + 图标一起变，不只靠颜色深浅 */
.nav-item.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

/* ── 连接状态 ── */
.conn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.conn.ok {
  color: var(--c-success-ink);
}

.conn.down {
  color: var(--c-danger-ink);
}

/* 连接中：图标轻微呼吸，表示「还在探测」而不是「已经好了」 */
.conn.checking .icon {
  animation: conn-breathe 1.6s ease-in-out infinite;
}

@keyframes conn-breathe {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.35;
  }
}

/* ── 右侧动作按钮 ── */
.nav-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-2);
  font-family: var(--font-ui);
  font-size: var(--fs-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.nav-action:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.nav-action:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* 一屏唯一的主操作 */
.nav-action-primary {
  border-color: var(--c-primary);
  background: var(--c-primary);
  color: var(--c-on-primary);
}

.nav-action-primary:hover {
  border-color: var(--c-primary-hover);
  background: var(--c-primary-hover);
  color: var(--c-on-primary);
}

.nav-action-primary:active {
  transform: translateY(1px);
}

.task-count {
  min-width: 16px;
  padding: 0 4px;
  /* 999px 而不是 8px：8px 只在两位数时"看起来像胶囊"（高度 16px 的一半），
     一旦计数变成三位数、元素被拉宽，8px 就露出上下平边；999px 在任何宽度都是胶囊 */
  border-radius: 999px;
  background: var(--c-primary);
  color: var(--c-on-primary);
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

/* 主按钮上的角标反过来用底色强调，避免两个同色块糊在一起 */
.nav-action-primary .task-count {
  background: var(--c-on-primary);
  color: var(--c-primary);
}

.nav-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-2);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.nav-icon:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.nav-icon:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* 环境待配置：用警示色但保持低饱和，别把顶栏变成报警灯 */
.env-flag {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  margin-right: var(--space-1);
  padding: 2px var(--space-2);
  border: 1px solid var(--c-warning-border);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-family: var(--font-ui);
  font-size: var(--fs-xs);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
}

.env-flag:hover {
  border-color: var(--c-warning);
}

.env-flag:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* ── 通知条 ── */
.toast-stack {
  /* popover 的 UA 默认（居中、边框、底色、内边距）全部要清掉，位置仍贴右下 */
  position: fixed;
  inset: auto var(--space-6) var(--space-6) auto;
  width: fit-content;
  max-width: min(380px, 100vw - 2 * var(--space-6));
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  overflow: visible;
  z-index: 60;
}

/* display 只在打开时给：无条件写会盖过 UA 的 `[popover]:not(:popover-open){display:none}`，
   空的通知区就会一直以 display:flex 占在那儿 */
.toast-stack:popover-open {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  max-width: 380px;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  box-shadow: var(--elev-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--c-text-1);
  cursor: pointer;
  animation: slide-in var(--dur-enter) var(--ease-out);
}

/* 结果图标分色，文字保持正文色——颜色只做辅助，不做唯一线索 */
.toast.ok .icon {
  color: var(--c-success-ink);
}

.toast.error .icon {
  color: var(--c-danger-ink);
}

.toast.info .icon {
  color: var(--c-primary-ink);
}

.toast-text {
  display: block;
  min-width: 0;
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

/* ── 演示模式横幅 ── */
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

/* 试用入口比「下载桌面版」更值得点：给它一个实心按钮的样子 */
.demo-bar a.demo-cta {
  padding: 1px var(--space-2);
  border: 1px solid var(--c-primary-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  color: var(--c-primary-ink);
  white-space: nowrap;
}

.demo-bar .demo-sep {
  color: var(--c-text-3);
}

/* ── 窄窗：先收不承载信息的字，导航保持一行 ── */
@media (max-width: 1180px) {
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

  .nav-action span:not(.task-count) {
    display: none;
  }

  .nav-action {
    padding: 0 var(--space-2);
  }
}

@media (prefers-reduced-motion: reduce) {
  .conn.checking .icon {
    animation: none;
  }

  .nav-action-primary:active {
    transform: none;
  }

  .toast {
    animation: none;
  }
}
</style>
