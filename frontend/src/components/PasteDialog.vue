<script setup>
import { computed, ref, watch } from 'vue'

import { api, friendlyMessage } from '../api/client'

const props = defineProps({
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'created'])

const title = ref('')
const content = ref('')
const submitting = ref(false)
const errorText = ref('')

const words = computed(() => content.value.trim().length)
const canSubmit = computed(() => words.value > 0 && !submitting.value)

watch(
  () => props.open,
  (open) => {
    if (open) {
      title.value = ''
      content.value = ''
      errorText.value = ''
      submitting.value = false
    }
  }
)

function tryClose() {
  if (submitting.value) return
  if (content.value.trim() && !window.confirm('关闭后已粘贴的内容会丢失，确定关闭？')) return
  emit('close')
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  errorText.value = ''
  try {
    const payload = { raw_content: content.value }
    if (title.value.trim()) payload.title = title.value.trim()
    const result = await api.createItem(payload)
    emit('created', result)
  } catch (err) {
    errorText.value = friendlyMessage(err)
    submitting.value = false
  }
}
</script>

<template>
  <div v-if="open" class="mask" @click.self="tryClose" @keydown.esc="tryClose">
    <div class="dialog" role="dialog" aria-modal="true" aria-label="粘贴文本">
      <header class="dialog-head">
        <h2>粘贴文本</h2>
        <button class="btn btn-ghost btn-sm" type="button" @click="tryClose">关闭</button>
      </header>

      <div class="dialog-body">
        <label class="field">
          <span class="field-label">标题（可留空，整理后由 AI 生成）</span>
          <input v-model="title" class="input" type="text" maxlength="40" placeholder="可留空，整理时会自动生成标题" />
        </label>

        <label class="field">
          <span class="field-label">正文</span>
          <textarea
            v-model="content"
            class="textarea"
            rows="12"
            placeholder="把要整理的段落粘进来，800 字以上效果最好"
            autofocus
          />
        </label>

        <div class="dialog-foot">
          <span class="hint">{{ words }} 字</span>
          <span v-if="errorText" class="error">{{ errorText }}</span>
          <div class="grow" />
          <button class="btn" type="button" @click="tryClose">取消</button>
          <button class="btn btn-primary" type="button" :disabled="!canSubmit" @click="submit">
            {{ submitting ? '正在保存…' : '加入知识库' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(35, 33, 28, 0.32);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  z-index: 50;
}

.dialog {
  width: min(720px, 100%);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg-1);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  overflow: hidden;
}

.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--c-border);
}

.dialog-head h2 {
  font-size: var(--fs-lg);
}

.dialog-body {
  padding: var(--space-4) var(--space-6) var(--space-6);
  overflow: auto;
}

.field {
  display: block;
  margin-bottom: var(--space-4);
}

.field-label {
  display: block;
  margin-bottom: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.dialog-foot {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.grow {
  flex: 1;
}

.hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.error {
  font-size: var(--fs-xs);
  color: var(--c-danger);
}
</style>
