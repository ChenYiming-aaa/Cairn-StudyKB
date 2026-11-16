<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage, humanDetail, streamSSE } from '../api/client'
import { useLayout } from '../composables/useLayout'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'
import { shortTime } from '../utils/format'
import { usable } from '../utils/components'

const router = useRouter()
const toast = useToast()
const { openItemAt, openSettings, openPaste } = useUi()
// T7.3：历史抽屉的开关搬到 useLayout（和左栏/列表同一套记忆），Ctrl+H 在 App.vue 触发
const { isPanelCollapsed, setPanel } = useLayout()

const TABS = [
  { key: 'ask', label: '问答' },
  { key: 'search', label: '原文命中' },
]

const tab = ref('ask')
const question = ref('')
const asking = ref(false)
const askedQuestion = ref('')

const answer = ref('')
const sources = ref([])
const noResult = ref(false)
const askError = ref('')
const askFallback = ref('none')

const hits = ref([])
const hitsLoading = ref(false)
const hitsError = ref('')
const hitsFallback = ref('none')
const hitsQuery = ref('')
/**
 * 向量检索现在能不能用（M2）。默认 true：探测失败时宁可不说，也不要凭空劝人下 118 MB。
 * 判据只有 `utils/components.usable`（看后端算好的 `mode`）—— 按 `state` 判会把
 * 「源码运行 / 本机已装库」这种实际能用的环境报成没装。
 */
const embedReady = ref(true)

// 问答历史（T3.12）：抽屉里的列表只用来"找回来"，不参与检索
// T7.3：开关状态放 useLayout（`panels.chat`），顶栏 Ctrl+H 与这里的按钮共用同一个
const historyOpen = computed(() => !isPanelCollapsed('chat'))
const historyLoading = ref(false)
const historyError = ref('')
const historyItems = ref([])
const historyTotal = ref(0)
const currentLogId = ref(null)
/** 当前展示的是不是从历史里调出来的旧记录（非 null 时答案上方标出时间） */
const currentRecord = ref(null)

let controller = null

const matchCount = computed(() => sources.value.length)
// 当前页签上「这一下还没回来」：问答看流式、搜索看那一次请求，互不干扰
const pending = computed(() => (tab.value === 'ask' ? asking.value : hitsLoading.value))
const itemCount = computed(() => new Set(sources.value.map((s) => s.item_id)).size)

/**
 * 当前提示是不是"缺向量组件"—— 只有它才配「去安装」按钮。
 * 搜索前的那次探测也算：`fallback` 还没回来时（'none'）同样要能看出「现在就缺一块」。
 */
const needEmbed = computed(() => {
  const value = tab.value === 'ask' ? askFallback.value : hitsFallback.value
  if (value === 'vector_component_missing') return true
  return value === 'none' && !embedReady.value
})

const fallbackHint = computed(() => {
  const value = tab.value === 'ask' ? askFallback.value : hitsFallback.value
  // 搜索前就先说清楚（M2）：等搜完才补一句「只能按关键词搜」，用户会先把
  // 第一轮结果质量差归因成「我的库不行」
  if (value === 'none' && !embedReady.value) return '现在只能按关键词搜。装上「向量检索」就能按意思搜'
  if (value === 'vector_disabled') return '语义检索暂时不可用，已改成按关键词搜，也能找到大部分内容'
  // 文案不再自带"去设置里装"：那一句改成一个按钮（同一行里更明显，也不用记路径）
  if (value === 'vector_component_missing') return '现在只能按关键词搜。装上「向量检索」就能按意思搜'
  if (value === 'like_short_query') return '关键词少于 3 字，已改用模糊匹配'
  return ''
})

/** 把答案里的 [n] 切成可点的引用按钮；其余文字原样保留（含换行） */
const answerParts = computed(() => {
  const text = answer.value || ''
  const parts = []
  const re = /\[(\d+)\]/g
  let last = 0
  let m = re.exec(text)
  while (m) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index) })
    parts.push({ cite: Number(m[1]) })
    last = m.index + m[0].length
    m = re.exec(text)
  }
  if (last < text.length) parts.push({ text: text.slice(last) })
  return parts
})

