<script setup>
/**
 * 拖拽分隔条（T7.0）。
 *
 * 只做三件事，都别加戏：
 * 1. 拖：pointer events + capture，指针移出面板也不丢
 * 2. 双击：回到默认宽（用户改窄了想反悔，不用一像素一像素拖）
 * 3. 键盘：聚焦后 ← → 每次 8px（鼠标拖不准的时候，键盘更准）
 */
import { ref } from 'vue'

import { useLayout } from '../composables/useLayout'

const props = defineProps({
  // 'sidebar' | 'list'，决定改哪一栏、夹在哪个区间
  target: { type: String, default: 'sidebar' },
  label: { type: String, default: '调整宽度' },
})

const { width, setWidth, resetWidth } = useLayout()

const dragging = ref(false)
const handle = ref(null)
let startX = 0
let startWidth = 0

function onPointerDown(event) {
  if (event.button !== 0) return
  event.preventDefault()
  startX = event.clientX
  startWidth = width(props.target)
  dragging.value = true
  handle.value?.setPointerCapture?.(event.pointerId)
  // 拖的时候整页禁选中 + 光标保持一致，否则会顺手选中旁边列表的文字
  document.body.classList.add('is-resizing')
}

function onPointerMove(event) {
  if (!dragging.value) return
  // 拖动过程不写盘：每一帧都写 localStorage 既没必要也会卡
  setWidth(props.target, startWidth + (event.clientX - startX), { persist: false })
}

function onPointerUp(event) {
  if (!dragging.value) return
  dragging.value = false
  handle.value?.releasePointerCapture?.(event.pointerId)
  document.body.classList.remove('is-resizing')
  // 松手才落盘一次
  setWidth(props.target, width(props.target))
}

function onKeydown(event) {
  const step = event.shiftKey ? 24 : 8
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    setWidth(props.target, width(props.target) - step)
  } else if (event.key === 'ArrowRight') {
    event.preventDefault()
    setWidth(props.target, width(props.target) + step)
  } else if (event.key === 'Home') {
    event.preventDefault()
    resetWidth(props.target)
  }
}
</script>

<template>
  <div
    ref="handle"
    class="split-handle"
    :class="{ dragging }"
    role="separator"
    aria-orientation="vertical"
    :aria-label="label"
    :aria-valuenow="width(target)"
    tabindex="0"
    title="拖动调整宽度，双击复位"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @dblclick="resetWidth(target)"
    @keydown="onKeydown"
  >
    <span class="grip" aria-hidden="true" />
  </div>
</template>

<style scoped>
.split-handle {
  position: absolute;
  top: 0;
  right: -4px;
  z-index: 5;
  width: 8px;
  height: 100%;
  cursor: col-resize;
  touch-action: none;
}

/* 抓握提示：默认只有一根 1px 的线，悬停才变粗，别在静止时抢视线 */
.grip {
  position: absolute;
  top: 0;
  left: 3px;
  width: 2px;
  height: 100%;
  background: transparent;
  transition: background 0.15s;
}

.split-handle:hover .grip,
.split-handle:focus-visible .grip,
.split-handle.dragging .grip {
  background: var(--c-primary-border);
}

.split-handle:focus-visible {
  outline: 2px solid var(--c-primary);
  outline-offset: -2px;
}
</style>
