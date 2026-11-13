<script setup>
/**
 * 工作区区块（T9.9）。左栏最上面那一段，和下面的「分类」是**两件事**：
 *
 * - 工作区是**用户自己划的抽屉**（「数据结构」「英语二」），内容只能在一个抽屉里；
 * - 分类是**机器读完给的归类**，一条内容只有一个分类。
 *
 * 所以两段必须视觉上分开（分隔线 + 不同字重），否则用户会以为是一棵树的上下两级。
 * 「全部」「未归类」是固定项，不在这份列表里（未归类 = `workspace_id IS NULL`，
 * 后端用哨兵值 `"none"` 表达，不用 0）。
 *
 * 计数一律用后端给的 `item_count` / `none_count`，前端不自己数 —— 列表只加载 50 条，
 * 自己数会偏低（M1 的已知限制，后来改由 SQL 聚合）。
 */
import { computed, nextTick, ref } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { useToast } from '../../composables/useToast'
import WorkspaceRow from './WorkspaceRow.vue'

const props = defineProps({
  // [{ id, name, color, sort_order, item_count }]
  workspaces: { type: Array, default: () => [] },
  // '' = 全部 | 'none' = 未归类 | number = 某个工作区
  active: { type: [Number, String], default: '' },
  noneCount: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
})
const emit = defineEmits(['select', 'changed'])

const toast = useToast()
const NAME_MAX = 20

const draft = ref('')
const editingId = ref(null)      // 正在改名的工作区 id；-1 = 正在新建
const busy = ref(false)
const newRef = ref(null)

const rows = computed(() => [
  { key: '', name: '全部', count: props.total },
  ...props.workspaces.map((ws) => ({ key: ws.id, name: ws.name, count: ws.item_count, ws })),
  { key: 'none', name: '未归类', count: props.noneCount },
])

function pick(key) {
  if (editingId.value !== null) return
  emit('select', key)
}

async function startNew() {
  editingId.value = -1
  draft.value = ''
  await nextTick()
  newRef.value?.focus?.()
}

function cancel() {
  editingId.value = null
  draft.value = ''
}

async function create() {
  const name = draft.value.trim()
  if (!name || busy.value) return
  if (name.length > NAME_MAX) {
    toast.error(`名字最多 ${NAME_MAX} 个字`)
    return
  }
  busy.value = true
  try {
    const created = await api.createWorkspace({ name })
    cancel()
    emit('changed')
    emit('select', created.id)     // 新建完直接切进去，省一次点击
    toast.ok(`建好了「${created.name}」`)
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    busy.value = false
  }
}

async function saveName(name) {
  if (busy.value || editingId.value === null) return
  busy.value = true
  try {
    await api.patchWorkspace(editingId.value, { name })
    cancel()
    emit('changed')
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    busy.value = false
  }
}

async function remove(ws) {
  const inside = ws.item_count > 0 ? `里面的 ${ws.item_count} 条内容会回到「未归类」，` : ''
  if (!window.confirm(`删除工作区「${ws.name}」？${inside}内容本身不会被删掉。`)) return
  try {
    await api.deleteWorkspace(ws.id)
    // 正在看的就是被删的那个 → 回到「全部」，否则列表会停在一条空结果上
    if (props.active === ws.id) emit('select', '')
    emit('changed')
    toast.ok('工作区已删除，内容都还在')
  } catch (err) {
    toast.error(friendlyMessage(err))
  }
}
</script>

<template>
  <section class="ws">
    <div class="ws-head">
      <span class="ws-title">工作区</span>
      <button class="add" type="button" aria-label="新建工作区" title="新建工作区" @click="startNew">
        ＋
      </button>
    </div>

    <div v-if="editingId === -1" class="editor">
      <input
        ref="newRef"
        v-model="draft"
        class="input input-sm"
        :maxlength="NAME_MAX"
        placeholder="工作区名字"
        aria-label="工作区名字"
        @keydown.enter="create"
        @keydown.esc="cancel"
      />
      <button class="btn btn-sm" type="button" :disabled="busy" @click="create">建好</button>
    </div>

    <ul class="ws-list">
      <WorkspaceRow
        v-for="row in rows"
        :key="row.key || 'all'"
        :row="row"
        :active="active === row.key"
        :editing="editingId !== null && editingId === row.key"
        @select="pick"
        @rename="editingId = $event.id"
        @save="saveName"
        @cancel="cancel"
        @remove="remove"
      />
    </ul>

    <p v-if="!workspaces.length" class="ws-hint">
      建一个工作区，把「数据结构」「英语二」这类内容分开放。
    </p>
  </section>
</template>

<style scoped>
.ws {
  padding: var(--space-2) var(--space-1) var(--space-2);
  border-bottom: 1px solid var(--c-border);
}

.ws-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-2);
}

.ws-title {
  font-size: var(--fs-xs);
  letter-spacing: 0.06em;
  color: var(--c-text-2);
  font-weight: 600;
}

.add {
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-3);
  font-size: var(--fs-sm);
  line-height: 1;
}

.add:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.ws-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.editor {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
}

.input-sm {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-sm);
  padding: var(--space-1) var(--space-2);
}

.ws-hint {
  margin: var(--space-2) var(--space-2) 0;
  font-size: var(--fs-xs);
  line-height: 1.7;
  color: var(--c-text-3);
}
</style>
