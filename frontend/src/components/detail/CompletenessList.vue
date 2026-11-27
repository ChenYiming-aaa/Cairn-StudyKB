<script setup>
/**
 * 完善度清单（借鉴 GitHub 仓库的社区标准卡片）。
 *
 * 回答的问题是「这条内容还差什么、下一步点哪里」，而不是「你考了多少分」。
 * 每一步的完成状态全部由**已有字段**推导（有没有原文 / 是否整理过 / 有没有要点 / 有没有笔记），
 * 不引入新接口，也不会出现算不准的假进度。
 *
 * 未完成项直接带一个动作按钮——清单本身不能只是描述问题。
 */
import Icon from '../../ui/Icon.vue'

defineProps({
  // [{ key, label, done, hint, action }]，action 是按钮文案，没有就不给按钮
  steps: { type: Array, required: true },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits(['action'])
</script>

<template>
  <div class="checklist">
    <ul class="checklist-rows">
      <li
        v-for="step in steps"
        :key="step.key"
        class="check-row"
        :class="{ 'is-done': step.done }"
      >
        <span class="check-mark" aria-hidden="true">
          <Icon :name="step.done ? 'check' : 'chevron-right'" :size="12" />
        </span>

        <span class="check-body">
          <span class="check-label">
            {{ step.label }}
            <span class="sr-only">{{ step.done ? '（已完成）' : '（未完成）' }}</span>
          </span>
          <span v-if="step.hint" class="check-hint">{{ step.hint }}</span>
        </span>

        <button
          v-if="!step.done && step.action"
          class="check-action"
          type="button"
          :disabled="busy"
          @click="emit('action', step.key)"
        >
          {{ step.action }}
        </button>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.checklist-rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--c-border);
}

.check-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.check-row:first-child {
  padding-top: 0;
}

/* 完成状态：圆形实底 + 对勾；未完成：空心的箭头，暗示「这一步还没走」 */
.check-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  flex: none;
  border-radius: 50%;
  border: 1px solid var(--c-border);
  background: var(--c-bg-2);
  color: var(--c-text-3);
}

.is-done .check-mark {
  border-color: var(--c-success-border);
  background: var(--c-success-soft);
  color: var(--c-success-ink);
}

.check-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.check-label {
  display: block;
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--c-text-1);
}

.is-done .check-label {
  color: var(--c-text-2);
}

.check-hint {
  display: block;
  font-size: var(--fs-xs);
  line-height: 1.5;
  color: var(--c-text-3);
}

.check-action {
  flex: none;
  align-self: center;
  padding: 2px var(--space-2);
  border: 1px solid var(--c-primary-border);
  border-radius: var(--radius-sm);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-family: var(--font-ui);
  font-size: var(--fs-xs);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.check-action:hover:not(:disabled) {
  background: var(--c-bg-2);
}

.check-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.check-action:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
</style>
