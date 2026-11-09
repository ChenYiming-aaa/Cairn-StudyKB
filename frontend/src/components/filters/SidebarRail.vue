<script setup>
/**
 * 左栏的 44px 窄条（T7.0 §3.2「能收」）。
 *
 * 四个图标不是四个页面，是**筛选入口**（2026-11-09 裁决）：点哪个就展开左栏并落到那个视图，
 * 否则收起之后就只是个「展开」按钮，等于把用户的视图丢了。
 */
import { computed } from 'vue'

const props = defineProps({
  counts: { type: Object, default: () => ({ total: 0, pending: 0, organizing: 0 }) },
  status: { type: String, default: '' },
  active: { type: Object, default: () => ({ category: '', tag: '' }) },
})
const emit = defineEmits(['all', 'status', 'section'])

const isAll = computed(
  () => !props.status && !props.active.category && !props.active.tag
)
</script>

<template>
  <div class="rail-nav">
    <button
      type="button"
      class="rail-btn"
      :class="{ on: isAll }"
      :title="`全部条目 · ${counts.total}`"
      aria-label="全部条目"
      @click="emit('all')"
    >
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <line x1="2" y1="4" x2="14" y2="4" stroke="currentColor" stroke-width="1.3" />
        <line x1="2" y1="8" x2="14" y2="8" stroke="currentColor" stroke-width="1.3" />
        <line x1="2" y1="12" x2="14" y2="12" stroke="currentColor" stroke-width="1.3" />
      </svg>
    </button>

    <button
      v-if="counts.pending > 0"
      type="button"
      class="rail-btn"
      :class="{ on: status === 'pending' }"
      :title="`待整理 · ${counts.pending}`"
      aria-label="待整理"
      @click="emit('status', 'pending')"
    >
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.3" />
        <line x1="8" y1="4.6" x2="8" y2="8.4" stroke="currentColor" stroke-width="1.3" />
        <circle cx="8" cy="10.9" r="0.8" fill="currentColor" />
      </svg>
    </button>

    <button
      type="button"
      class="rail-btn"
      :class="{ on: Boolean(active.category) }"
      title="分类"
      aria-label="分类"
      @click="emit('section', 'cat')"
    >
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path
          d="M2 5.2a1.2 1.2 0 0 1 1.2-1.2h3l1.3 1.6h5.3A1.2 1.2 0 0 1 14 6.8v4.4a1.2 1.2 0 0 1-1.2 1.2H3.2A1.2 1.2 0 0 1 2 11.2z"
          fill="none"
          stroke="currentColor"
          stroke-width="1.3"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    <button
      type="button"
      class="rail-btn"
      :class="{ on: Boolean(active.tag) }"
      title="标签"
      aria-label="标签"
      @click="emit('section', 'tag')"
    >
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <line x1="6" y1="2.5" x2="4.6" y2="13.5" stroke="currentColor" stroke-width="1.3" />
        <line x1="11.4" y1="2.5" x2="10" y2="13.5" stroke="currentColor" stroke-width="1.3" />
        <line x1="2.4" y1="6" x2="13.6" y2="6" stroke="currentColor" stroke-width="1.3" />
        <line x1="2.4" y1="10" x2="13.6" y2="10" stroke="currentColor" stroke-width="1.3" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
.rail-nav {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  width: 100%;
  margin-top: var(--space-1);
}

.rail-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-3);
}

.rail-btn:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.rail-btn.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.rail-btn:focus-visible {
  outline: 2px solid var(--c-primary);
  outline-offset: 1px;
}
</style>
