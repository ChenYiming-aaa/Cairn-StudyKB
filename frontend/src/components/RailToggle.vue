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
  target: { type: String, default: 'sidebar' }, // 'sidebar' | 'list' | 'picker' | 'config'
})

const { state, toggle } = useLayout()

const LABELS = { sidebar: '左栏', list: '列表', picker: '内容选择', config: '出题配置' }
// 这几栏都在左边（折叠后是左侧窄条），图标里的分隔线画在左侧
const ON_LEFT = ['sidebar', 'picker', 'config']

const collapsed = computed(() => state[props.target].collapsed)
const name = computed(() => LABELS[props.target] || '侧栏')
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
        :x1="ON_LEFT.includes(target) ? 6 : 10"
        y1="2.5"
        :x2="ON_LEFT.includes(target) ? 6 : 10"
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
