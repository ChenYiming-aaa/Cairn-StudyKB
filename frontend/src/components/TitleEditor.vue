<script setup>
import { nextTick, ref } from 'vue'

import { api, friendlyMessage } from '../api/client'
import { useToast } from '../composables/useToast'

const props = defineProps({
  itemId: { type: Number, required: true },
  title: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['saved'])

const MAX = 20 // 与整理 Agent 同一口径（2026-11-06 裁决）
const toast = useToast()
const editing = ref(false)
const draft = ref('')
const saving = ref(false)
const inputEl = ref(null)

async function start() {
  if (props.disabled || saving.value) return
  draft.value = props.title
  editing.value = true
  await nextTick()
  inputEl.value?.focus()
  inputEl.value?.select()
}

function cancel() {
  if (saving.value) return
  editing.value = false
}

async function save() {
  if (saving.value || !editing.value) return
  const next = draft.value.trim()
  if (!next) return cancel()
  if (next === props.title) return cancel()
  if (next.length > MAX) return toast.error(`标题最多 ${MAX} 个字，请先截短`)
  saving.value = true
  try {
    await api.patchItem(props.itemId, { title: next })
    editing.value = false
    toast.ok('标题已更新')
    emit('saved', next)
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="title-wrap">
    <input
      v-if="editing"
      ref="inputEl"
      v-model="draft"
      class="title-input"
      type="text"
      :maxlength="MAX"
      :disabled="saving"
      @keyup.enter="save"
      @keyup.esc="cancel"
      @blur="save"
    />
    <h1 v-else class="title" :title="title" @dblclick="start">{{ title }}</h1>

    <button v-if="!editing" class="edit" type="button" :disabled="disabled" title="改标题（双击标题也行）" @click="start">改</button>
    <span v-else class="count">{{ draft.length }}/{{ MAX }} · 回车保存</span>
  </div>
</template>

<style scoped>
.title-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  gap: var(--space-2);
}

.title {
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  font-size: var(--fs-xl);
  font-weight: 600;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  cursor: text;
}

.title-input {
  flex: 1;
  min-width: 0;
  font-family: inherit;
  font-size: var(--fs-xl);
  font-weight: 600;
  color: var(--c-text-1);
  background: var(--c-bg-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  padding: 2px var(--space-2);
}

.edit {
  flex: none;
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  background: none;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  padding: 1px 6px;
  cursor: pointer;
}

.edit:hover {
  color: var(--c-text-1);
}

.count {
  flex: none;
  margin-top: 8px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  white-space: nowrap;
}
</style>
