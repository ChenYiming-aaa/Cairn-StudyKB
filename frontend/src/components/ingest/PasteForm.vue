<script setup>
import { computed, reactive, ref } from 'vue'

import { api, friendlyMessage } from '../../api/client'

/**
 * 「粘贴文本」tab（T9.8）：从 `IngestPanel` 里搬出来的第一块。
 *
 * 它只负责一件事 —— 把一段文字变成一条内容。上传文件、抓网页都在别的 tab，
 * 所以这里没有进度条、没有轮询：`POST /api/knowledge` 是同步的，返回即成功。
 */
const emit = defineEmits(['created'])

const paste = reactive({ title: '', content: '' })
const submitting = ref(false)
const errorText = ref('')

const words = computed(() => paste.content.trim().length)
const canSubmit = computed(() => words.value > 0 && !submitting.value)

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  errorText.value = ''
  try {
    const payload = { raw_content: paste.content }
    if (paste.title.trim()) payload.title = paste.title.trim()
    emit('created', await api.createItem(payload))
  } catch (err) {
    errorText.value = friendlyMessage(err)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div>
    <label class="field">
      <span class="field-label">标题（可留空，整理后由模型生成）</span>
      <input
        v-model="paste.title"
        class="input"
        type="text"
        maxlength="40"
        placeholder="可留空，整理时会自动生成标题"
      />
    </label>
    <label class="field">
      <span class="field-label">正文</span>
      <textarea
        v-model="paste.content"
        class="textarea"
        rows="12"
        placeholder="粘贴正文，800 字以上整理效果更好"
        autofocus
      />
    </label>

    <div class="foot">
      <span class="hint">{{ words }} 字</span>
      <span v-if="errorText" class="error">{{ errorText }}</span>
      <div class="grow" />
      <button class="btn btn-primary" type="button" :disabled="!canSubmit" @click="submit">
        {{ submitting ? '正在保存…' : '加入知识库' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
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

.foot {
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
  color: var(--c-danger-ink);
}
</style>
