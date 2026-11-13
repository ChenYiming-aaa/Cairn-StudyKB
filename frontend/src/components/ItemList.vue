<script setup>
/**
 * 内容列表栏（T7.0 → T7.2 接入 SidePanel → T9.9 加勾选与批量移入）。
 *
 * - 宽度/折叠交给 SidePanel + useLayout（列宽 0 时整栏干净收起，不靠过渡样式兜）
 * - 搜索框留在顶部；空状态给「下一步」：一句话 + 最近 3 条 + 采集按钮
 * - 勾选态按 id 存，筛选变化时剔掉看不见的 id（否则会移走屏幕外的内容）
 */
import { ref, watch } from 'vue'

import SidePanel from './SidePanel.vue'
import BulkMoveBar from './list/BulkMoveBar.vue'
import ItemRow from './list/ItemRow.vue'
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
  // [{ id, name, item_count }]，用来显示每条属于哪个工作区、以及批量移入的下拉
  workspaces: { type: Array, default: () => [] },
})
const emit = defineEmits([
  'select', 'search', 'retry', 'organize-pending', 'select-recent', 'create', 'move',
])

const keyword = ref(props.q)
const picked = ref([])          // 勾中的 id
let timer = null

/** id → 名字。不做成 Map 是为了让模板里一行就能用（列表最多 50 条，线性找也不慢） */
function wsName(id) {
  if (!id) return ''
  return (props.workspaces || []).find((ws) => ws.id === id)?.name || ''
}

function toggle(id) {
  picked.value = picked.value.includes(id)
    ? picked.value.filter((x) => x !== id)
    : [...picked.value, id]
}

/** 批量移入：条自己只管「选哪些」，移到哪里由 BulkMoveBar 决定 */
function onBulkMove(workspaceId) {
  if (!picked.value.length) return
  emit('move', { ids: [...picked.value], workspaceId })
  picked.value = []
}

// 筛选换了以后，屏幕上没有的 id 不该还留着选中（会移走用户看不见的内容）
watch(
  () => props.items.map((item) => item.id).join(','),
  () => {
    const alive = new Set(props.items.map((item) => item.id))
    picked.value = picked.value.filter((id) => alive.has(id))
  }
)

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

    <BulkMoveBar
      v-if="picked.length"
      :count="picked.length"
      :workspaces="workspaces"
      @move="onBulkMove"
      @cancel="picked = []"
    />

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
        <ItemRow
          v-for="item in items"
          :key="item.id"
          :item="item"
          :active="item.id === activeId"
          :picked="picked.includes(item.id)"
          :ws-name="wsName(item.workspace_id)"
          @select="emit('select', $event)"
          @toggle="toggle"
        />
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
