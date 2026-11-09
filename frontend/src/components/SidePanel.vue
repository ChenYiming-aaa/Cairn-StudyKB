<script setup>
/**
 * 侧栏统一包壳（T7.0）：宽度由 CSS 变量给，这里只管「折叠时露什么」和「拖拽手柄挂哪」。
 *
 * 宽度与记忆都归 `useLayout`（那是唯一真源），本组件刻意不接 min/max/storageKey ——
 * 7 个页面各自传一套区间，迟早会互相打架。
 */
import { computed } from 'vue'

import SplitHandle from './SplitHandle.vue'
import { useLayout } from '../composables/useLayout'

const props = defineProps({
  target: { type: String, default: 'sidebar' }, // 'sidebar' | 'list'
  // 折叠后留 44px 窄条（图标条）。列表栏不要窄条，收就收干净（宽度 0）
  rail: { type: Boolean, default: false },
  title: { type: String, default: '' },
})

const { isCollapsed } = useLayout()
const collapsed = computed(() => isCollapsed(props.target))
// 只有「支持窄条」的侧栏在收起时才切 rail；列表栏收起是干净的 0 宽
const showRail = computed(() => collapsed.value && props.rail)
</script>

<template>
  <aside class="side-panel" :class="{ 'is-collapsed': collapsed }" :aria-label="title || undefined">
    <!-- 用 v-show 而不是 v-if：折叠一次不该把搜索词和展开状态全丢掉 -->
    <div v-show="showRail" class="rail">
      <slot name="rail" />
    </div>
    <div v-show="!showRail" class="panel-body">
      <slot />
    </div>
    <SplitHandle v-if="!collapsed" :target="target" :label="`调整${title || '侧栏'}宽度`" />
  </aside>
</template>

<style scoped>
.side-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--c-bg-1);
  border-right: 1px solid var(--c-border);
}

/* 收起：宽度由 grid 列（--w-list: 0）决定，这里只负责别留下 1px 边框和溢出内容 */
.side-panel.is-collapsed {
  border-right: 0;
  overflow: hidden;
}

.panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.rail {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) 0 var(--space-4);
}
</style>