/** 片段里高亮关键词：只做纯文本切分，不拼 HTML（XSS 无入口） */
function snippetParts(text, keyword) {
  const body = text || ''
  const needle = (keyword || '').trim()
  if (!needle) return [{ text: body }]
  const parts = []
  let from = 0
  let at = body.indexOf(needle)
  while (at >= 0) {
    if (at > from) parts.push({ text: body.slice(from, at) })
    parts.push({ text: needle, hit: true })
    from = at + needle.length
    at = body.indexOf(needle, from)
  }
  if (from < body.length) parts.push({ text: body.slice(from) })
  return parts.length ? parts : [{ text: body }]
}

async function ask() {
  const q = question.value.trim()
  if (!q || asking.value) return
  askedQuestion.value = q
  answer.value = ''
  sources.value = []
  noResult.value = false
  askError.value = ''
  askFallback.value = 'none'
  currentLogId.value = null
  currentRecord.value = null
  asking.value = true
  controller = new AbortController()

  try {
    await streamSSE(
      '/api/ask',
      { question: q, limit: 8 },
      (ev) => {
        if (ev.type === 'sources') {
          sources.value = ev.sources || []
          askFallback.value = ev.fallback || 'none'
          // 这轮真用上了语义检索：把进页面时的预判纠回来
          if (askFallback.value === 'none') embedReady.value = true
        } else if (ev.type === 'delta') {
          answer.value += ev.text || ''
        } else if (ev.type === 'no_result') {
          noResult.value = true
          answer.value = ev.message || ''
        } else if (ev.type === 'error') {
          askError.value = ev.message || '这次没问成'
          // detail 是排查用的技术串，只有中文的才值得给用户看
          const detail = humanDetail(ev.detail)
          toast.error(`${ev.message || '这次没问成'}${detail ? `（${detail}）` : ''}`)
        } else if (ev.type === 'done') {
          asking.value = false
        }
      },
      { signal: controller.signal }
    )
  } catch (err) {
    if (err?.name !== 'AbortError') askError.value = friendlyMessage(err)
  } finally {
    asking.value = false
    controller = null
    // 后端是在 done 之前落库的，这里刷新角标能立刻看到新记录
    refreshHistoryCount()
  }
}

function stop() {
  controller?.abort()
}

/** 只取条数，用来在入口按钮上显示角标；不打开抽屉就不必拉列表 */
async function refreshHistoryCount() {
  try {
    const data = await api.askHistory({ limit: 1, offset: 0 })
    historyTotal.value = data.total || 0
  } catch {
    // 计数失败不打扰用户，入口仍然可点
  }
}

async function loadHistory() {
  historyLoading.value = true
  historyError.value = ''
  try {
    const data = await api.askHistory({ limit: 50, offset: 0 })
    historyItems.value = data.items || []
    historyTotal.value = data.total || 0
  } catch (err) {
    historyItems.value = []
    historyError.value = friendlyMessage(err)
  } finally {
    historyLoading.value = false
  }
}

function toggleHistory() {
  setPanel('chat', historyOpen.value)   // 传「折叠后」的状态：开着就关
}

// 不管入口是页面按钮还是 Ctrl+H，打开就拉一次列表
watch(historyOpen, (open) => {
  if (open) loadHistory()
})

// 抽屉没有遮罩了（M7 §4 T7.3），Esc 是它唯一的「点外面关掉」替代
function onKeydown(event) {
  if (event.key === 'Escape' && historyOpen.value) setPanel('chat', true)
}

/** 点一条历史：把当时的问题、答案、来源恢复到主视图，**不再调模型** */
async function openLog(id) {
  if (!id) return
  try {
    const log = await api.askHistoryDetail(id)
    currentRecord.value = log
    question.value = log.question || ''
    askedQuestion.value = log.question || ''
    answer.value = log.answer || ''
    sources.value = log.sources || []
    noResult.value = Boolean(log.no_result)
    askError.value = log.error_code ? '这次问答中途失败了，上面的内容不完整' : ''
    askFallback.value = log.fallback || 'none'
    currentLogId.value = log.id
    tab.value = 'ask'
    setPanel('chat', true)   // 恢复完就关抽屉，别挡着答案
  } catch (err) {
    toast.error(friendlyMessage(err))
  }
}

