<script setup>
/**
 * 原文页签的**分派壳**（T9.10）：打开一看是那份文件，不是一坨文字。
 *
 *   pdf                  → PdfView（页图 + 该页文字，按页翻）
 *   docx                 → DocxView（后端净化过的版式 HTML）
 *   pptx                 → PptxView（逐页大纲：标题 / 要点 / 备注）
 *   png jpg jpeg webp    → ImageView（左原图、右识别文字）
 *   其余（txt md xlsx 或没有原件）→ TextRawPane（纯文本 + 问答定位高亮）
 *
 * 为什么按 `ext` 而不是按 `kind`：kind 是"内容是什么"（资料 / 试卷 / 图片），
 * 同一份资料可能是 docx 也可能是 pdf，而**能怎么渲染只取决于原件格式**。
 * xlsx 故意留在纯文本：它的"页"是虚拟的（整份算 1 页），没有版式可还原。
 *
 * `active` 是「原文页签现在可见吗」：不可见时一个请求都不发 ——
 * 30 页 PDF 的页图不该在打开详情时就开始下。
 */
import { computed } from 'vue'

import DocxView from './raw/DocxView.vue'
import ImageView from './raw/ImageView.vue'
import PdfView from './raw/PdfView.vue'
import PptxView from './raw/PptxView.vue'
import TextRawPane from './raw/TextRawPane.vue'

const props = defineProps({
  // 详情整条：需要 id（取页）、raw_content（纯文本回退）、file.ext / page_count（分派）
  item: { type: Object, default: null },
  // {text, key}：问答来源卡片跳转要定位的那一段
  focus: { type: Object, default: null },
  active: { type: Boolean, default: false },
})

const IMAGES = ['png', 'jpg', 'jpeg', 'webp']

const ext = computed(() => String(props.item?.file?.ext || '').toLowerCase())
const kind = computed(() => {
  if (ext.value === 'pdf') return 'pdf'
  if (ext.value === 'docx') return 'docx'
  if (ext.value === 'pptx') return 'pptx'
  if (IMAGES.includes(ext.value)) return 'image'
  return 'text'
})

// 原件还在读（占位正文）时，页图/页文字都还没有：让几个视图自己去说"还没有"，
// 这里不额外拦，否则会出现两层空态
const itemId = computed(() => Number(props.item?.id || 0))
const pageCount = computed(() => Number(props.item?.file?.page_count || 0))
</script>

<template>
  <div class="raw-pane">
    <div v-if="!item" class="state">从左侧选一条内容。</div>
    <PdfView v-else-if="kind === 'pdf'" :key="`pdf-${itemId}`" :item-id="itemId" :page-count="pageCount" :active="active" />
    <DocxView v-else-if="kind === 'docx'" :key="`docx-${itemId}`" :item-id="itemId" :active="active" />
    <PptxView v-else-if="kind === 'pptx'" :key="`pptx-${itemId}`" :item-id="itemId" :page-count="pageCount" :active="active" />
    <ImageView v-else-if="kind === 'image'" :key="`img-${itemId}`" :item-id="itemId" :active="active" />
    <TextRawPane v-else :text="item.raw_content || ''" :focus="focus" />
  </div>
</template>

<style scoped>
.raw-pane {
  height: 100%;
  min-height: 0;
  padding-top: var(--space-3);
}

.state {
  margin: var(--space-3) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
