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
import { useLocate } from '../../composables/useFocus'
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
/**
 * 读到第几页，按内容记住（H3）。
 *
 * 详情区被骨架屏替换 / 刷新页面 / 切走再回来，本组件都会重挂，而 `reset()` 会把 `current`
 * 打回 1 —— 读者刚看到第 40 页，被挪回第 1 页。这里用模块级 Map 记页码：不落盘，
 * 因为「这次打开应用读到哪里」就够了；页高随窗口变，只有页码是稳定的锚。
 */
const PAGE_MEMORY = new Map()
const current = ref(PAGE_MEMORY.get(props.itemId) || 1)
const opening = ref(false)
const pdfError = ref('')
// 右侧面板回报的整页数据：顶部那句「这一页可能有错」要靠它算
const pageData = ref(null)
// 引用命中段：{page, from, to, matched}。**带 page** —— 翻到别的页就不能再标。
// 问后端「这段字在第几页」那段与 Word/PPT/图片共用 `useLocate`，别在这里再写一遍：
// 各写一份的结果是这里少了 `matched`，以后后端换字段只在三个组件里生效。
const marks = useLocate(() => props.itemId, () => props.focus)
let loaded = false

const total = computed(() => doc.value?.numPages || props.pageCount || sizes.value.length || 0)

async function open() {
  opening.value = true
  pdfError.value = ''
  try {
    // 走 api 客户端：演示站要把这条地址换成本地那份 PDF（手写 URL 换不掉）
    const opened = await openPdf(api.fileUrl(props.itemId), {
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

/** 记住当前页码（卸载前调；`reset()` 会把 current 打回 1，所以必须先记再清） */
function rememberPage() {
  if (props.itemId) PAGE_MEMORY.set(props.itemId, current.value)
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
  (id, prev) => {
    if (prev) PAGE_MEMORY.set(prev, current.value)
    reset()
    current.value = PAGE_MEMORY.get(id) || 1
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
 * 引用跳转（T11.2）：拿到命中页就翻过去。
 *
 * 同一页时 `PdfScroller` 不会自己滚（它按滚动位置判断，本来就在那一页），
 * 所以这里显式滚一次；不同页交给 `current` 的变化。
 * 落不到页不是错误（chunk 被重新整理删了 / 这页还没读出来），停在当前页即可。
 */
watch(marks, (found) => {
  if (!found) return
  if (found.page === current.value) scroller.value?.scrollToPage(found.page, true)
  else current.value = found.page
})

/** 没给 chunkId（老接口 / 笔记）：只停在当前页，不做假定位 */
watch(
  () => props.focus,
  (target) => {
    if (target && !target.chunkId) scroller.value?.scrollToPage(current.value, true)
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

onBeforeUnmount(() => {
  rememberPage()
  reset()
})
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

/* 左原件、右文字：各自滚动，谁长谁滚 */
.pdf-view {
  /* 详情区的可用宽度由「左栏 + 列表」两档折叠与拖拽决定，跟视口宽度不是一回事：
     1280 的窗口拖宽列表后，详情区可能只剩 600。所以这里按自己的宽度判断，不按窗口。 */
  container-type: inline-size;
}

.spread {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 1fr);
  gap: var(--space-4);
}

/* 660 = 左右两栏各自的最低可读宽度之和（≈330 + 300 + 24 间距）；比这窄就上下排 */
@container (max-width: 660px) {
  .spread {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  }
}
</style>
