<script setup>
/**
 * 徽标：一枚标签，表达「状态」而不是「类别」的，一律配图标或圆点 + 文字。
 *
 * 状态绝不能只靠颜色区分（色盲用户与黑白打印都读不出差异），
 * 所以 tone 只决定底色与描边，文字本身已经把状态说清楚了。
 *
 * 字重刻意用 500 而不是 600：列表里每行都挂一枚徽标，600 会让整列发黑。
 */
import Icon from './Icon.vue'

defineProps({
  tone: { type: String, default: 'neutral' }, // neutral | info | success | warning | danger
  icon: { type: String, default: '' },
  // 不需要图标时给一个静态圆点，视觉重量更轻
  dot: { type: Boolean, default: false },
  // organizing 这类进行中的状态给呼吸点
  pulse: { type: Boolean, default: false },
})
</script>

<template>
  <!-- `badge` 是旧类名兼容钩子：e2e 与部分脚本按 `.badge` 取状态徽标。
       外观仍由 `.u-badge*` 决定（scoped 选择器优先级压过全局 `.badge`）。 -->
  <span class="u-badge badge" :class="`u-badge-${tone}`">
    <Icon v-if="icon" :name="icon" :size="12" />
    <i v-else-if="dot" class="u-badge-dot" :class="{ 'is-pulsing': pulse }" />
    <span class="u-badge-text"><slot /></span>
  </span>
</template>

<style scoped>
.u-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px var(--space-2);
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: var(--fs-xs);
  font-weight: 500;
  line-height: 16px;
  white-space: nowrap;
}

.u-badge-dot {
  width: 5px;
  height: 5px;
  flex: none;
  border-radius: 50%;
  background: currentColor;
}

.u-badge-dot.is-pulsing {
  animation: u-badge-pulse 1.4s ease-in-out infinite;
}

@keyframes u-badge-pulse {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0.25;
  }
}

.u-badge-neutral {
  background: var(--c-bg-2);
  border-color: var(--c-border);
  color: var(--c-text-2);
}

.u-badge-info {
  background: var(--c-primary-soft);
  border-color: var(--c-primary-border);
  color: var(--c-primary-ink);
}

.u-badge-success {
  background: var(--c-success-soft);
  border-color: var(--c-success-border);
  color: var(--c-success-ink);
}

.u-badge-warning {
  background: var(--c-warning-soft);
  border-color: var(--c-warning-border);
  color: var(--c-warning-ink);
}

.u-badge-danger {
  background: var(--c-danger-soft);
  border-color: var(--c-danger-border);
  color: var(--c-danger-ink);
}

@media (prefers-reduced-motion: reduce) {
  .u-badge-dot.is-pulsing {
    animation: none;
  }
}
</style>
