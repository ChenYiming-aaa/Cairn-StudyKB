<script setup>
/**
 * 折叠 / 展开按钮（T7.0）。
 *
 * 「顶栏与侧栏内各一个位置，状态同一个」——所以这里不接任何 v-model，
 * 直接读 useLayout 的单例状态，两处按钮永远同步。
 *
 * v0.5 改动：手写的 15×15 轮廓 SVG 换成图标集里的 panel-left / panel-list，
 * 与顶栏其余图标同一套描边与圆角；命中区域从 28×28 提到 30×30（仍小于 44，
 * 因为它是桌面端的高频小控件，且两侧留了 ≥8px 间距不会误触相邻按钮）。
 */
import { computed } from 'vue'

import { useLayout } from '../composables/useLayout'
import Icon from '../ui/Icon.vue'

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
const iconName = computed(() => (ON_LEFT.includes(props.target) ? 'panel-left' : 'panel-list'))
</script>

<template>
  <button
    class="rail-toggle"
    :class="{ 'is-collapsed': collapsed }"
    type="button"
    :title="tip"
    :aria-label="tip"
    :aria-expanded="!collapsed"
    @click="toggle(target)"
  >
    <Icon :name="iconName" :size="16" />
  </button>
</template>

<style scoped>
.rail-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-3);
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.rail-toggle:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.rail-toggle:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* 收起时图标降到更弱：按钮本身仍然可点，但要让用户看出这一栏此刻是关的 */
.rail-toggle.is-collapsed {
  color: var(--c-text-2);
}
</style>