async function removeLog(id) {
  // 一行一个「×」，一点就没了且没有撤销 —— 先问一句（同页其它删除也都确认过）
  if (!window.confirm('删掉这条问答记录？删了就找不回来了。')) return
  try {
    await api.deleteAskHistory(id)
    historyItems.value = historyItems.value.filter((h) => h.id !== id)
    historyTotal.value = Math.max(0, historyTotal.value - 1)
    if (currentLogId.value === id) currentLogId.value = null
    toast.ok('已删除这条问答记录')
  } catch (err) {
    toast.error(friendlyMessage(err))
  }
}

/** 进页面先问一次组件状态：降级提示要在搜索之前就能看见（M2） */
async function probeEmbed() {
  try {
    const data = await api.components()
    embedReady.value = usable((data.items || []).find((item) => item.id === 'embed'))
  } catch {
    // 演示站 / 组件接口暂时不可用：不提示，搜索响应回来自会带 fallback
    embedReady.value = true
  }
}

onMounted(() => {
  refreshHistoryCount()
  probeEmbed()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

async function runSearch() {
  const q = question.value.trim()
  // 按钮在飞时是禁用的，但回车不走按钮：这里也挡一次，避免两次结果互相覆盖
  if (!q || hitsLoading.value) return
  hitsQuery.value = q
  hitsLoading.value = true
  hitsError.value = ''
  try {
    const data = await api.search({ q, limit: 20 })
    hits.value = data.items || []
    hitsFallback.value = data.fallback || 'none'
  } catch (err) {
    hits.value = []
    hitsError.value = friendlyMessage(err)
  } finally {
    hitsLoading.value = false
  }
}

function submit() {
  if (tab.value === 'ask') ask()
  else runSearch()
}

function onEnter(event) {
  if (event.shiftKey) return
  event.preventDefault()
  submit()
}

function openAt(itemId, text, source, chunkId, hint) {
  openItemAt(itemId, { text, source, chunkId, hint })
  router.push('/')
}

function jump(source) {
  if (!source) {
    // 模型偶尔给出超出范围的引用号（比如只有 8 段却写 [9]）。按钮看着可点，
    // 点了却什么都不发生 —— 说一句，比静默 return 诚实（L 组）
    toast.info('这条引用在来源里找不到对应原文，可能已被删除')
    return
  }
  // chunk_id 一起带过去：PDF 的原文要按它算「这段字在第几页」（T11.2）
  openAt(source.item_id, source.content, source.source, source.chunk_id)
}

/** 零命中时的两个出口：换问答再问一次 / 把这条内容采进来（L 组） */
function switchToAsk() {
  const q = question.value.trim()
  tab.value = 'ask'
  if (q) ask()
}

function switchTab(key) {
  tab.value = key
  if (key === 'search' && question.value.trim() && !hits.value.length) runSearch()
}

watch(question, () => {
  if (tab.value === 'search' && !question.value.trim()) hits.value = []
})
</script>

<template>
  <div class="ask-page">
    <div class="ask-inner">
      <header class="ask-head">
        <div>
          <h1 class="page-title">检索问答</h1>
          <p class="page-sub">只在你的知识库里找答案，每条结论都能点回原文</p>
        </div>
        <div class="head-right">
          <nav class="tabs">
            <button
              v-for="entry in TABS"
              :key="entry.key"
              type="button"
              class="tab"
              :class="{ on: tab === entry.key }"
              @click="switchTab(entry.key)"
            >
              {{ entry.label }}
            </button>
          </nav>
          <button
            class="btn btn-sm hist-btn"
            type="button"
            :class="{ on: historyOpen }"
            title="问答历史（Ctrl+H）"
            @click="toggleHistory"
          >
            历史
            <span v-if="historyTotal" class="hist-count">{{ historyTotal }}</span>
          </button>
        </div>
      </header>

      <div class="ask-bar">
        <textarea
          v-model="question"
          class="input ask-input"
          rows="2"
          placeholder="问点什么，或输入关键词搜原文（Shift + Enter 换行）"
          @keydown.enter="onEnter"
        />
        <div class="ask-actions">
          <button v-if="asking" class="btn btn-sm" type="button" @click="stop">停止</button>
          <!-- 在飞的时候禁用：提问走流式、搜索走一次请求，重复点会打两次请求且答案互相覆盖 -->
          <button
            class="btn btn-primary btn-sm"
            type="button"
            :disabled="!question.trim() || pending"
            :aria-busy="pending"
            @click="submit"
          >
            <progress v-if="pending" class="spin" aria-hidden="true" />
            {{ pending
              ? (tab === 'ask' ? '生成中…' : '搜索中…')
              : (tab === 'ask' ? '提问' : '搜索') }}
          </button>
        </div>
      </div>

      <!-- M8 T8.4：缺向量组件时给一个能点的入口，别只让用户自己去翻设置 -->
      <p v-if="fallbackHint" class="hint-line">
        {{ fallbackHint }}
        <button
          v-if="needEmbed"
          class="hint-btn"
          type="button"
          @click="openSettings('downloads')"
        >
          去安装
        </button>
      </p>

      <!-- 问答 -->
      <template v-if="tab === 'ask'">
        <p v-if="currentRecord" class="hist-loaded">
          历史记录 · {{ shortTime(currentRecord.created_at) }}（不是刚问的，不会重新调模型）
        </p>

        <p v-if="sources.length" class="stats">
          命中 {{ matchCount }} 段原文 · 来自 {{ itemCount }} 条内容
        </p>

        <article v-if="answer" class="answer" :class="{ dim: noResult }">
          <template v-for="(part, index) in answerParts" :key="index">
            <!-- 引用号越界（模型写成 [9] 但只有 8 段）：没有对应来源就不渲染成按钮 ——
                 一个「看着能点、点了没反应」的东西比一个灰色号更让人怀疑整段答案（L 组） -->
            <button
              v-if="part.cite && sources[part.cite - 1]"
              class="cite"
              type="button"
              :title="sources[part.cite - 1]?.item_title || ''"
              @click="jump(sources[part.cite - 1])"
            >
              [{{ part.cite }}]
            </button>
            <span
              v-else-if="part.cite"
              class="cite cite-lost"
              title="这条引用找不到对应原文，可能来自上一版回答"
            >[{{ part.cite }}]</span>
            <template v-else>{{ part.text }}</template>
          </template>
        </article>

        <p v-if="askError" class="state-error">{{ askError }}</p>

        <section v-if="sources.length" class="sources">
          <h2 class="section-title">来源</h2>
          <ol class="source-list">
            <li v-for="source in sources" :key="source.chunk_id">
              <button class="source" type="button" @click="jump(source)">
                <span class="source-n">[{{ source.n }}]</span>
                <span class="source-body">
                  <span class="source-title">{{ source.item_title }}</span>
                  <span class="source-snippet">{{ source.snippet }}</span>
                </span>
                <span class="source-tag">{{ source.source === 'note' ? '笔记' : '原文' }}</span>
              </button>
            </li>
          </ol>
        </section>

        <div v-else-if="!answer && !asking && !askError" class="state">
          <p class="state-title">试着问一个具体问题</p>
          <p>答案只来自你采集的内容；找不到会直接说没有。</p>
        </div>
      </template>

      <!-- 原文命中 -->
      <template v-else>
        <div v-if="hitsLoading" class="skeletons">
          <div v-for="i in 4" :key="i" class="skeleton" style="height: 46px" />
        </div>

        <p v-else-if="hitsError" class="state-error">{{ hitsError }}</p>

        <div v-else-if="hitsQuery && !hits.length" class="state">
          <p class="state-title">没有匹配「{{ hitsQuery }}」的原文片段</p>
          <p>换个说法再试，或者让模型按意思找一遍。</p>
          <div class="state-actions">
            <button class="btn btn-sm" type="button" @click="switchToAsk">改成问答</button>
            <button class="btn btn-ghost btn-sm" type="button" @click="openPaste(hitsQuery)">采集这条内容</button>
          </div>
        </div>

        <section v-else-if="hits.length" class="hits">
          <p class="stats">
            「{{ hitsQuery }}」命中 {{ hits.length }} 段
          </p>
          <ul class="hit-list">
            <li v-for="hit in hits" :key="hit.chunk_id">
              <button
                class="hit"
                type="button"
                @click="openAt(hit.item_id, hit.content, hit.source, hit.chunk_id, hitsQuery)"
              >                <span class="hit-head">
                  <span class="hit-title">{{ hit.item_title }}</span>
                  <span class="badge badge-soft">{{ hit.match_type }}</span>
                  <span v-if="hit.source === 'note'" class="hit-src">笔记</span>
                </span>
                <span class="hit-text">
                  <template v-for="(part, index) in snippetParts(hit.snippet, hitsQuery)" :key="index">
                    <mark v-if="part.hit">{{ part.text }}</mark>
                    <template v-else>{{ part.text }}</template>
                  </template>
                </span>
              </button>
            </li>
          </ul>
        </section>

        <div v-else class="state">
          <p class="state-title">搜原文片段</p>
          <p>输入关键词后按回车。两个字也能搜，会自动走模糊匹配。</p>
        </div>
      </template>
    </div>

    <!-- 问答历史抽屉（T3.12 / T7.3）：保留浮层形态，但不铺半透明遮罩 —— 抽屉关掉后
         页面上不残留任何挡住点击的层；开着时按 Esc 或点「关闭」收起 -->
    <aside v-if="historyOpen" class="hist-drawer" aria-label="问答历史">
      <header class="hist-head">
        <h2 class="section-title">问答历史</h2>
        <span class="hist-total">共 {{ historyTotal }} 条</span>
        <button class="btn btn-sm" type="button" @click="toggleHistory">关闭</button>
      </header>

      <p v-if="historyLoading" class="state-empty">加载中…</p>
      <p v-else-if="historyError" class="state-error">{{ historyError }}</p>
      <p v-else-if="!historyItems.length" class="state-empty">
        还没有问答记录，问一次就会出现在这里
      </p>

      <ul v-else class="hist-list">
        <li
          v-for="log in historyItems"
          :key="log.id"
          class="hist-item"
          :class="{ on: currentLogId === log.id }"
        >
          <button class="hist-main" type="button" @click="openLog(log.id)">
            <span class="hist-q">
              <span v-if="log.no_result" class="badge badge-warn">无结果</span>
              <span v-else-if="log.error_code" class="badge badge-warn">出错</span>
              {{ log.question }}
            </span>
            <span class="hist-preview">{{ log.answer_preview }}</span>
            <span class="hist-meta">
              {{ shortTime(log.created_at) }}
              <template v-if="log.source_count"> · 来源 {{ log.source_count }} 段</template>
              <template v-if="log.completion_tokens"> · {{ log.completion_tokens }} tokens</template>
            </span>
          </button>
          <button
            class="hist-del"
            type="button"
            title="删除这条记录"
            @click.stop="removeLog(log.id)"
          >
            ×
          </button>
        </li>
      </ul>
    </aside>
  </div>
</template>

<style scoped>
.ask-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: var(--c-bg-0);
}

.ask-inner {
  max-width: 860px;
  margin: 0 auto;
  padding: var(--space-6) var(--space-6) var(--space-8);
}

.ask-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.page-title {
  margin: 0;
  font-size: var(--fs-xl);
  color: var(--c-text-1);
}

.page-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.tabs {
  display: flex;
  gap: var(--space-3);
  border-bottom: 1px solid var(--c-border);
}

.tab {
  padding: var(--space-2) 0;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  margin-bottom: -1px;
  /* 不加会被 .head-right 挤成两行（min-content 只有 1 个字宽） */
  white-space: nowrap;
}

.tab.on {
  color: var(--c-primary-ink);
  border-bottom-color: var(--c-primary);
  font-weight: 600;
}

.ask-bar {
  position: relative;
}

.ask-input {
  width: 100%;
  padding: var(--space-3) var(--space-3) var(--space-8);
  resize: vertical;
  font-family: var(--font-ui);
  line-height: var(--lh-body);
}

.ask-actions {
  position: absolute;
  right: var(--space-2);
  bottom: var(--space-2);
  display: flex;
  gap: var(--space-2);
}

.hint-line {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-warning-ink);
}

