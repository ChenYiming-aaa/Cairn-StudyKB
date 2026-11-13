<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { api, friendlyMessage, pollTask } from '../api/client'
import StatusBadge from './StatusBadge.vue'
import MindmapPane from './MindmapPane.vue'
import NoteEditor from './NoteEditor.vue'
import RawPane from './RawPane.vue'
import SessionLog from './SessionLog.vue'
import SummaryPane from './SummaryPane.vue'
import TitleEditor from './TitleEditor.vue'
import { useTheme } from '../composables/useTheme'
import { useTimer } from '../composables/useTimer'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'
import { fullTime } from '../utils/format'

const props = defineProps({
  item: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  // D-01：空态要分两种——"库里有内容但没选中" vs "库里一条都没有"，
  // 后者说"从左侧选一条"是死路。默认 true，避免首次加载瞬间误报"还没有内容"。
  hasItems: { type: Boolean, default: true },
  // [{ id, name }]：详情里那个「移到哪个工作区」的下拉（T9.9）
  workspaces: { type: Array, default: () => [] },
})
const emit = defineEmits(['refresh', 'deleted', 'create', 'move'])

const toast = useToast()
const { focusChunk } = useUi()
// 导图是后端现场出的 SVG，明暗得前端告诉它（T6.7）；让它自己判断会和界面脱节
const { theme, resolvedMode } = useTheme()

const tab = ref('summary')
const organizing = ref(false)
// 问答点 [n] 跳过来时定位的那一段：{text, key}。key 每次跳转都变，
// 目的是让 RawPane 即使跳的是同一段也能重新滚动一次。
const focus = ref(null)
let stopPolling = null

const TABS = [
  { key: 'summary', label: '摘要与要点' },
  { key: 'note', label: '整理笔记' },
  { key: 'raw', label: '原文' },
  { key: 'mindmap', label: '思维导图' },
  { key: 'sessions', label: '学习记录' },
]

// T5.3：从条目点「开始专注」，把这条件为目标带进计时（target_type=item）
const { start: startSession } = useTimer()

async function startFocus() {
  if (!props.item) return
  const created = await startSession({
    target_type: 'item',
    target_id: props.item.id,
    planned_seconds: 1500,
  })
  if (created) toast.info(`开始专注：${props.item.title}`)
}

const isPending = computed(() => props.item?.status !== 'ready')
const busy = computed(() => organizing.value || props.item?.status === 'organizing')

watch(
  () => props.item?.id,
  () => {
    tab.value = 'summary'
    focus.value = null
  }
)

/** 来源卡片跳转：条目换了也要生效，所以同时监听 item.id 与 focusChunk */
watch(
  () => [props.item?.id, focusChunk.value],
  () => {
    const target = focusChunk.value
    if (!target || !props.item || target.itemId !== props.item.id) return
    // 笔记片段在 textarea 里定位不到，只能切到对应 Tab 让用户自己看
    tab.value = target.source === 'note' ? 'note' : 'raw'
    focus.value = target.source === 'note' ? null : { text: target.text, key: Date.now() }
    focusChunk.value = null
  },
  { immediate: true }
)

function stop() {
  if (stopPolling) {
    stopPolling()
    stopPolling = null
  }
}

function organize() {
  const item = props.item
  if (!item || busy.value) return
  // 数据契约 §3：note_edited=1 时重新整理会覆盖手改内容，必须先确认
  if (item.note_edited && !window.confirm('重新整理会覆盖你手改过的笔记，并按正文重新生成标题。继续？')) return

  organizing.value = true
  api
    .organize(item.id)
    .then((res) => {
      stopPolling = pollTask(res.task_id, {
        onUpdate: (task) => {
          if (task.status === 'done') {
            stop()
            organizing.value = false
            toast.ok('整理完成')
            emit('refresh', item.id)
          } else if (task.status === 'failed') {
            stop()
            organizing.value = false
            toast.error(`这次没整理成功：${task.error_msg || task.error_code || '原因没记下来'}。点「重新整理」再试一次；还不行去任务中心看原因。`)
            emit('refresh', item.id)
          }
        },
      })
    })
    .catch((err) => {
      organizing.value = false
      toast.error(friendlyMessage(err))
      emit('refresh', item.id)
    })
}

/** 详情里的下拉：改这一条的位置。空串 = 未归类（PATCH 里 null 就是「移出工作区」） */
function onWorkspaceChange(event) {
  const value = event.target.value
  emit('move', {
    id: props.item.id,
    workspaceId: value === '' ? null : Number(value),
  })
}

function remove() {
  const item = props.item
  if (!item) return
  if (!window.confirm(`删除「${item.title}」？它的笔记片段、题目、作答记录和专注记录会一起删掉，不能恢复。`)) return
  api
    .deleteItem(item.id)
    .then(() => {
      toast.ok('已删除这条')
      emit('deleted', item.id)
    })
    .catch((err) => toast.error(friendlyMessage(err)))
}

function onNoteSaved() {
  emit('refresh', props.item.id)
}

