<script setup>
/**
 * docx 原文（T9.10）：直接用抽取时生成的版式 HTML 渲染。
 *
 * 安全边界只有一条，不许破：**HTML 只来自后端**（`extractors/docx.py` 里
 * `renderer.sanitize()` 过一遍白名单），前端绝不拼接、绝不 `innerHTML` 拼字符串。
 * 后端没转出版式时退到纯文本，不是空白页 —— 用户要看的是内容，不是版式。
 */
import { computed, ref, watch } from 'vue'

import { api, friendlyMessage } from '../../api/client'

const props = defineProps({
  itemId: { type: Number, required: true },
  active: { type: Boolean, default: false },
})

const data = ref(null)
const loading = ref(false)
const error = ref('')
let loaded = false

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getPage(props.itemId, 1)
  } catch (err) {
    data.value = null
    error.value = friendlyMessage(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.itemId,
  () => {
    data.value = null
    loaded = false
    if (props.active) {
      loaded = true
      load()
    }
  }
)

watch(
  () => props.active,
  (on) => {
    if (!on || loaded) return
    loaded = true
    load()
  },
  { immediate: true }
)

// 后端给的是净化过的 HTML（唯一允许 v-html 的地方）
const html = computed(() => data.value?.html || '')
const text = computed(() => data.value?.text || '')
</script>

<template>
  <div class="docx-view">
    <p v-if="error" class="state">{{ error }}</p>
    <p v-else-if="loading" class="state">正在打开这份文件…</p>
    <div v-else-if="html" class="doc" v-html="html" />
    <pre v-else-if="text" class="fallback">{{ text }}</pre>
    <p v-else class="state">这份文件还没读出内容。</p>
  </div>
</template>

<style scoped>
.docx-view {
  height: 100%;
  overflow: auto;
  padding-right: var(--space-2);
}

/* 版式按"读文档"的长文排：限制行宽、正文用宋体 */
.doc {
  max-width: 74ch;
  font-family: var(--font-reading);
  font-size: 14px;
  line-height: 1.9;
  color: var(--c-text-2);
  overflow-wrap: break-word;
}

.doc :deep(h1),
.doc :deep(h2),
.doc :deep(h3) {
  margin: var(--space-4) 0 var(--space-2);
  font-family: var(--font-ui);
  font-size: var(--fs-lg);
  line-height: var(--lh-title);
  color: var(--c-text-1);
}

.doc :deep(p) {
  margin: 0 0 var(--space-2);
}

.doc :deep(ul),
.doc :deep(ol) {
  margin: 0 0 var(--space-2);
  padding-left: var(--space-6);
}

.doc :deep(li) {
  margin-bottom: var(--space-1);
}

/* 表格是讲义里最常见的结构，横向滚动而不是把列压扁 */
.doc :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: var(--space-3) 0;
  font-size: var(--fs-sm);
}

.doc :deep(th),
.doc :deep(td) {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--c-border);
  text-align: left;
  vertical-align: top;
}

.doc :deep(th) {
  background: var(--c-bg-1);
  color: var(--c-text-1);
}

.fallback {
  margin: 0;
  max-width: 74ch;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-reading);
  font-size: 14px;
  line-height: 1.9;
  color: var(--c-text-2);
}

.state {
  margin: var(--space-3) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
