<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { api, friendlyMessage } from '../api/client'
import { humanDuration, shortTime } from '../utils/format'

/**
 * 条目学习记录（T5.1 DoD：完成一轮后「该条目学习记录里出现这次 session」）。
 *
 * 只列 done / abandoned —— 正在跑的那一轮在顶栏和番茄钟面板里，重复显示会让人以为记了两笔。
 */
const props = defineProps({
  itemId: { type: Number, required: true },
  /** 外部每完成一轮 +1，用来触发重新拉取（不用轮询） */
  refreshTick: { type: Number, default: 0 },
})

const loading = ref(true)
const error = ref('')
const items = ref([])
const total = ref(0)

const focusTotal = computed(() =>
  items.value.filter((s) => s.status === 'done').reduce((sum, s) => sum + s.duration_seconds, 0)
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.sessionHistory({ target_type: 'item', target_id: props.itemId, limit: 20 })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (err) {
    error.value = friendlyMessage(err)
    items.value = []
  } finally {
    loading.value = false
  }
}

watch(() => [props.itemId, props.refreshTick], load)
onMounted(load)
</script>

<template>
  <div class="pane session-log">
    <p class="log-head">
      <span>共 {{ total }} 次</span>
      <span v-if="focusTotal">累计专注 {{ humanDuration(focusTotal) }}</span>
      <span class="muted">不计入暂停与已放弃的时长</span>
    </p>

    <p v-if="loading" class="state-note">加载中…</p>
    <p v-else-if="error" class="state-note error">{{ error }}</p>
    <div v-else-if="!items.length" class="state">
      <p class="state-title">还没在这条上专注过</p>
      <p>点「开始专注」，结束时写一句笔记，这一轮就记在这里。</p>
    </div>
    <ul v-else class="rows">
      <li v-for="row in items" :key="row.id" class="row">
        <span class="row-time">{{ shortTime(row.end_time || row.start_time) }}</span>
        <span class="row-dur" :class="{ muted: row.status !== 'done' }">
          {{ humanDuration(row.duration_seconds) }}
        </span>
        <span class="row-status" :class="row.status">
          {{ row.status === 'done' ? '完成' : '已放弃' }}
        </span>
        <span class="row-note">{{ row.note || '—' }}</span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.session-log {
  overflow-y: auto;
}

.log-head {
  display: flex;
  gap: var(--space-3);
  margin: 0 0 var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

.log-head .muted,
.row-dur.muted {
  color: var(--c-text-3);
}

.state-note {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.state-note.error {
  color: var(--c-danger-ink);
}

.rows {
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  display: grid;
  grid-template-columns: 96px 76px 56px minmax(0, 1fr);
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--c-border);
  font-size: var(--fs-sm);
}

.row-time,
.row-dur {
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  font-variant-numeric: tabular-nums;
}

.row-status {
  font-size: var(--fs-xs);
  color: var(--c-success-ink);
}

.row-status.abandoned {
  color: var(--c-text-3);
}

.row-note {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--c-text-1);
}
</style>
