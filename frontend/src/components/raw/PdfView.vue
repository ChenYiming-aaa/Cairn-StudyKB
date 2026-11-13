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
 * 行级置信度（`line_conf`）与文字逐行对齐，`< 0.85` 的行标黄；页级 `avg_conf`
 * 低的在页头提示一句。老识别结果没有行级数据，那时就只提示不标黄。
 *
 * pdf.js 打不开（文件坏了 / 用了不支持的加密）时退回「只看页图 + 文字」：
 * 用户要的是读到这一页，不是看一个报错页。
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import PdfScroller from './pdf/PdfScroller.vue'
import { fallbackSizes, openPdf } from './pdf/usePdf'

const props = defineProps({
  itemId: { type: Number, required: true },
  // 原件总页数（`item.file.page_count`）；还没读出来时是 0，界面要说清楚
  pageCount: { type: Number, default: 0 },
  // 页签是否可见：不可见时不发请求，打开原文才取
  active: { type: Boolean, default: false },
  // {text, page}：问答引用要落到的那一页与那一段（T11.2）
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
const data = ref(null)
const textLoading = ref(false)
const textError = ref('')
let loaded = false
let textSeq = 0

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

async function loadText(pageNo) {
  const mine = ++textSeq
  textLoading.value = true
  textError.value = ''
  try {
    const next = await api.getPage(props.itemId, pageNo)
    if (mine === textSeq) data.value = next
  } catch (err) {
    if (mine !== textSeq) return
    data.value = null
    textError.value = friendlyMessage(err)
  } finally {
    if (mine === textSeq) textLoading.value = false
  }
}

function go(pageNo) {
  if (pageNo < 1 || (total.value && pageNo > total.value) || pageNo === current.value) return
  current.value = pageNo
}

function reset() {
  textSeq += 1
  // destroy 是异步的，且可能在渲染进行中被调用：吞掉拒绝，别让控制台多一条
  // 「切换内容时的报错」，那对用户没有任何意义
  const current = doc.value
  if (current?.destroy) Promise.resolve(current.destroy()).catch(() => {})
  doc.value = null
  sizes.value = []
  data.value = null
  current.value = 1
  pdfError.value = ''
  textError.value = ''
  loaded = false
}

watch(
  () => props.itemId,
  () => {
    reset()
    if (props.active) {
      loaded = true
      open()
      loadText(1)
    }
  }
)

watch(
  () => props.active,
  (on) => {
    if (!on || loaded) return
    loaded = true
    open()
    loadText(current.value)
  },
  { immediate: true }
)

watch(current, (pageNo) => loadText(pageNo))

// 引用跳转：先滚到那一页，命中段在文字里标黄（T11.2）
watch(
  () => props.focus,
  (target) => {
    if (!target) return
    if (target.page && target.page !== current.value) current.value = target.page
    else scroller.value?.scrollToPage(current.value, true)
  }
)

/** 行级置信度缺失（老数据 / 抽取页）时 confs 为空，所有行都不标 */
const lines = computed(() => {
  const body = data.value?.text || ''
  const confs = data.value?.line_conf || []
  return body
    ? body.split('\n').map((text, index) => ({ text, low: confs[index] != null && confs[index] < LOW }))
    : []
})

const lowCount = computed(() => lines.value.filter((line) => line.low).length)

/** 页级平均分低 = 这页整体可疑；0 表示什么都没认出来，单独说 */
const pageSuspicious = computed(() => {
  const conf = data.value?.avg_conf
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

      <div class="text">
        <p v-if="textLoading" class="state">正在取这一页…</p>
        <p v-else-if="textError" class="state">{{ textError }}</p>
        <template v-else-if="lines.length">
          <p v-for="(line, index) in lines" :key="index" class="line" :class="{ low: line.low }">{{ line.text }}</p>
        </template>
        <p v-else class="state">这页没认出文字，可以对照页图看看。</p>
      </div>
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

.state {
  margin: var(--space-3) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
