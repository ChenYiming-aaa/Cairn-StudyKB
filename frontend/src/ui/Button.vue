<script setup>
/**
 * 按钮。
 *
 * 变体只保留四个：primary（一屏唯一的主操作）、secondary（并列的次级操作）、
 * ghost（工具栏与图标按钮）、danger（不可逆操作）。
 * 同一视口里出现两个以上 primary，说明主操作没有被确定——那是信息层级的问题，不该靠加按钮解决。
 */
import { computed, useSlots } from 'vue'

// 安装后本文件位于 frontend/src/ui/，Icon.vue 与它同级
import Icon from './Icon.vue'

const props = defineProps({
  variant: { type: String, default: 'secondary' }, // primary | secondary | ghost | danger
  size: { type: String, default: 'md' }, // sm | md
  icon: { type: String, default: '' },
  // 没有文字时用它当可访问名称与 tooltip；有文字时忽略
  label: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  type: { type: String, default: 'button' },
})

const emit = defineEmits(['click'])
const slots = useSlots()

const iconSize = computed(() => (props.size === 'sm' ? 16 : 20))
// 只凭「有没有文字」判断，不凭有没有 label：传了 label 但没槽内容时，
// 它应该是「一个带可访问名称的图标按钮」，而不是「一个空文字按钮」
const iconOnly = computed(() => Boolean(props.icon) && !slots.default)

function onClick(event) {
  if (props.disabled || props.loading) {
    event.preventDefault()
    return
  }
  emit('click', event)
}
</script>

<template>
  <button
    :type="type"
    class="u-btn"
    :class="[
      `u-btn-${variant}`,
      `u-btn-${size}`,
      { 'is-block': block, 'is-loading': loading, 'is-icon-only': iconOnly },
    ]"
    :disabled="disabled || loading"
    :aria-busy="loading ? 'true' : undefined"
    :aria-label="iconOnly ? label : undefined"
    :title="iconOnly ? label : undefined"
    @click="onClick"
  >
    <Icon v-if="loading" name="spinner" :size="iconSize" class="spin" />
    <Icon v-else-if="icon" :name="icon" :size="iconSize" />
    <span v-if="!iconOnly" class="u-btn-text"><slot /></span>
  </button>
</template>

<style scoped>
.u-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  font-family: var(--font-ui);
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.u-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.u-btn:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* ── 尺寸 ── */
.u-btn-md {
  min-height: 34px;
  padding: 0 var(--space-4);
  font-size: var(--fs-md);
}

.u-btn-sm {
  min-height: 28px;
  padding: 0 var(--space-3);
  font-size: var(--fs-sm);
}

.u-btn.is-icon-only.u-btn-md {
  width: 34px;
  padding: 0;
}

.u-btn.is-icon-only.u-btn-sm {
  width: 28px;
  padding: 0;
}

.u-btn.is-block {
  width: 100%;
}

/* ── primary ── */
.u-btn-primary {
  background: var(--c-primary);
  color: var(--c-on-primary);
  border-color: var(--c-primary);
}

.u-btn-primary:hover:not(:disabled) {
  background: var(--c-primary-hover);
  border-color: var(--c-primary-hover);
}

.u-btn-primary:active:not(:disabled) {
  transform: translateY(1px);
}

/* ── secondary ── */
.u-btn-secondary {
  background: var(--c-surface-1);
  color: var(--c-text-1);
  border-color: var(--c-border);
}

.u-btn-secondary:hover:not(:disabled) {
  background: var(--c-bg-2);
  border-color: var(--c-line-strong);
  color: var(--c-text-1);
}

/* ── ghost ── */
.u-btn-ghost {
  background: transparent;
  color: var(--c-text-2);
}

.u-btn-ghost:hover:not(:disabled) {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

/* ── danger ── */
.u-btn-danger {
  background: var(--c-danger);
  /* danger 是实心深色，文字必须显式给白，不能继承 */
  color: #fff;
  border-color: var(--c-danger);
}

.u-btn-danger:hover:not(:disabled) {
  background: var(--c-danger-ink);
  border-color: var(--c-danger-ink);
}

.u-btn-text {
  display: inline-block;
}

.spin {
  animation: u-spin 0.9s linear infinite;
}

@keyframes u-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .spin {
    animation-duration: 2.4s;
  }

  .u-btn:active:not(:disabled) {
    transform: none;
  }
}
</style>
