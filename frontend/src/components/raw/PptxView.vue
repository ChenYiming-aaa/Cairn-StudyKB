<script setup>
/**
 * pptx 原文（T9.10）：一页幻灯片一张卡，按页翻。
 *
 * 一页幻灯片没有"版式图片"（抽取时不出页图），所以这里呈现的是**大纲**：
 * 标题 / 要点（带层级）/ 备注。层级信息来自抽取时保留的缩进（`- ` 前的空格），
 * 丢了它就只剩一坨平铺的文字，讲义的骨架就看不出来了。
 */
import { computed, nextTick, ref, watch } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { useLocate } from '../../composables/useFocus'

const props = defineProps({
  itemId: { type: Number, required: true },
  pageCount: { type: Number, default: 0 },
  active: { type: Boolean, default: false },
  // {text, chunkId}：问答引用要落到的那一页那一条（T11.2）
  focus: { type: Object, default: null },
})

const page = ref(1)
const data = ref(null)
const loading = ref(false)
const error = ref('')
let loaded = false

const total = computed(() => props.pageCount || data.value?.page_no || 0)

async function load(n) {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getPage(props.itemId, n)
  } catch (err) {
    data.value = null
    error.value = friendlyMessage(err)
  } finally {
    loading.value = false
  }
}

function go(n) {
  if (n < 1 || (total.value && n > total.value) || n === page.value) return
  page.value = n
  load(n)
}

watch(
  () => props.itemId,
  () => {
    page.value = 1
    data.value = null
    loaded = false
    if (props.active) {
      loaded = true
      load(1)
    }
  }
)

watch(
  () => props.active,
  (on) => {
    if (!on || loaded) return
    loaded = true
    load(page.value)
  },
  { immediate: true }
)

/**
 * 引用定位（T11.2）：先问后端落在第几页，翻过去，再把命中的那一条标出来。
 *
 * 一页幻灯片一屏，所以**不能只在当前页里找字** —— 目标常常在别的页上。
 * 页号由 `knowledge/{id}/locate` 给（它比对的是 `item_page.text`，与这里的大纲同源）。
 */
const marks = useLocate(() => props.itemId, () => props.focus)
const box = ref(null)

watch(
  marks,
  async (hit) => {
    if (!hit) return
    const moved = hit.page !== page.value
    page.value = hit.page
    // 页签没开时只记住页号：切过去时 `active` 的 watch 会用 `page.value` 去取
    if (!props.active || !moved) return
    await load(hit.page)
  },
  { immediate: true }
)

// 大纲渲染出来之后再滚：命中那一条是刚算出来的，早一步 DOM 里还没有它
// **必须写在 `outline` 之后** —— 写在前面会在 setup 阶段读未初始化的 const（TDZ）

/** 抽取出的大纲 → {title, blocks[], notes}。`- ` 前缀是抽取器约定的要点标记 */
const outline = computed(() => {
  const body = data.value?.text || ''
  if (!body.trim()) return { title: '', blocks: [], notes: '' }
  const lines = body.split('\n').filter((line) => line.trim())
  const noteAt = lines.findIndex((line) => line.startsWith('备注：'))
  const notes = noteAt >= 0 ? lines.slice(noteAt).join('\n').replace(/^备注：/, '') : ''
  const rest = noteAt >= 0 ? lines.slice(0, noteAt) : lines

  const blocks = []
  let title = ''
  for (const line of rest) {
    const bullet = /^(\s*)-\s+(.*)$/.exec(line)
    if (bullet) {
      blocks.push({ kind: 'bullet', level: Math.min(Math.floor(bullet[1].length / 2), 3), text: bullet[2] })
    } else if (!title && !blocks.length) {
      // 第一行非要点文字按标题排（抽取顺序里标题通常在最前）
      title = line.trim()
    } else {
      blocks.push({ kind: 'text', level: 0, text: line })
    }
  }
  // 命中段可能跨行（chunk 是拼回来的），只拿第一行去对 —— 对到哪一条就标哪一条
  const needle = (marks.value?.matched || '').split('\n')[0].trim()
  const hitText = needle.length >= 8 ? needle : ''
  return {
    title,
    blocks: blocks.map((block) => ({ ...block, hit: !!hitText && block.text.includes(hitText) })),
    notes,
  }
})

watch(outline, async () => {
  if (!marks.value) return
  await nextTick()
  box.value?.querySelector('.hit')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
})
</script>

<template>
  <div class="pptx-view">
    <div class="bar">
      <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
      <span class="pager">第 {{ page }} 页<template v-if="total"> / 共 {{ total }} 页</template></span>
      <button
        class="btn btn-sm"
        type="button"
        :disabled="!total || page >= total"
        @click="go(page + 1)"
      >下一页</button>
    </div>

    <p v-if="error" class="state">{{ error }}</p>
    <p v-else-if="loading" class="state">正在取这一页…</p>
    <div v-else-if="outline.title || outline.blocks.length || outline.notes" ref="box" class="slide">
      <h3 v-if="outline.title" class="slide-title">{{ outline.title }}</h3>
      <template v-for="(block, index) in outline.blocks" :key="index">
        <p v-if="block.kind === 'bullet'" class="bullet" :class="{ hit: block.hit }" :style="{ paddingLeft: `calc(var(--space-4) + ${block.level * 16}px)` }">{{ block.text }}</p>
        <p v-else class="para" :class="{ hit: block.hit }">{{ block.text }}</p>
      </template>
      <div v-if="outline.notes" class="notes">
        <p class="notes-label">备注</p>
        <p class="notes-body">{{ outline.notes }}</p>
      </div>
    </div>
    <p v-else class="state">这一页没有文字。</p>
  </div>
</template>

<style scoped>
.pptx-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  height: 100%;
  min-height: 0;
}

.bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.pager {
  font-variant-numeric: tabular-nums;
}

.slide {
  flex: 1;
  min-height: 0;
  overflow: auto;
  max-width: 74ch;
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
}

.slide-title {
  margin: 0 0 var(--space-3);
  font-family: var(--font-ui);
  font-size: var(--fs-lg);
  line-height: var(--lh-title);
  color: var(--c-text-1);
}

.bullet {
  position: relative;
  margin: 0 0 var(--space-1);
  padding-left: var(--space-4);
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  color: var(--c-text-2);
}

/* 项目符号用手画：中文列表用 `<ul>` 会带一层额外缩进，和层级偏移打架 */
.bullet::before {
  content: "·";
  position: absolute;
  left: var(--space-1);
  color: var(--c-text-3);
}

.para {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  color: var(--c-text-2);
  white-space: pre-wrap;
}

/* 问答引用命中的那一条（T11.2）：与纯文本原文同一个标记色 */
.hit {
  background: var(--c-mark);
  color: var(--c-text-1);
  border-radius: 3px;
  scroll-margin: 120px;
}

.notes {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--c-border);
}

.notes-label {
  margin: 0 0 var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.notes-body {
  margin: 0;
  font-family: var(--font-reading);
  font-size: var(--fs-md);
  line-height: 1.9;
  color: var(--c-text-2);
  white-space: pre-wrap;
}

.state {
  margin: var(--space-3) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
