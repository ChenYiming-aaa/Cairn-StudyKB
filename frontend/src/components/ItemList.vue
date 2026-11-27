<script setup>
/**
 * 内容列表栏（T7.0 → T7.2 接入 SidePanel → T9.9 加勾选与批量移入；v0.5 重做视觉）。
 *
 * - 宽度/折叠交给 SidePanel + useLayout（列宽 0 时整栏干净收起，不靠过渡样式兜）
 * - 搜索框留在顶部；空状态给「下一步」：一句话 + 最近 3 条 + 采集按钮
 * - 勾选态按 id 存，筛选变化时剔掉看不见的 id（否则会移走屏幕外的内容）
 *
 * v0.5 的改动只在表现层，props / emits / 交互一个没动：
 * 1. 搜索框从裸 input 换成「图标 + 可清空」的一体输入，清空按钮从 `×` 字符换成图标。
 * 2. 空态与错误态改用统一的 EmptyState，出路不再是一段灰字里夹一个链接。
 * 3. 骨架屏改成与真实行同构的三行（标题 + 元信息），内容到达时不再整块跳动。
 */
import { ref, watch } from 'vue'

import SidePanel from './SidePanel.vue'
import BulkMoveBar from './list/BulkMoveBar.vue'
import ItemRow from './list/ItemRow.vue'
import Button from '../ui/Button.vue'
import EmptyState from '../ui/EmptyState.vue'
import Icon from '../ui/Icon.vue'
import Skeleton from '../ui/Skeleton.vue'
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
  // { done, total }：批量移入进行中。按钮要靠它禁用并显示进度
  moving: { type: Object, default: null },
})
const emit = defineEmits([
  'select', 'search', 'retry', 'organize-pending', 'select-recent', 'create', 'move',
  // 「只搜标题」提示里的出路（2026-11-17）：本组件不碰路由，交给 Knowledge 跳检索页
  'open-search',
])

const keyword = ref(props.q)
// 勾选态由父级持有（H4）：移入失败的那几条要留在勾选里，而「清空」必须等结果回来
// 才做 —— 子组件自己拿着就只能同帧清空，失败项再也找不回来
const picked = defineModel('picked', { type: Array, default: () => [] })
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

/** 批量移入：条自己只管「选哪些」，移到哪里由 BulkMoveBar 决定。
    清空不在这里做 —— 等父级拿到结果，成功的剔掉、失败的留着，见 Knowledge.onMoveItems */
