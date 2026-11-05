<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { api, friendlyMessage, pollTask } from '../api/client'
import StatusBadge from './StatusBadge.vue'
import NoteEditor from './NoteEditor.vue'
import RawPane from './RawPane.vue'
import SummaryPane from './SummaryPane.vue'
import { useToast } from '../composables/useToast'
import { fullTime } from '../utils/format'

const props = defineProps({
  item: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['refresh', 'deleted'])

const toast = useToast()

const tab = ref('summary')
const organizing = ref(false)
let stopPolling = null

const TABS = [
  { key: 'summary', label: '摘要与要点' },
  { key: 'note', label: '结构化笔记' },
  { key: 'raw', label: '原文' },
]

const isPending = computed(() => props.item?.status !== 'ready')
const busy = computed(() => organizing.value || props.item?.status === 'organizing')

watch(
  () => props.item?.id,
  () => {
    tab.value = 'summary'
  }
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
  if (item.note_edited && !window.confirm('重新整理将覆盖你手动编辑过的笔记，确定继续？')) return

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
            toast.error(`整理失败：${task.error_msg || task.error_code || '未知原因'}`)
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

function remove() {
  const item = props.item
  if (!item) return
  if (!window.confirm(`删除「${item.title}」？其分块与题目会一并删除，无法恢复。`)) return
  api
    .deleteItem(item.id)
    .then(() => {
      toast.ok('已删除')
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
      <p class="state-title">从左侧选一条来读</p>
      <p>或点右上角「粘贴文本」加入新的内容</p>
    </div>

    <template v-else>
      <header class="detail-head">
        <h1 class="title">{{ item.title }}</h1>
        <div class="head-actions">
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
        <span class="time">{{ fullTime(item.created_at) }}</span>
      </div>

      <p v-if="item.truncated" class="truncated-note">原文超过 50,000 字符，整理时只采样前 40,000 字与末 10,000 字。</p>

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

        <RawPane v-show="tab === 'raw'" :text="item.raw_content" />
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

.title {
  flex: 1;
  font-size: var(--fs-xl);
  font-weight: 600;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
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
  background: #fdf3e3;
  color: var(--c-warning);
}

.time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.truncated-note {
  margin: var(--space-3) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: #fdf3e3;
  color: var(--c-warning);
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
  color: var(--c-primary);
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
