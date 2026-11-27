<script setup>
/**
 * 页签。
 *
 * 用于「同一份内容的不同视角」（原文 / 笔记 / 摘要 / 脑图），不用于导航——
 * 页面级的跳转请用 router-link，否则浏览器前进后退会失效。
 *
 * 键盘：左右方向键切页签、Home/End 跳到首尾（WAI-ARIA Tabs 标准行为）。
 */
import { ref } from 'vue'

import Icon from './Icon.vue'

const props = defineProps({
  // [{ id, label, icon? }]
  tabs: { type: Array, required: true },
})

const model = defineModel({ type: String, required: true })

const root = ref(null)

function select(id) {
  model.value = id
}

function onKeydown(event, index) {
  const last = props.tabs.length - 1
  let next

  if (event.key === 'ArrowRight') next = index === last ? 0 : index + 1
  else if (event.key === 'ArrowLeft') next = index === 0 ? last : index - 1
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = last
  else return

  event.preventDefault()
  const target = props.tabs[next]
  if (!target) return
  model.value = target.id
  // 焦点跟着选中走，否则键盘用户还得再按一次 Tab
  root.value?.querySelector(`#tab-${target.id}`)?.focus()
}
</script>

<template>
  <!-- `tabs` / `tab` / `on` 是旧类名兼容钩子：verify_m7、verify_m11 与 e2e 都按
       `.tabs .tab`、`.tab.on` 定位页签。视觉一律由 `.u-*` 承担，旧类名只保留可定位性，
       与 app-shell-v05.css 里「旧类名不删、只升级外观」是同一条规矩。 -->
  <div ref="root" class="u-tabs tabs" role="tablist">
    <button
      v-for="(tab, index) in tabs"
      :id="`tab-${tab.id}`"
      :key="tab.id"
      type="button"
      role="tab"
      class="u-tab tab"
      :class="{ 'is-active': model === tab.id, on: model === tab.id }"
      :aria-selected="model === tab.id ? 'true' : 'false'"
      :tabindex="model === tab.id ? 0 : -1"
      @click="select(tab.id)"
      @keydown="onKeydown($event, index)"
    >
      <Icon v-if="tab.icon" :name="tab.icon" :size="16" />
      <span>{{ tab.label }}</span>
      <!-- 计数：不点进去也知道里面有没有东西、有多少（0 或未给就不显示，避免一排零） -->
      <span v-if="tab.count" class="u-tab-count">{{ tab.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.u-tabs {
  display: flex;
  align-items: stretch;
  gap: var(--space-1);
  border-bottom: 1px solid var(--c-border);
  overflow-x: auto;
  scrollbar-width: none;
}

.u-tabs::-webkit-scrollbar {
  display: none;
}

.u-tab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  color: var(--c-text-3);
  font-family: var(--font-ui);
  font-size: var(--fs-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out);
}

.u-tab:hover {
  color: var(--c-text-1);
}

.u-tab:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: var(--radius-sm);
}

.u-tab.is-active {
  color: var(--c-primary-ink);
}

/* 选中态指示条：只挂在 active 上，切换时靠 transform 生长，不做整排位移 */
.u-tab::after {
  content: '';
  position: absolute;
  inset: auto var(--space-3) -1px;
  height: 2px;
  border-radius: 2px;
  background: var(--c-primary);
  transform: scaleX(0);
  transform-origin: center;
  transition: transform var(--dur-enter) var(--ease-out);
}

.u-tab.is-active::after {
  transform: scaleX(1);
}

/* 计数胶囊：比页签名再轻一档，不与标签争读 */
.u-tab-count {
  min-width: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--c-bg-2);
  color: var(--c-text-3);
  font-size: 11px;
  font-weight: 500;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.u-tab.is-active .u-tab-count {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

@media (prefers-reduced-motion: reduce) {
  .u-tab::after {
    transition: none;
  }
}
</style>
