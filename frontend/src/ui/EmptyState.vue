<script setup>
/**
 * 空态。
 *
 * 空态永远回答两个问题：「这里将来会出现什么」和「我现在能做什么」。
 * 只有一句「暂无数据」的空态等于把用户丢在原地。
 *
 * 不传 action 插槽时，第二行会自动收成一个引导句，不留空位。
 */
import Icon from './Icon.vue'

defineProps({
  icon: { type: String, default: 'inbox' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  // 紧凑版：用在列表栏、抽屉这类窄容器里
  compact: { type: Boolean, default: false },
})
</script>

<template>
  <div class="u-empty" :class="{ 'is-compact': compact }">
    <span class="u-empty-icon" aria-hidden="true">
      <Icon :name="icon" :size="compact ? 24 : 32" />
    </span>

    <p class="u-empty-title">{{ title }}</p>
    <p v-if="description" class="u-empty-desc">{{ description }}</p>

    <div v-if="$slots.default" class="u-empty-actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.u-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-12) var(--space-6);
  text-align: center;
}

.u-empty.is-compact {
  padding: var(--space-8) var(--space-4);
}

.u-empty-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  margin-bottom: var(--space-1);
  border-radius: 50%;
  background: var(--c-bg-2);
  color: var(--c-text-3);
}

.u-empty.is-compact .u-empty-icon {
  width: 36px;
  height: 36px;
}

.u-empty-title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  line-height: var(--lh-title);
  color: var(--c-text-1);
}

.u-empty.is-compact .u-empty-title {
  font-size: var(--fs-md);
}

.u-empty-desc {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--c-text-3);
}

/* 只有窄容器（列表栏、抽屉）需要限行宽：宽面板里限到 34ch 会把「摘要」这类
   两字词从中间折断，中文没有空格可以回退，断在哪完全由宽度决定 */
.u-empty.is-compact .u-empty-desc {
  max-width: 34ch;
}

.u-empty-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
