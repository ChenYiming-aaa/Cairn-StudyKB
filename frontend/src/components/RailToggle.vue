<script setup>
/**
 * 折叠 / 展开按钮（T7.0）。
 *
 * 「顶栏与侧栏内各一个位置，状态同一个」——所以这里不接任何 v-model，
 * 直接读 useLayout 的单例状态，两处按钮永远同步。
 */
import { computed } from 'vue'

import { useLayout } from '../composables/useLayout'

const props = defineProps({
  target: { type: String, default: 'sidebar' }, // 'sidebar' | 'list'
})

const { state, toggle } = useLayout()

const collapsed = computed(() => state[props.target].collapsed)
const name = computed(() => (props.target === 'sidebar' ? '左栏' : '列表'))
const tip = computed(() => `${collapsed.value ? '展开' : '收起'}${name.value}`)
</script>

<template>
  <button
    class="rail-toggle"
    type="button"
    :title="tip"
    :aria-label="tip"
    :aria-expanded="!collapsed"
    @click="toggle(target)"
  >
    <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">
      <rect
        x="1.5"
        y="2.5"
        width="13"
        height="11"
        rx="2"
        fill="none"
        stroke="currentColor"
        stroke-width="1.2"
      />
      <line
        :x1="target === 'sidebar' ? 6 : 10"
        y1="2.5"
        :x2="target === 'sidebar' ? 6 : 10"
        y2="13.5"
        stroke="currentColor"
        stroke-width="1.2"
      />
    </svg>
  </button>
</template>

<style scoped>
.rail-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-2);
}

.rail-toggle:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.rail-toggle:focus-visible {
  outline: 2px solid var(--c-primary);
  outline-offset: 1px;
}
</style>
