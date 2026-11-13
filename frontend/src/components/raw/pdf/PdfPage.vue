<script setup>
/**
 * 一页 PDF（T11.1）：**页图垫底、canvas 盖上**。
 *
 * 分层不是讲究：后端页图在识别时就落在盘上了（`GET file?page=n`），
 * 通常几十毫秒就能显示；pdf.js 还要解析文档、准备字体。先出图再换清晰版，
 * 首屏 1 秒才有硬保障，而 pdf.js 万一渲染失败，用户看到的也不是白框。
 *
 * 尺寸由父组件算好传进来（虚拟滚动要靠它排位置），这里只负责画 ——
 * `width/height` 是**布局尺寸**，canvas 的内部像素按 devicePixelRatio 放大，
 * 不然 Retina 上字是糊的。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  doc: { type: Object, default: null },
  pageNo: { type: Number, required: true },
  width: { type: Number, required: true },
  height: { type: Number, required: true },
  // 可见才画；滚出缓冲区就把画布释放掉（30 页全留内存 = 一张 A4 约 12 MB）
  visible: { type: Boolean, default: false },
  shotUrl: { type: String, default: '' },
})

const canvas = ref(null)
const shotOk = ref(true)
const drawn = ref(false)
const failed = ref(false)
let task = null
let seq = 0
let gone = false

function release() {
  seq += 1
  if (task) {
    task.cancel()
    task = null
  }
  drawn.value = false
  const el = canvas.value
  if (el) {
    el.width = 0
    el.height = 0
  }
}

async function draw() {
  if (!props.doc || !props.visible || !canvas.value) return
  const mine = ++seq
  try {
    const page = await props.doc.getPage(props.pageNo)
    if (mine !== seq || !canvas.value) return
    const base = page.getViewport({ scale: 1 })
    // 上限 2：4K 屏再往上翻倍只是多占内存，字早就清楚了
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const viewport = page.getViewport({ scale: (props.width / base.width) * dpr })
    const el = canvas.value
    el.width = Math.ceil(viewport.width)
    el.height = Math.ceil(viewport.height)
    task = page.render({ canvas: el, canvasContext: el.getContext('2d'), viewport })
    await task.promise
    if (mine !== seq) return
    drawn.value = true
    failed.value = false
  } catch (err) {
    if (gone || err?.name === 'RenderingCancelledException') return
    // 单页画不出来就留着页图，不弹错 —— 用户要的是读到这一页，不是看报错。
    // 但控制台要留一条：这类失败被界面吞掉后，排查时只剩「就是不出图」。
    console.warn(`[pdf] 第 ${props.pageNo} 页画不出来`, err)
    failed.value = true
  }
}

watch(
  () => [props.visible, props.doc, props.pageNo, props.width],
  () => {
    if (props.visible) draw()
    else release()
  },
  { immediate: true }
)

// **滚出来的页必须单独补这一次**：`immediate` 那次跑在 setup 里，`canvas` 还是 null，
// draw() 直接返回就再也不重来了 —— 表现是「第一页出来了，往下滚全是白纸」。
// 2026-11-13 实测踩到：首屏正好靠 doc 异步到位把 watcher 又触发了一遍，所以看不出来。
onMounted(() => {
  if (props.visible) draw()
})

onBeforeUnmount(() => {
  gone = true
  release()
})
</script>

<template>
  <div class="sheet" :style="{ width: `${width}px`, height: `${height}px` }">
    <img
      v-if="shotUrl && shotOk"
      class="shot"
      :src="shotUrl"
      :alt="`第 ${pageNo} 页`"
      loading="lazy"
      @error="shotOk = false"
    />
    <canvas ref="canvas" class="canvas" :class="{ in: drawn }" />
    <p v-if="!shotOk && !drawn" class="missing">
      <template v-if="!doc">这一页没有页图，看右边的文字就行。</template>
      <template v-else-if="failed">第 {{ pageNo }} 页画不出来，看右边的文字就行。</template>
      <template v-else>第 {{ pageNo }} 页还在画…</template>
    </p>
  </div>
</template>

<style scoped>
.sheet {
  position: relative;
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  box-shadow: var(--shadow-1, 0 1px 2px rgb(0 0 0 / 6%));
}

.shot,
.canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
}

.canvas {
  opacity: 0;
  transition: opacity 160ms ease-out;
}

.canvas.in {
  opacity: 1;
}

.missing {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: var(--space-4);
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  text-align: center;
}
</style>