onBeforeUnmount(stop)
</script>

<template>
  <section class="detail">
    <div v-if="loading" class="detail-loading">
      <div v-for="w in ['45%', '80%', '70%', '60%']" :key="w" class="skeleton" :style="{ width: w }" />
    </div>

    <div v-else-if="error" class="detail-state">
      <p class="state-title">详情加载失败</p>
      <p class="state-error">{{ error }}</p>
      <button class="btn btn-sm" type="button" @click="emit('refresh', item?.id)">重试</button>
    </div>

    <div v-else-if="!item" class="detail-state state">
      <template v-if="hasItems">
        <p class="state-title">这里放你的摘要、笔记和原文</p>
        <p>从左侧选一条开始读。</p>
      </template>
      <template v-else>
        <p class="state-title">这里放你的内容</p>
        <p>还没有采集过内容。</p>
        <button class="btn btn-sm" type="button" @click="emit('create')">＋ 采集内容</button>
      </template>
    </div>

    <template v-else>
      <header class="detail-head">
        <TitleEditor :item-id="item.id" :title="item.title" :disabled="busy" @saved="emit('refresh', item.id)" />
        <div class="head-actions">
          <button class="btn btn-sm" type="button" @click="startFocus">开始专注</button>
          <button class="btn btn-sm" type="button" :disabled="busy" @click="organize">
            {{ busy ? '整理中…' : isPending ? '开始整理' : '重新整理' }}
          </button>
          <button class="btn btn-sm btn-danger" type="button" @click="remove">删除</button>
        </div>
      </header>

      <div class="meta">
        <StatusBadge :status="item.status" />
        <span v-if="item.category" class="chip">{{ item.category }}</span>
        <span v-for="tag in item.tags" :key="tag" class="chip chip-tag">#{{ tag }}</span>
        <span v-if="item.note_edited" class="chip chip-edit" title="整理会覆盖手改内容">笔记已手改</span>
        <select
          class="ws-pick"
          aria-label="移到哪个工作区"
          :value="item.workspace_id ? String(item.workspace_id) : ''"
          @change="onWorkspaceChange"
        >
          <option value="">未归类</option>
          <option v-for="ws in workspaces" :key="ws.id" :value="String(ws.id)">{{ ws.name }}</option>
        </select>
        <span class="time">{{ fullTime(item.created_at) }}</span>
      </div>

      <p v-if="item.truncated" class="truncated-note">原文超过 5 万字，整理时只读开头 4 万字和结尾 1 万字；原文完整保留，不受影响。</p>

      <nav class="tabs">
        <button
          v-for="entry in TABS"
          :key="entry.key"
          type="button"
          class="tab"
          :class="{ on: tab === entry.key }"
          @click="tab = entry.key"
        >
          {{ entry.label }}
        </button>
      </nav>

      <div class="detail-body">
        <SummaryPane v-show="tab === 'summary'" :item="item" />

        <div v-show="tab === 'note'" class="pane pane-note">
          <NoteEditor :key="item.id" :item-id="item.id" :note="item.structured_note || ''" @saved="onNoteSaved" />
        </div>

        <!-- T9.10：原文按原件格式分派（PDF 页图、Word 版式、PPT 大纲、图片对照）；
             active 传下去，页签没打开时不发任何取页请求 -->
        <RawPane v-show="tab === 'raw'" :item="item" :focus="focus" :active="tab === 'raw'" />

        <MindmapPane
          v-if="tab === 'mindmap'"
          :item-id="item.id"
          :updated-at="item.updated_at || ''"
          :theme="theme"
          :mode="resolvedMode"
        />

        <!-- v-if 而非 v-show：每次切进来都重新拉一次，刚结束的一轮立刻能看到 -->
        <SessionLog v-if="tab === 'sessions'" :item-id="item.id" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  padding: var(--space-4) var(--space-6) 0;
  background: var(--c-bg-0);
}

.detail-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-height: 0;
  padding-bottom: var(--space-8);
}

.detail-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-6) 0;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
}

.head-actions {
  display: flex;
  gap: var(--space-2);
  padding-top: 2px;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.chip {
  padding: 1px var(--space-2);
  border-radius: 999px;
  background: var(--c-bg-2);
  color: var(--c-text-2);
}

.chip-tag {
  background: transparent;
  border: 1px solid var(--c-border);
  color: var(--c-text-3);
}

.chip-edit {
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
}

.ws-pick {
  max-width: 140px;
  padding: 1px var(--space-1);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
}

.time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.truncated-note {
  margin: var(--space-3) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
}

.tabs {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-4);
  border-bottom: 1px solid var(--c-border);
}

.tab {
  padding: var(--space-2) 0;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  margin-bottom: -1px;
}

.tab:hover {
  color: var(--c-text-1);
}

.tab.on {
  color: var(--c-primary-ink);
  border-bottom-color: var(--c-primary);
  font-weight: 600;
}

.pane-note {
  display: flex;
  flex-direction: column;
}

.detail-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-bottom: var(--space-4);
}

</style>