.hint-btn {
  margin-left: var(--space-1);
  padding: 0;
  border: none;
  background: none;
  color: var(--c-primary-ink);
  font-size: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.hint-btn:hover {
  color: var(--c-primary-hover);
}

.stats {
  margin: var(--space-4) 0 var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.answer {
  margin: var(--space-2) 0 0;
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  font-family: var(--font-reading);
  font-size: 15px;
  line-height: 1.9;
  color: var(--c-text-1);
  white-space: pre-wrap;
  word-break: break-word;
}

.answer.dim {
  color: var(--c-text-2);
  font-family: var(--font-ui);
}

.cite {
  margin: 0 1px;
  padding: 0 2px;
  border: none;
  background: none;
  font-size: 12px;
  font-family: var(--font-ui);
  color: var(--c-primary-ink);
  vertical-align: super;
  line-height: 1;
}

.cite:hover {
  text-decoration: underline;
}

/* 越界的引用号：留着位置（正文里那个 [9] 本来就在），但不像可点 */
.cite-lost {
  color: var(--c-text-3);
  cursor: help;
}

.section-title {
  margin: var(--space-6) 0 var(--space-2);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.source-list,
.hit-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.source,
.hit {
  width: 100%;
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  text-align: left;
}

.source:hover,
.hit:hover {
  border-color: var(--c-primary-border);
  background: var(--c-primary-soft);
}

.source-n {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-primary-ink);
  font-variant-numeric: tabular-nums;
}

.source-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.source-title {
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.source-snippet {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.source-tag {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.hit {
  flex-direction: column;
  gap: var(--space-2);
}

.hit-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.hit-title {
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.hit-src {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.hit-text {
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  line-height: 1.7;
}

.hit-text mark {
  background: var(--c-mark);
  color: var(--c-text-1);
  padding: 0 1px;
}

.state-empty {
  margin: var(--space-6) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.skeletons {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

/* ── 问答历史（T3.12）──────────────────────────── */
.head-right {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  flex: none;
}

.hist-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.hist-btn.on {
  border-color: var(--c-primary);
  color: var(--c-primary-ink);
}

.hist-count {
  min-width: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}

.hist-loaded {
  margin: var(--space-3) 0 0;
  padding: var(--space-2) var(--space-3);
  border-left: 3px solid var(--c-warning);
  background: var(--c-bg-2);
  border-radius: var(--radius-sm);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

/* T7.3：从「遮罩 + 抽屉」改成纯浮层。遮罩会盖住整页（连顶栏都点不到），
   而历史抽屉不是模态 —— 用户还可能想边看历史边改问题。 */
.hist-drawer {
  position: fixed;
  top: var(--h-topbar);
  right: 0;
  bottom: 0;
  z-index: 40;
  width: min(420px, 92vw);
  display: flex;
  flex-direction: column;
  background: var(--c-bg-1);
  border-left: 1px solid var(--c-border);
  box-shadow: var(--shadow-md);
}

.hist-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  border-bottom: 1px solid var(--c-border);
}

.hist-head .section-title {
  margin: 0;
}

.hist-total {
  margin-right: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.hist-list {
  list-style: none;
  margin: 0;
  padding: var(--space-2);
  overflow-y: auto;
  flex: 1;
}

.hist-item {
  position: relative;
  display: flex;
  align-items: stretch;
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-2);
  border: 1px solid transparent;
}

.hist-item:hover {
  background: var(--c-bg-2);
}

.hist-item.on {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}

.hist-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--space-3);
  border: none;
  background: none;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.hist-q {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hist-preview {
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hist-meta {
  color: var(--c-text-3);
  font-size: 11px;
}

.hist-del {
  width: 30px;
  border: none;
  background: none;
  color: var(--c-text-3);
  font-size: 16px;
  line-height: 1;
  border-radius: var(--radius-sm);
}

.hist-del:hover {
  color: var(--c-danger-ink);
  background: var(--c-bg-2);
}

.badge-warn {
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  flex: none;
}
</style>
