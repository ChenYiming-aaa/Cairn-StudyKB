<script setup>
/**
 * PDF 连续滚动区（T11.1）：**只挂可视页**。
 *
 * 做法是标准虚拟滚动：先把每页的布局高度算出来（宽度按容器宽、高度按原始比例），
 * 用一个撑开的总高占位，页面绝对定位在各自的 `top` 上，只有落在
 * 「视口上下各一屏」范围内的页才真的挂载 —— 30 页 A4 全量挂上就是 30 张
 * 约 12 MB 的位图，滚两下浏览器就开始吃力。
 *
 * 「当前页」= 视口上沿往下 1/4 处落在哪一页。比「露出面积最大」稳：
 * 两页交界处不会因为一像素的滚动来回跳。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api } from '../../../api/client'
import PdfPage from './PdfPage.vue'

const props = defineProps({
  doc: { type: Object, default: null },
  // [{width, height}]：每页原始尺寸（pt），比例用来算布局高度
  sizes: { type: Array, default: () => [] },
  itemId: { type: Number, default: 0 },
  current: { type: Number, default: 1 },
})
const emit = defineEmits(['update:current'])

const GAP = 14
const PAD = 12

const box = ref(null)
const width = ref(0)
const viewH = ref(0)
const scrollTop = ref(0)
let observer = null
let frame = 0

const dims = computed(() => {
  const inner = Math.max(160, width.value - PAD * 2)
  return props.sizes.map((size) => {
    const ratio = size.width > 0 ? size.height / size.width : 1.414
    return { w: inner, h: Math.round(inner * ratio) }
  })
})

const offsets = computed(() => {
  let y = PAD
  return dims.value.map((dim) => {
    const top = y
    y += dim.h + GAP
    return top
  })
})

const totalH = computed(() => {
  if (!dims.value.length) return 0
  const last = dims.value[dims.value.length - 1]
  return offsets.value[offsets.value.length - 1] + last.h + PAD
})

/** 只渲染视口上下各一屏；缓冲区取一屏高，快速滚动时不会看到大片空白 */
const range = computed(() => {
  const top = scrollTop.value - viewH.value
  const bottom = scrollTop.value + viewH.value * 2
  const out = []
  offsets.value.forEach((offset, index) => {
    const dim = dims.value[index]
    if (offset + dim.h >= top && offset <= bottom) out.push(index + 1)
  })
  return out
})

function shotUrl(pageNo) {
  // 走 api 客户端而不是手写 `/api/knowledge/...`：演示站（静态）要把这条地址换成本地页图，
  // 手写的 URL 不经 fetch，换不掉 —— 表现就是「页图全 404、只剩一句『这一页没有页图』」。
  return props.itemId ? api.pageImageUrl(props.itemId, pageNo) : ''
}

/** 当前读到哪一页：视口上沿往下 1/4 处 */
function pick() {
  const el = box.value
  if (!el || !offsets.value.length) return 1
  const line = el.scrollTop + Math.min(120, el.clientHeight * 0.25)
  let pageNo = 1
  offsets.value.forEach((offset, index) => {
    if (offset <= line) pageNo = index + 1
  })
  return Math.min(pageNo, offsets.value.length)
}

function onScroll() {
  if (frame) return
  frame = requestAnimationFrame(() => {
    frame = 0
    const el = box.value
    if (!el) return
    scrollTop.value = el.scrollTop
    const pageNo = pick()
    if (pageNo !== props.current) emit('update:current', pageNo)
  })
}

/** 滚到第 n 页（顶对齐）。上一页 / 下一页与引用跳转都走这里 */
function scrollToPage(pageNo, smooth = false) {
  const el = box.value
  if (!el || !offsets.value.length) return
  const index = Math.min(Math.max(1, pageNo), offsets.value.length) - 1
  el.scrollTo({ top: Math.max(0, offsets.value[index] - 4), behavior: smooth ? 'smooth' : 'auto' })
}

defineExpose({ scrollToPage })

function measure() {
  const el = box.value
  if (!el) return
  width.value = el.clientWidth
  viewH.value = el.clientHeight
  scrollTop.value = el.scrollTop
}

onMounted(() => {
  measure()
  observer = new ResizeObserver(measure)
  if (box.value) observer.observe(box.value)
  nextTick(() => scrollToPage(props.current))
})

onBeforeUnmount(() => {
  observer?.disconnect()
  if (frame) cancelAnimationFrame(frame)
})

// 外部指定了另一页（翻页按钮 / 引用跳转）：滚过去。
// 自己滚动引发的那次不走这里 —— `pick()` 已经等于 current，不会再滚一遍。
watch(
  () => props.current,
  (pageNo) => {
    if (pick() !== pageNo) scrollToPage(pageNo, true)
  }
)

// 逐页纠正尺寸会让偏移整体变化：纠正后重新对齐当前页，别让读者被挪走
watch(
  () => props.sizes,
  () => nextTick(() => scrollToPage(props.current))
)
</script>

<template>
  <div ref="box" class="scroller" @scroll.passive="onScroll">
    <div class="stack" :style="{ height: `${totalH}px` }">
      <div
        v-for="pageNo in range"
        :key="pageNo"
        class="slot"
        :style="{ top: `${offsets[pageNo - 1]}px` }"
      >
        <PdfPage
          :doc="doc"
          :page-no="pageNo"
          :width="dims[pageNo - 1].w"
          :height="dims[pageNo - 1].h"
          :visible="true"
          :shot-url="shotUrl(pageNo)"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.scroller {
  min-height: 0;
  overflow: auto;
  padding: 0 var(--space-2);
  background: var(--c-bg-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  scroll-behavior: auto;
}

.stack {
  position: relative;
  width: 100%;
}

.slot {
  position: absolute;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
}
</style>
