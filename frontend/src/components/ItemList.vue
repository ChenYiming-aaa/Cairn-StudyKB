<script setup>
/**
 * 条目列表栏（T7.0 原样保留 → T7.2 接入 SidePanel）。
 *
 * 三件事：
 * - 宽度/折叠交给 SidePanel + useLayout（列宽 0 时整栏干净收起，不再靠过渡样式兜）
 * - 搜索框留在顶部：位置不变，用户已经形成肌肉记忆
 * - 空状态给「下一步」：一句话 + 最近 3 条（点一条直接跳过去）+ 采集按钮
 */
import { ref, watch } from 'vue'

import SidePanel from './SidePanel.vue'
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
  // 最近采集的 3 条（不受当前筛选影响）：列表因筛选变空时用来「跳回去」
  recent: { type: Array, default: () => [] },
})
const emit = defineEmits(['select', 'search', 'retry', 'organize-pending', 'select-recent', 'create'])

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
  <SidePanel target="list" class="list-panel" title="内容列表">
    <div class="list-toolbar">
      <div class="search">
        <input
          v-model="keyword"
          class="input"
          type="search"
          placeholder="搜索标题"
          aria-label="搜索标题"
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
          {{ organizing ? '整理中…' : `开始整理 ${pendingCount} 条` }}
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
        <p class="state-title">列表没加载出来</p>
        <p>{{ error }}</p>
        <p>内容还在，重试一次通常就好。</p>
        <div class="state-actions">
          <button class="btn btn-sm" type="button" @click="emit('retry')">重试</button>
        </div>
      </div>

      <div v-else-if="!items.length" class="state">
        <p class="state-title">{{ filtered ? '没有匹配的内容' : '这里放你的内容' }}</p>
        <p>{{ filtered ? '换个关键词，或点左栏「全部内容」。' : '还没有采集过内容。' }}</p>

        <ul v-if="recent.length" class="recent">
          <li class="recent-label">最近采集的</li>
          <li v-for="item in recent" :key="item.id">
            <button class="recent-row" type="button" @click="emit('select-recent', item.id)">
              <span class="recent-title">{{ item.title }}</span>
              <span class="recent-time">{{ shortTime(item.created_at) }}</span>
            </button>
          </li>
        </ul>

        <button class="btn btn-primary btn-sm" type="button" @click="emit('create')">
          ＋ 采集内容
        </button>
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
  </SidePanel>
</template>

<style scoped>
/* 根节点是 SidePanel 的 .side-panel：背景与右边框它已经给了，这里只管内容排列。
   .list-panel 这个类同时是 <1000px 浮层化的 CSS 钩子（见 styles/app.css）。 */
.list-panel {
  min-height: 0;
}

.list-toolbar {
  flex: 0 0 auto;
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

/* 空态里有最近 3 条与按钮，垂直居中会把按钮推到屏幕外，改成从顶部排 */
.list-body .state {
  min-height: 100%;
  justify-content: flex-start;
  padding-top: var(--space-8);
}

.recent {
  width: 100%;
  list-style: none;
  margin: var(--space-3) 0 var(--space-4);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
}

.recent-label {
  padding: 0 var(--space-2) var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.recent-row {
  width: 100%;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.recent-row:hover {
  background: var(--c-bg-0);
  border-color: var(--c-border);
}

.recent-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-time {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
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
