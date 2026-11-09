<script setup>
import { ref, watch } from 'vue'

import StatusBadge from './StatusBadge.vue'
import { shortTime } from '../utils/format'

const props = defineProps({
  items: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  activeId: { type: Number, default: null },
  q: { type: String, default: '' },
  pendingCount: { type: Number, default: 0 },
  organizing: { type: Boolean, default: false },
  filtered: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'search', 'retry', 'organize-pending'])

const keyword = ref(props.q)
let timer = null

watch(
  () => props.q,
  (value) => {
    if (value !== keyword.value) keyword.value = value
  }
)

function onInput() {
  clearTimeout(timer)
  timer = setTimeout(() => emit('search', keyword.value.trim()), 300)
}

function clearKeyword() {
  keyword.value = ''
  clearTimeout(timer)
  emit('search', '')
}
</script>

<template>
  <section class="list-panel">
    <div class="list-toolbar">
      <div class="search">
        <input
          v-model="keyword"
          class="input"
          type="search"
          placeholder="搜索标题"
          @input="onInput"
        />
        <button v-if="keyword" class="clear" type="button" title="清空" @click="clearKeyword">×</button>
      </div>
      <div class="list-meta">
        <span>{{ total }} 条{{ filtered ? '（已筛选）' : '' }}</span>
        <button
          v-if="pendingCount > 0"
          class="btn btn-ghost btn-sm"
          type="button"
          :disabled="organizing"
          @click="emit('organize-pending')"
        >
          {{ organizing ? '整理中…' : `整理待处理 ${pendingCount}` }}
        </button>
      </div>
    </div>

    <div class="list-body">
      <div v-if="loading && !items.length" class="skeletons">
        <div v-for="i in 5" :key="i" class="skeleton-row">
          <div class="skeleton" style="width: 70%" />
          <div class="skeleton" style="width: 40%; height: 10px" />
        </div>
      </div>

      <div v-else-if="error" class="state state-error">
        <p class="state-title">列表加载失败</p>
        <p>{{ error }}</p>
        <div class="state-actions">
          <button class="btn btn-sm" type="button" @click="emit('retry')">重试</button>
        </div>
      </div>

      <div v-else-if="!items.length" class="state">
        <p class="state-title">{{ filtered ? '没有匹配的条目' : '知识库还是空的' }}</p>
        <p>{{ filtered ? '换个关键词或点左侧「全部条目」' : '点右上角「采集内容」开始' }}</p>
      </div>

      <ul v-else class="rows">
        <li v-for="item in items" :key="item.id">
          <button
            type="button"
            class="row"
            :class="{ on: item.id === activeId }"
            @click="emit('select', item.id)"
          >
            <span class="row-title">{{ item.title }}</span>
            <span class="row-meta">
              <StatusBadge :status="item.status" />
              <span v-if="item.category" class="row-cat">{{ item.category }}</span>
              <span class="row-time">{{ shortTime(item.created_at) }}</span>
            </span>
          </button>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.list-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--c-bg-1);
  border-right: 1px solid var(--c-border);
}

.list-toolbar {
  padding: var(--space-3) var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--c-border);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.search {
  position: relative;
}

.search .input {
  padding-right: var(--space-6);
}

.clear {
  position: absolute;
  right: var(--space-2);
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: none;
  color: var(--c-text-3);
  font-size: var(--fs-md);
  line-height: 1;
  padding: 0 var(--space-1);
}

.list-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  min-height: 24px;
}

.list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.list-body .state {
  min-height: 100%;
  justify-content: center;
}

.rows {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.row {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
}

.row:hover {
  background: var(--c-bg-0);
}

.row.on {
  background: var(--c-primary-soft);
  border-color: var(--c-primary-border);
}

.row-title {
  font-size: var(--fs-sm);
  line-height: var(--lh-title);
  color: var(--c-text-1);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.row-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.row-cat {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 80px;
}

.row-time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.skeletons {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.skeleton-row {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
</style>
