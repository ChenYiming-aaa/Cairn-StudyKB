<script setup>
/**
 * 状态快筛（T7.1）：把「待整理 / 整理中」从颜色小点升级成可点的行。
 *
 * 与分类/标签的关系是**叠加**（2026-11-09 裁决）：点「待整理」后再点某分类 = 该分类下还没整理的。
 * 所以这里只发状态，不清另外两个筛选。
 */
import { computed } from 'vue'

const props = defineProps({
  counts: { type: Object, default: () => ({ total: 0, pending: 0, organizing: 0 }) },
  // '' | 'pending' | 'organizing'
  active: { type: String, default: '' },
})
const emit = defineEmits(['all', 'pick'])

/** 有数量时才显示对应行：永远是 0 的「整理中」只会增加视觉噪音 */
const rows = computed(() => {
  const list = [{ key: '', label: '全部条目', count: props.counts.total || 0, tone: '' }]
  if (props.counts.pending > 0) {
    list.push({ key: 'pending', label: '待整理', count: props.counts.pending, tone: 'warning' })
  }
  if (props.counts.organizing > 0) {
    list.push({ key: 'organizing', label: '整理中', count: props.counts.organizing, tone: 'info' })
  }
  return list
})

function pick(key) {
  if (!key) {
    // 「全部条目」是根节点：连分类/标签一起清掉，不是只清状态
    emit('all')
    return
  }
  emit('pick', key)
}
</script>

<template>
  <div class="status-filter">
    <button
      v-for="row in rows"
      :key="row.key || 'all'"
      type="button"
      class="row"
      :class="{ on: active === row.key }"
      @click="pick(row.key)"
    >
      <span v-if="row.tone" class="dot" :class="row.tone" aria-hidden="true" />
      <span class="label">{{ row.label }}</span>
      <span class="count">{{ row.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.status-filter {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0 var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--c-border);
}

.row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.row:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.row.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-weight: 600;
}

.label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  color: var(--c-text-3);
}

.row.on .count {
  color: var(--c-primary-ink);
}

.dot {
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
}

.dot.warning {
  background: var(--c-warning);
}

.dot.info {
  background: var(--c-primary);
}
</style>
