<script setup>
/**
 * 内容概览面板（详情页的数据层）。
 *
 * 借鉴 GitHub 仓库页的信息架构：页头给出「这是什么 + 能做什么」，
 * 数据摘要贴着页头展开，正文保持干净的阅读宽度。
 *
 * 三条设计取舍：
 * 1. **可折叠**。读长文时这块占的几百像素是实打实的，不该永远压在上面。
 *    折叠后仍留一条进度条与一句结论，状态不会因为收起而丢失。
 * 2. **不堆卡片**。整块是一张面板内部的网格，不是六个浮起的卡片堆——
 *    卡片堆叠会让页面看起来像组件演示而不是工作界面。
 * 3. **动效只用一个**。展开/收起走高度的话会触发重排，这里改用透明度 + 位移，
 *    并且只动 transform / opacity。
 */
import { ref } from 'vue'

import Icon from '../../ui/Icon.vue'

defineProps({
  title: { type: String, default: '内容概览' },
  // 折叠后仍要看得见的那句话，例如「4 / 6 步已完成」
  headline: { type: String, default: '' },
  percent: { type: Number, default: 0 },
})

const collapsed = ref(false)
</script>

<template>
  <section class="insight" :class="{ 'is-collapsed': collapsed }">
    <header class="insight-head">
      <button
        class="insight-toggle"
        type="button"
        :aria-expanded="collapsed ? 'false' : 'true'"
        @click="collapsed = !collapsed"
      >
        <Icon :name="collapsed ? 'chevron-right' : 'chevron-down'" :size="16" />
        <span class="insight-title">{{ title }}</span>
      </button>

      <span v-if="headline" class="insight-headline">{{ headline }}</span>

      <!-- 折叠后仍保留的进度线索：一条细条，不占高度 -->
      <span class="insight-meter" role="img" :aria-label="`已完成 ${percent}%`">
        <span class="insight-meter-fill" :style="{ width: `${percent}%` }" />
      </span>
    </header>

    <div v-show="!collapsed" class="insight-body">
      <div class="insight-main">
        <slot />
      </div>
      <aside class="insight-side">
        <slot name="side" />
      </aside>
    </div>
  </section>
</template>

<style scoped>
.insight {
  flex: none;
  margin-bottom: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-surface-1);
  overflow: hidden;
}

.insight-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid transparent;
}

.insight:not(.is-collapsed) .insight-head {
  border-bottom-color: var(--c-border);
}

.insight-toggle {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 2px var(--space-1);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-2);
  font-family: var(--font-ui);
  font-size: var(--fs-sm);
  font-weight: 600;
  cursor: pointer;
}

.insight-toggle:hover {
  color: var(--c-text-1);
}

.insight-toggle:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.insight-title {
  display: block;
  white-space: nowrap;
}

.insight-headline {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 进度条推到最右，宽度自适应：折叠与否都占满剩余空间 */
.insight-meter {
  flex: 1;
  min-width: 40px;
  height: 3px;
  margin-left: auto;
  border-radius: 999px;
  background: var(--c-bg-2);
  overflow: hidden;
}

.insight-meter-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--c-primary);
  transition: width var(--dur-progress) var(--ease-out);
}

.insight-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(240px, 300px);
  gap: var(--space-5);
  padding: var(--space-4);
  animation: insight-in var(--dur-enter) var(--ease-out) both;
}

.insight-main {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
}

.insight-side {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
  padding-left: var(--space-5);
  border-left: 1px solid var(--c-border);
}

@keyframes insight-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }

  to {
    opacity: 1;
    transform: none;
  }
}

/* 窄窗：两列并一列，侧栏的左边框改成上分隔线 */
@media (max-width: 1080px) {
  .insight-body {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-4);
  }

  .insight-side {
    padding-left: 0;
    padding-top: var(--space-4);
    border-left: none;
    border-top: 1px solid var(--c-border);
  }
}

@media (prefers-reduced-motion: reduce) {
  .insight-body {
    animation: none;
  }

  .insight-meter-fill {
    transition: none;
  }
}
</style>
