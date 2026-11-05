<script setup>
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api, friendlyMessage } from '../api/client'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'

const props = defineProps({
  itemId: { type: Number, required: true },
  note: { type: String, default: '' },
})
const emit = defineEmits(['saved'])

const toast = useToast()
const { setEditorDirty } = useUi()

marked.setOptions({ gfm: true, breaks: true })

const mode = ref('split')
const draft = ref(props.note || '')
const html = ref('')
const dirty = ref(false)
const saving = ref(false)

let renderTimer = null

const words = computed(() => draft.value.trim().length)

function render() {
  const source = draft.value || ''
  html.value = source ? DOMPurify.sanitize(marked.parse(source)) : ''
}

function scheduleRender() {
  clearTimeout(renderTimer)
  // M1 §6.9：防抖 500ms，不要每键入一次就渲染
  renderTimer = setTimeout(render, 500)
}

watch(draft, () => {
  dirty.value = draft.value !== (props.note || '')
  setEditorDirty(dirty.value)
  scheduleRender()
})

watch(
  () => props.note,
  (value) => {
    // 外部刷新（重新整理 / 切换条目）时，只有本地没有未保存修改才覆盖草稿
    if (!dirty.value && value !== draft.value) {
      draft.value = value || ''
      render()
    }
  }
)

function save() {
  if (saving.value) return
  saving.value = true
  api
    .patchItem(props.itemId, { structured_note: draft.value })
    .then((result) => {
      dirty.value = false
      setEditorDirty(false)
      emit('saved', result)
      toast.ok(`笔记已保存，重建 ${result.note_chunk_count} 个笔记片段`)
    })
    .catch((err) => toast.error(friendlyMessage(err)))
    .finally(() => {
      saving.value = false
    })
}

function onKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && event.key === 's') {
    event.preventDefault()
    save()
  }
}

function onBeforeUnload(event) {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => {
  render()
  window.addEventListener('beforeunload', onBeforeUnload)
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  clearTimeout(renderTimer)
  setEditorDirty(false)
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="editor">
    <div class="editor-bar">
      <div class="modes">
        <button
          v-for="item in [
            { key: 'edit', label: '编辑' },
            { key: 'preview', label: '预览' },
            { key: 'split', label: '分屏' },
          ]"
          :key="item.key"
          type="button"
          class="btn btn-sm"
          :class="mode === item.key ? 'btn-primary' : 'btn-ghost'"
          @click="mode = item.key"
        >
          {{ item.label }}
        </button>
      </div>

      <span class="words">{{ words }} 字</span>
      <span v-if="dirty" class="dirty">已修改 •</span>
      <button class="btn btn-sm btn-primary" type="button" :disabled="!dirty || saving" @click="save">
        {{ saving ? '保存中…' : '保存笔记' }}
      </button>
    </div>

    <div class="editor-body" :class="mode">
      <textarea
        v-show="mode !== 'preview'"
        v-model="draft"
        class="textarea pane"
        spellcheck="false"
        placeholder="# 一级标题&#10;&#10;## 小节&#10;- 要点"
      />
      <div v-show="mode !== 'edit'" class="preview pane">
        <div v-if="html" class="prose" v-html="html" />
        <p v-else class="preview-empty">左侧写 Markdown，这里实时预览</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.editor {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

.editor-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) 0 var(--space-3);
  border-bottom: 1px solid var(--c-border);
}

.modes {
  display: flex;
  gap: var(--space-1);
  padding: 2px;
  border-radius: var(--radius-sm);
  background: var(--c-bg-2);
}

.words {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.dirty {
  font-size: var(--fs-xs);
  color: var(--c-warning);
}

.editor-body {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: var(--space-3);
  padding-top: var(--space-3);
}

.editor-body.edit,
.editor-body.preview {
  grid-template-columns: 1fr;
}

.editor-body.split {
  grid-template-columns: 1fr 1fr;
}

.pane {
  min-height: 0;
  height: 100%;
  overflow-y: auto;
}

.textarea {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  line-height: 1.7;
  background: var(--c-bg-0);
  resize: none;
}

.preview {
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.preview-empty {
  margin: 0;
  color: var(--c-text-3);
  font-size: var(--fs-sm);
}
</style>
