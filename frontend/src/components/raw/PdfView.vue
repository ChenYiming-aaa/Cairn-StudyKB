<script setup>
/**
 * PDF 原文（T11.1）：**左边整份连续滚动，右边跟着显示当前页的文字**。
 *
 * 两条不许改：
 * - 页图/画布与这一页的文字永远同屏 —— 这是「认错也看得出来」的保障，
 *   做成分开的两个标签页就失效了。连续滚动时右侧自动跟到当前页。
 * - 首屏不等解析：后端页图先显示（识别时已落在盘上），pdf.js 画好再盖上去。
 *   30 页的扫描件整份下完要好几秒，但第一页的页图几十毫秒就出来了。
 *
 * 这个文件只管「壳」：翻页、开原件、引用跳页。文字与标黄在 `pdf/PdfTextPanel.vue`，
 * 页的挂载与虚拟滚动在 `pdf/PdfScroller.vue`。
 *
 * pdf.js 打不开（文件坏了 / 用了不支持的加密）时退回「只看页图 + 文字」：
 * 用户要的是读到这一页，不是看一个报错页。
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'

import { api } from '../../api/client'
import PdfScroller from './pdf/PdfScroller.vue'
import PdfTextPanel from './pdf/PdfTextPanel.vue'
import { fallbackSizes, openPdf } from './pdf/usePdf'

const props = defineProps({
  itemId: { type: Number, required: true },
  // 原件总页数（`item.file.page_count`）；还没读出来时是 0，界面要说清楚
  pageCount: { type: Number, default: 0 },
  // 页签是否可见：不可见时不发请求，打开原文才取
  active: { type: Boolean, default: false },
  // {text, chunkId}：问答引用要落到的那一段（T11.2）
  focus: { type: Object, default: null },
})

const LOW = 0.85
const scroller = ref(null)
// **必须 shallowRef**：pdf.js 的文档对象里有私有字段（`#`），Vue 的 `ref` 会把它
// 包成深层 Proxy，之后读私有字段就抛 TypeError —— 表现是「一声不响地画不出来」。
// 2026-11-13 实测踩到，控制台连一条错都没有。
const doc = shallowRef(null)
const sizes = ref([])
const current = ref(1)
const opening = ref(false)
const pdfError = ref('')
// 右侧面板回报的整页数据：顶部那句「这一页可能有错」要靠它算
const pageData = ref(null)
// 引用命中段：{page, from, to}。**带 page** —— 翻到别的页就不能再标
const marks = ref(null)
let loaded = false

const total = computed(() => doc.value?.numPages || props.pageCount || sizes.value.length || 0)

async function open() {
  opening.value = true
  pdfError.value = ''
  try {
    const opened = await openPdf(`/api/knowledge/${props.itemId}/file`, {
      onSizes: (next) => {
        sizes.value = next
      },
    })
    doc.value = opened.doc
    sizes.value = opened.sizes
  } catch {
    // 退回页图模式：页数只有后端知道，尺寸按 A4 估
    pdfError.value = '这份 PDF 没能按原样画出来，页图和文字照样能看。'
    sizes.value = fallbackSizes(props.pageCount)
  } finally {
    opening.value = false
  }
}

function go(pageNo) {
  if (pageNo < 1 || (total.value && pageNo > total.value) || pageNo === current.value) return
  current.value = pageNo
}

function reset() {
  // destroy 是异步的，且可能在渲染进行中被调用：吞掉拒绝，别让控制台多一条
  // 「切换内容时的报错」，那对用户没有任何意义
  const prev = doc.value
  if (prev?.destroy) Promise.resolve(prev.destroy()).catch(() => {})
  doc.value = null
  sizes.value = []
  pageData.value = null
  marks.value = null
  current.value = 1
  pdfError.value = ''
  loaded = false
}

watch(
  () => props.itemId,
  () => {
    reset()
    if (props.active) {
      loaded = true
      open()
    }
  }
)

watch(
  () => props.active,
  (on) => {
    if (!on || loaded) return
    loaded = true
    open()
  },
  { immediate: true }
)

/**
 * 引用跳转（T11.2）：先问后端「这段字在第几页」，再翻过去，命中行交给右侧面板标黄。
 *
 * **必须 immediate**：从问答点进来时组件是刚挂载的，`focus` 在挂载前就设好了，
 * 非 immediate 的 watch 根本不会触发（纯文本原文那边同理）。
 */
watch(
  () => props.focus,
  async (target) => {
    marks.value = null
    if (!target) return
    if (!target.chunkId) {
      // 没有 chunk id（老接口 / 笔记）就只停在当前页，不做假定位
      scroller.value?.scrollToPage(current.value, true)
      return
    }
    // 落不到页不是错误（chunk 被重新整理删了 / 这页还没读出来），停在当前页即可
    // `hint` 是搜索词：chunk 跨页时按它落页才落在用户看的那一句上
    const hit = await api.locate(props.itemId, target.chunkId, target.hint).catch(() => null)
    if (!hit?.page_no) return
    const pageNo = Number(hit.page_no)
    marks.value = {
      page: pageNo,
      from: Number(hit.line_from) || 0,
      to: Number(hit.line_to) || 0,
    }
    if (pageNo !== current.value) current.value = pageNo
    else scroller.value?.scrollToPage(pageNo, true)
  },
  { immediate: true }
)

/** 行级置信度缺失（老数据 / 抽取页）时 confs 为空，所有行都不标 */
const lowCount = computed(() => {
  const confs = pageData.value?.line_conf || []
  return confs.filter((conf) => conf != null && conf < LOW).length
})

/** 页级平均分低 = 这页整体可疑；0 表示什么都没认出来，单独说 */
const pageSuspicious = computed(() => {
  const conf = pageData.value?.avg_conf
  return typeof conf === 'number' && conf > 0 && conf < LOW
})

onBeforeUnmount(reset)
</script>

<template>
  <div class="pdf-view">
    <div class="bar">
      <button class="btn btn-sm" type="button" :disabled="current <= 1" @click="go(current - 1)">上一页</button>
      <span class="pager">第 {{ current }} 页<template v-if="total"> / 共 {{ total }} 页</template></span>
      <button class="btn btn-sm" type="button" :disabled="!total || current >= total" @click="go(current + 1)">
        下一页
      </button>
      <span class="hint">整份在左边滚动，右边跟着当前页</span>
      <span v-if="lowCount || pageSuspicious" class="warn">
        这一页可能有错<template v-if="lowCount">（{{ lowCount }} 行认不准，已标黄）</template>，对照页图看看
      </span>
    </div>

    <p v-if="pdfError" class="tip">{{ pdfError }}</p>
    <p v-if="opening" class="tip">正在打开原件…</p>

    <div class="spread">
      <PdfScroller
        ref="scroller"
        v-model:current="current"
        :doc="doc"
        :sizes="sizes"
        :item-id="itemId"
      />

      <PdfTextPanel
        :item-id="itemId"
        :page-no="current"
        :active="active"
        :marks="marks"
        @data="pageData = $event"
      />
    </div>
  </div>
</template>

<style scoped>
.pdf-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
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

.hint {
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}

.warn {
  margin-left: auto;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
}

.tip {
  flex: none;
  margin: 0;
  padding: 0 var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

/* 左原件、右文字：各自滚动，谁长谁滚（窄屏自动上下紧邻） */
.spread {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: var(--space-4);
}

@media (max-width: 1100px) {
  .spread {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  }
}
</style>
