<script setup>
/**
 * 设置窗口（M6 T6.5）：模态，宽 880 / 高 620，左侧 4 个 tab。
 *
 * 这个文件只负责「壳」：开合、焦点陷阱、Esc、遮罩点击、tab 记忆。
 * tab 的内容在 `components/settings/*`，Part 2 会补 外观 / 下载 / 关于 三块。
 *
 * 三条无障碍底线（模态不做这三件，键盘用户就被困住了）：
 * 1. `role="dialog"` + `aria-modal` + `aria-labelledby`
 * 2. 打开时焦点进窗、Tab 在窗内循环、关闭时焦点回原处
 * 3. Esc 关闭；点遮罩关闭（点面板内部不关）
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { useSettings } from '../composables/useSettings'
import { useUi } from '../composables/useUi'
import AboutTab from './settings/AboutTab.vue'
import AppearanceTab from './settings/AppearanceTab.vue'
import ModelTab from './settings/ModelTab.vue'

const TABS = [
  { id: 'model', label: '模型', hint: '服务、Key、每个任务用谁' },
  { id: 'appearance', label: '外观', hint: '配色与明暗' },
  { id: 'downloads', label: '下载', hint: '可选组件' },
  { id: 'about', label: '关于', hint: '版本与链接' },
]

const { settingsOpen, settingsTab, closeSettings, setSettingsTab } = useUi()
const { flushNow } = useSettings()

const panel = ref(null)
const heading = ref(null)
// 打开前的焦点位置：关闭时要还回去，否则用键盘的人会掉到页面开头
let lastFocused = null

const current = computed(() => TABS.find((t) => t.id === settingsTab.value) || TABS[0])

function focusables() {
  const nodes = panel.value?.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )
  return Array.from(nodes || []).filter((el) => el.offsetParent !== null)
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    close()
    return
  }
  if (event.key !== 'Tab') return
  const list = focusables()
  if (!list.length) return
  const first = list[0]
  const last = list[list.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

/** 点遮罩关闭；用 target 判断，避免面板内部的点击冒泡上来把窗口关掉 */
function onBackdrop(event) {
  if (event.target === panel.value) close()
}

function close() {
  closeSettings()
}

watch(settingsOpen, async (open) => {
  if (open) {
    lastFocused = document.activeElement
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKeydown, true)
    await nextTick()
    // 焦点落在「关闭」上：读屏先播报标题，再让用户自己往内容区走
    ;(panel.value?.querySelector('[data-autofocus]') || panel.value)?.focus()
    return
  }
  // 关窗前把还没发出去的改动推一次：防抖窗口里关窗口不能丢改动
  flushNow()
  window.removeEventListener('keydown', onKeydown, true)
  document.body.style.overflow = ''
  if (lastFocused && typeof lastFocused.focus === 'function') lastFocused.focus()
  lastFocused = null
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown, true)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <div v-if="settingsOpen" class="backdrop" @mousedown.self="onBackdrop">
      <div
        ref="panel"
        class="panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        tabindex="-1"
      >
        <aside class="side">
          <h2 id="settings-title" ref="heading" class="title">设置</h2>
          <nav class="tabs" role="tablist" aria-label="设置分类">
            <button
              v-for="tab in TABS"
              :key="tab.id"
              type="button"
              class="tab-btn"
              role="tab"
              :class="{ on: tab.id === current.id }"
              :aria-selected="tab.id === current.id"
              @click="setSettingsTab(tab.id)"
            >
              <span class="tab-label">{{ tab.label }}</span>
              <span class="tab-hint">{{ tab.hint }}</span>
            </button>
          </nav>
          <p class="side-foot">改动即时保存</p>
        </aside>

        <section class="body">
          <header class="body-head">
            <h3 class="body-title">{{ current.label }}</h3>
            <button class="btn btn-sm btn-ghost" type="button" data-autofocus @click="close">
              关闭
            </button>
          </header>

          <div class="body-scroll" role="tabpanel" :aria-label="current.label">
            <ModelTab v-if="current.id === 'model'" />
            <AppearanceTab v-else-if="current.id === 'appearance'" />
            <AboutTab v-else-if="current.id === 'about'" />

            <!-- 「下载」是 M8 的活，这里先给明确占位而不是空白 -->
            <div v-else class="pending">
              <p class="pending-title">可选组件（M8）</p>
              <p class="pending-body">
                向量模型、语音识别、浏览器内核这三块重组件会从安装包里拆出来，按需下载、可卸载。
                下载中心在 M8 做，现在装的是「全量包」，三个组件都已经在里面。
              </p>
            </div>
          </div>

          <footer class="body-foot">
            <span>全部内容存在本机；只有你配置的模型接口会收到内容。</span>
          </footer>
        </section>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background: rgba(20, 18, 14, 0.42);
  animation: fade 0.14s ease;
}

.panel {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr);
  width: 880px;
  max-width: 100%;
  height: 620px;
  max-height: 100%;
  overflow: hidden;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-0);
  box-shadow: var(--shadow-md);
  outline: none;
}

.side {
  display: flex;
  flex-direction: column;
  padding: var(--space-4) var(--space-3);
  border-right: 1px solid var(--c-border);
  background: var(--c-bg-1);
}

.title {
  margin: 0 var(--space-2) var(--space-3);
  font-size: var(--fs-lg);
  font-weight: 600;
}

.tabs {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tab-btn {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
}

.tab-btn:hover {
  background: var(--c-bg-2);
}

.tab-btn.on {
  background: var(--c-primary-soft);
}

.tab-label {
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.tab-btn.on .tab-label {
  color: var(--c-primary-ink);
  font-weight: 600;
}

.tab-hint {
  font-size: 11px;
  color: var(--c-text-3);
}

.side-foot {
  margin: auto 0 0;
  padding: 0 var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.body-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--c-border);
}

.body-title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.body-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}

.body-foot {
  padding: var(--space-2) var(--space-4);
  border-top: 1px solid var(--c-border);
  background: var(--c-bg-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.pending {
  padding: var(--space-6) var(--space-4);
  border: 1px dashed var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.pending-title {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-2);
}

.pending-body {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  line-height: var(--lh-body);
}

@keyframes fade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