function onBulkMove(workspaceId) {
  if (!picked.value.length || props.moving) return
  emit('move', { ids: [...picked.value], workspaceId })
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
      <!-- 搜索：图标在左、清空在右，标签对屏幕阅读器可见即可（搜索框的用途由占位符与图标共同表达） -->
      <div class="search">
        <Icon name="search" :size="16" class="search-icon" />
        <input
          v-model="keyword"
          class="input search-input"
          type="search"
          placeholder="搜索标题"
          aria-label="搜索标题"
          @input="onInput"
        />
        <button
          v-if="keyword"
          class="search-clear"
          type="button"
          title="清空"
          aria-label="清空搜索"
          @click="clearKeyword"
        >
          <Icon name="x" :size="16" />
        </button>
      </div>

      <div class="list-meta">
        <span class="list-count">{{ total }} 条{{ filtered ? '（已筛选）' : '' }}</span>
        <Button
          v-if="pendingCount > 0"
          variant="ghost"
          size="sm"
          :loading="organizing"
          @click="emit('organize-pending')"
        >
          {{ organizing ? '整理中…' : `开始整理 ${pendingCount} 条` }}
        </Button>
      </div>
    </div>

    <!-- 后端单次最多给 50 条，界面却按全量措辞显示总数：不说明的话，用户会以为
         「第 51 条之后没导进来」或者「丢了」，而这两件事他在界面上都证伪不了 -->
    <p v-if="total > items.length" class="list-truncated">
      显示前 {{ items.length }} 条 / 共 {{ total }} 条
    </p>

    <BulkMoveBar
      v-if="picked.length"
      :count="picked.length"
      :workspaces="workspaces"
      :busy="Boolean(moving)"
      :progress="moving"
      @move="onBulkMove"
      @cancel="picked = []"
    />

    <div class="list-body">
      <!-- 骨架与真实行同构：两行文字 + 一行元信息 -->
      <div v-if="loading && !items.length" class="skeletons">
        <div v-for="i in 5" :key="i" class="skeleton-item">
          <Skeleton variant="text" width="72%" :index="i" />
          <Skeleton variant="text" width="44%" height="10px" :index="i" />
        </div>
      </div>

      <EmptyState
        v-else-if="error"
        icon="alert"
        title="列表没加载出来"
        :description="`${error}。内容还在，重试一次通常就好。`"
      >
        <Button size="sm" icon="refresh" @click="emit('retry')">重试</Button>
      </EmptyState>

      <template v-else-if="!items.length">
        <!-- 搜了词却没结果：标题说的是「标题里」，出路就在下一行，不再另起一段解释
             「这个框只搜标题」——2026-11-22 把那一整段（SearchScopeHint）并进这里。 -->
        <EmptyState
          :icon="filtered ? 'search' : 'inbox'"
          :title="filtered ? `标题里没有「${keyword}」` : '这里放你的内容'"
          :description="filtered ? '' : '还没有采集过内容。粘一条链接、传一个文件，或者记一段笔记，整理之后就在这里了。'"
          compact
        >
          <!-- 按钮与前面的字写在一行：跨行会在「或者」和链接之间留一个空格，中文里不该有 -->
          <span v-if="filtered" class="empty-inline">
            换个词，或者<button class="link-btn" type="button" @click="emit('open-search')">去检索正文</button>
          </span>
          <Button v-else variant="primary" size="sm" icon="plus" @click="emit('create')">
            采集内容
          </Button>
        </EmptyState>

        <ul v-if="recent.length" class="recent">
          <li class="recent-label">最近采集的</li>
          <li v-for="item in recent" :key="item.id">
            <button class="recent-row" type="button" @click="emit('select-recent', item.id)">
              <span class="recent-title">{{ item.title }}</span>
              <span class="recent-time">{{ shortTime(item.created_at) }}</span>
            </button>
          </li>
        </ul>
      </template>

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
  padding: var(--space-3);
  border-bottom: 1px solid var(--c-border);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* ── 搜索框 ── */
.search {
  position: relative;
  display: flex;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: var(--space-3);
  color: var(--c-text-3);
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding-left: calc(var(--space-3) + 16px + var(--space-2));
  padding-right: var(--space-8);
}

.search-input::-webkit-search-cancel-button {
  display: none;
}

.search-clear {
  position: absolute;
  right: var(--space-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--c-text-3);
  cursor: pointer;
}

.search-clear:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.search-clear:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* ── 计数行 ── */
.list-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-height: 28px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.list-count {
  font-variant-numeric: tabular-nums;
}

.list-truncated {
  flex: 0 0 auto;
  margin: 0;
  padding: var(--space-1) var(--space-3);
  border-bottom: 1px solid var(--c-border);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.list-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

/* ── 空态里的行内出路 ── */
.empty-inline {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

/* ── 最近采集 ── */
.recent {
  width: 100%;
  list-style: none;
  margin: 0 0 var(--space-4);
  padding: 0 var(--space-2);
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
  font-family: var(--font-ui);
  font-size: var(--fs-sm);
  color: var(--c-text-1);
  cursor: pointer;
}

.recent-row:hover {
  background: var(--c-bg-0);
  border-color: var(--c-border);
}

.recent-row:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
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

/* ── 行列表 ── */
.rows {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* ── 骨架 ── */
.skeletons {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.skeleton-item {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
</style>
