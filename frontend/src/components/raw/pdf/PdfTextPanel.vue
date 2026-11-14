<script setup>
/**
 * 原文页签右边：**当前这一页的文字**（T11.2 从 PdfView 拆出来，守 300 行）。
 *
 * 三条不许改：
 * - 永远和左边的页图同屏 —— 认错的字得**当场**看得出来，做成分开的页签就失效了。
 * - 行级置信度（`line_conf`）与文字逐行对齐，`< 0.85` 的行标黄；老识别结果没有行级
 *   数据时 `confs` 为空，一行都不标（宁可不说，也别乱标）。
 * - 命中段（`marks`）只在它自己那一页标 —— 用户滚到别的页还留着黄条，会指错地方。
 */
import { computed, nextTick, ref, watch } from 'vue'

import { api, friendlyMessage } from '../../../api/client'

const props = defineProps({
  itemId: { type: Number, required: true },
  pageNo: { type: Number, default: 1 },
  // 页签可见吗：不可见时一个字都不取（打开详情时不替用户预下 30 页文字）
  active: { type: Boolean, default: true },
  // {page, from, to}：命中段落在哪一页、该页文字按 \n 切后的行号范围（T11.2）
  marks: { type: Object, default: null },
})
// 把整页数据交给 PdfView：顶部那句「这一页可能有错（N 行认不准）」要用它算
const emit = defineEmits(['data'])

const LOW = 0.85
const box = ref(null)
const data = ref(null)
const loading = ref(false)
const error = ref('')
let seq = 0

async function load(pageNo) {
  const mine = ++seq
  loading.value = true
  error.value = ''
  try {
    const next = await api.getPage(props.itemId, pageNo)
    if (mine !== seq) return
    data.value = next
    emit('data', next)
  } catch (err) {
    if (mine !== seq) return
    data.value = null
    emit('data', null)
    error.value = friendlyMessage(err)
  } finally {
    if (mine === seq) loading.value = false
  }
}

watch(
  () => [props.itemId, props.pageNo, props.active],
  () => {
    if (!props.active) return
    load(props.pageNo)
  },
  { immediate: true }
)

const lines = computed(() => {
  const body = data.value?.text || ''
  const confs = data.value?.line_conf || []
  const hit = props.marks && props.marks.page === props.pageNo ? props.marks : null
  return body
    ? body.split('\n').map((text, index) => ({
        text,
        low: confs[index] != null && confs[index] < LOW,
        hit: !!hit && index >= hit.from && index <= hit.to,
      }))
    : []
})

async function scrollToHit() {
  await nextTick()
  const el = box.value?.querySelector('.line.hit')
  if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

// 文字是异步来的：等命中行渲染出来再滚，否则滚到的是上一页的位置
watch(lines, () => {
  if (props.marks && props.marks.page === props.pageNo) scrollToHit()
})
</script>

<template>
  <div ref="box" class="text">
    <p v-if="loading" class="state">正在取这一页…</p>
    <p v-else-if="error" class="state">{{ error }}</p>
    <template v-else-if="lines.length">
      <p
        v-for="(line, index) in lines"
        :key="index"
        class="line"
        :class="{ low: line.low, hit: line.hit }"
      >{{ line.text }}</p>
    </template>
    <p v-else class="state">这页没认出文字，可以对照页图看看。</p>
  </div>
</template>

<style scoped>
.text {
  min-height: 0;
  overflow: auto;
  padding-right: var(--space-2);
  font-family: var(--font-reading);
  font-size: 14px;
  line-height: 1.9;
  color: var(--c-text-2);
}

.line {
  margin: 0 0 2px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 认不准的行标黄：只给底色不改字色，读起来还是正文 */
.low {
  background: var(--c-warning-soft);
  border-radius: 3px;
}

/* 问答引用命中的那一段（T11.2）：与纯文本原文用同一个标记色 */
.hit {
  background: var(--c-mark);
  color: var(--c-text-1);
  border-radius: 3px;
  scroll-margin: 120px;
}

.state {
  margin: var(--space-3) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
