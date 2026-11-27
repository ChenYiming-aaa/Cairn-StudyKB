<script setup>
/**
 * 模态对话框（原生 <dialog> + showModal）。
 *
 * 为什么坚持原生：焦点陷阱、Esc 关闭、惰性背景、顶层 z-index 全都是浏览器给的，
 * 自己实现这四件事是最容易出回归的一类代码。
 *
 * 关闭后把焦点还给当初打开它的那个控件——不还给「body」，
 * 否则键盘用户按 Tab 会从页面开头重新数一遍。
 */
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import Icon from './Icon.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  size: { type: String, default: 'md' }, // sm | md | lg
})

const emit = defineEmits(['close'])

const el = ref(null)
let lastFocus = null

watch(
  () => props.open,
  async (isOpen) => {
    const node = el.value
    if (!node) return

    if (isOpen) {
      lastFocus = document.activeElement
      if (!node.open) node.showModal()
      await nextTick()
      // 初始焦点放在标了 data-autofocus 的元素上，没有就落到第一个可交互控件
      const target =
        node.querySelector('[data-autofocus]') ||
        node.querySelector('input, select, textarea, button:not(.u-dialog-x)')
      if (target && typeof target.focus === 'function') target.focus()
    } else if (node.open) {
      node.close()
    }
  }
)

onBeforeUnmount(() => {
  if (el.value?.open) el.value.close()
})

/** 原生 close 事件覆盖三种关法：Esc、点按钮、主动 close() —— 统一在这里归还焦点 */
function onNativeClose() {
  if (lastFocus && typeof lastFocus.focus === 'function' && document.contains(lastFocus)) {
    lastFocus.focus()
  }
  lastFocus = null
  emit('close')
}

/** 点遮罩空白处关闭：只在真正点到 dialog 本体（而非内部容器）时触发 */
function onBackdropClick(event) {
  if (event.target === el.value) emit('close')
}
</script>

<template>
  <dialog
    ref="el"
    class="u-dialog"
    :class="`u-dialog-${size}`"
    :aria-label="title"
    @close="onNativeClose"
    @click="onBackdropClick"
  >
    <div class="u-dialog-inner">
      <header class="u-dialog-head">
        <h2 class="u-dialog-title">{{ title }}</h2>
        <button class="u-dialog-x" type="button" aria-label="关闭" @click="emit('close')">
          <Icon name="x" :size="20" />
        </button>
      </header>

      <div class="u-dialog-body">
        <slot />
      </div>

      <footer v-if="$slots.footer" class="u-dialog-foot">
        <slot name="footer" />
      </footer>
    </div>
  </dialog>
</template>

<style scoped>
/* 关键：未打开的 dialog 必须彻底不显示。
   组件用了 flex，如果只写 .u-dialog { display: flex } 会把关闭状态的对话框顶出来。 */
.u-dialog {
  display: none;
  position: fixed;
  inset: 0;
  margin: auto;
  padding: 0;
  width: min(560px, calc(100vw - 2 * var(--space-6)));
  max-height: calc(100vh - 2 * var(--space-8));
  border: 1px solid var(--c-border);
  border-radius: var(--radius-lg);
  background: var(--c-surface-2);
  color: var(--c-text-1);
  box-shadow: var(--elev-3);
  overflow: visible;
}

.u-dialog[open] {
  display: flex;
}

.u-dialog::backdrop {
  background: var(--overlay-scrim);
}

.u-dialog-sm {
  width: min(420px, calc(100vw - 2 * var(--space-6)));
}

.u-dialog-lg {
  width: min(760px, calc(100vw - 2 * var(--space-6)));
}

.u-dialog-inner {
  display: flex;
  flex-direction: column;
  min-height: 0;
  width: 100%;
  max-height: calc(100vh - 2 * var(--space-8));
}

.u-dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--c-border);
}

.u-dialog-title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  line-height: var(--lh-tight);
  letter-spacing: var(--ls-title);
}

.u-dialog-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-3);
  cursor: pointer;
}

.u-dialog-x:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.u-dialog-x:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.u-dialog-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-5);
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  color: var(--c-text-1);
}

.u-dialog-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-5) var(--space-4);
  border-top: 1px solid var(--c-border);
}

/* 进场：只动 opacity 与 transform */
.u-dialog[open] .u-dialog-inner {
  animation: u-dialog-in var(--dur-overlay) var(--ease-out) both;
}

@keyframes u-dialog-in {
  from {
    opacity: 0;
    transform: translateY(6px) scale(0.99);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .u-dialog[open] .u-dialog-inner {
    animation: none;
  }
}
</style>
