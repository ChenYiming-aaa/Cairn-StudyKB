<script setup>
/**
 * 整理结果卡：把 organize 返回的六个字段按桌面版的版式摆出来。
 *
 * 为什么不用纯文本：演示的意义在于「看整理成什么样」。结构化笔记在桌面版里就是
 * Markdown 渲染出来的，这里必须一样，否则用户会以为产品只给一坨纯文本。
 */
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps({
  note: { type: Object, required: true },
})

marked.setOptions({ gfm: true, breaks: true })

const html = computed(() => {
  const src = props.note.structured_note || ''
  return src ? DOMPurify.sanitize(marked.parse(src)) : ''
})
</script>

<template>
  <article class="note">
    <h3 class="title">{{ note.title || '（没给标题）' }}</h3>
    <div class="meta">
      <span v-if="note.category" class="cat">{{ note.category }}</span>
      <span v-for="tag in note.tags" :key="tag" class="tag">{{ tag }}</span>
    </div>
    <p v-if="note.summary" class="summary">{{ note.summary }}</p>
    <ul v-if="note.key_points.length" class="points">
      <li v-for="(point, i) in note.key_points" :key="i">{{ point }}</li>
    </ul>
    <div v-if="html" class="body" v-html="html" />
    <p v-else class="empty">模型只给了上面这些，没写出笔记正文。</p>
  </article>
</template>

<style scoped>
.note {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-0);
  padding: var(--space-3) var(--space-4);
}

.title {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-lg);
  line-height: var(--lh-title);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-bottom: var(--space-2);
}

.cat {
  font-size: var(--fs-xs);
  color: var(--c-primary-ink);
  background: var(--c-primary-soft);
  border-radius: var(--radius-sm);
  padding: 1px var(--space-2);
}

.tag {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  padding: 1px var(--space-2);
}

.summary {
  margin: 0 0 var(--space-2);
  color: var(--c-text-1);
  line-height: var(--lh-body);
}

.points {
  margin: 0 0 var(--space-3);
  padding-left: var(--space-4);
  color: var(--c-text-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
}

.body {
  border-top: 1px dashed var(--c-border);
  padding-top: var(--space-3);
  font-family: var(--font-reading);
  line-height: var(--lh-body);
  color: var(--c-text-1);
}

.body :deep(h1) {
  font-size: var(--fs-lg);
  margin: var(--space-2) 0;
}

.body :deep(h2) {
  font-size: var(--fs-md);
  margin: var(--space-3) 0 var(--space-1);
}

.body :deep(h3) {
  font-size: var(--fs-sm);
  margin: var(--space-2) 0 var(--space-1);
}

.body :deep(ul) {
  padding-left: var(--space-4);
  margin: var(--space-1) 0;
}

.body :deep(p) {
  margin: var(--space-1) 0;
}

.empty {
  color: var(--c-text-3);
  font-size: var(--fs-sm);
  margin: 0;
}
</style>
