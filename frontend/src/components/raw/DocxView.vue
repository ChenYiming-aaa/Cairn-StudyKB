<script setup>
/**
 * docx 原文（T9.10）：直接用抽取时生成的版式 HTML 渲染。
 *
 * 安全边界只有一条，不许破：**HTML 只来自后端**（`extractors/docx.py` 里
 * `renderer.sanitize()` 过一遍白名单），前端绝不拼接、绝不 `innerHTML` 拼字符串。
 * 后端没转出版式时退到纯文本，不是空白页 —— 用户要看的是内容，不是版式。
 */
import { computed, nextTick, ref, watch } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { highlightIn } from '../../composables/useFocus'

const props = defineProps({
  itemId: { type: Number, required: true },
  active: { type: Boolean, default: false },
  // {text, chunkId}：问答引用要落到的那一段（T11.2）—— Word 没有页可翻，靠文字定位
  focus: { type: Object, default: null },
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

const doc = ref(null)

/**
 * 引用定位（T11.2）：版式出来之后在 DOM 里找那段话。
 *
 * **必须等 `html` 真的挂上**：`focus` 在挂载前就设好了，早跑一次容器还是空的，
 * 之后就再没有触发点了（PDF 那边踩过同一个坑）。
 */
watch(
  [html, () => props.focus],
  async () => {
    if (!html.value || !props.focus) return
    await nextTick()
    highlightIn(doc.value, props.focus.text, props.focus.hint)
  },
  { immediate: true }
)
</script>

<template>
  <div class="docx-view">
    <p v-if="error" class="state">{{ error }}</p>
    <p v-else-if="loading" class="state">正在打开这份文件…</p>
    <div v-else-if="html" ref="doc" class="doc" v-html="html" />
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

/* 内嵌图片（T11.3）：按正文宽度收着放，别让 1600 px 的图把行宽撑爆 */
.doc :deep(img) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: var(--space-3) 0;
  border-radius: var(--radius-sm);
  border: 1px solid var(--c-border);
  background: var(--c-bg-1);
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
