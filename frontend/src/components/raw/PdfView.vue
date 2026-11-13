<script setup>
/**
 * PDF 原文（T9.10）：**页图在上、这一页的文字在下**，按页翻。
 *
 * 两件事不许改：
 * - 页图与文字同一次请求（`pages/{n}` 一起返回），永远挨着显示 —— 这是
 *   「认错也看得出来」的保障，做成分开的两个标签页就失效了。
 * - 首屏只取第 1 页，翻页才请求下一页：30 页的讲义一次性拉全是几百 MB 页图。
 *
 * 行级置信度（`line_conf`）与文字逐行对齐，`< 0.85` 的行标黄；页级 `avg_conf`
 * 低的在页头提示一句。老识别结果没有行级数据，那时就只提示不标黄。
 */
import { computed, ref, watch } from 'vue'

import { api, friendlyMessage } from '../../api/client'

const props = defineProps({
  itemId: { type: Number, required: true },
  // 原件总页数（`item.file.page_count`）；还没读出来时是 0，界面要说清楚
  pageCount: { type: Number, default: 0 },
  // 页签是否可见：不可见时不发请求，打开原文才取第 1 页
  active: { type: Boolean, default: false },
})

const LOW = 0.85
const page = ref(1)
const data = ref(null)
const loading = ref(false)
const error = ref('')
const imgError = ref(false)
const textBox = ref(null)
let loaded = false

const total = computed(() => props.pageCount || data.value?.page_no || 0)

async function load(n) {
  loading.value = true
  error.value = ''
  imgError.value = false
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

// 切内容回来时从第 1 页重新开始（page 只在 itemId 变时重置，翻页不受影响）
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

function showText() {
  textBox.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}
</script>

<template>
  <div class="pdf-view">
    <div class="bar">
      <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
      <span class="pager">第 {{ page }} 页<template v-if="total"> / 共 {{ total }} 页</template></span>
      <button
        class="btn btn-sm"
        type="button"
        :disabled="!total || page >= total"
        @click="go(page + 1)"
      >下一页</button>
      <span v-if="lowCount || pageSuspicious" class="warn">
        这一页可能有错<template v-if="lowCount">（{{ lowCount }} 行认不准，已标黄）</template>，对照页图看看
      </span>
    </div>

    <p v-if="error" class="state">{{ error }}</p>

    <div v-else class="spread" :class="{ busy: loading }">
      <figure class="shot">
        <img
          v-if="!imgError && data?.image_url"
          :src="data.image_url"
          :alt="`第 ${page} 页的页图`"
          @error="imgError = true"
        />
        <div v-else-if="imgError" class="shot-missing">
          <p>页图没显示出来，可能是这份文件重新读过了。</p>
          <button class="btn btn-sm" type="button" @click="showText">看文字</button>
        </div>
        <figcaption v-else-if="!loading" class="shot-missing">这一页没有页图，看文字就行。</figcaption>
      </figure>

      <div ref="textBox" class="text">
        <p v-if="loading" class="state">正在取这一页…</p>
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

.warn {
  margin-left: auto;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
}

/* 页图与文字并排（窄屏自动上下紧邻），各自滚动，谁长谁滚 */
.spread {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: var(--space-4);
}

@media (max-width: 1100px) {
  .spread {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  }
}

.shot {
  margin: 0;
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.shot img {
  display: block;
  width: 100%;
  height: auto;
}

.shot-missing {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 160px;
  padding: var(--space-4);
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  text-align: center;
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
