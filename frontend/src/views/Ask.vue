<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage, streamSSE } from '../api/client'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'

const router = useRouter()
const toast = useToast()
const { openItemAt } = useUi()

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

let controller = null

const matchCount = computed(() => sources.value.length)
const itemCount = computed(() => new Set(sources.value.map((s) => s.item_id)).size)

const fallbackHint = computed(() => {
  const value = tab.value === 'ask' ? askFallback.value : hitsFallback.value
  if (value === 'vector_disabled') return '向量不可用，已降级为全文检索（功能不受影响）'
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
        } else if (ev.type === 'delta') {
          answer.value += ev.text || ''
        } else if (ev.type === 'no_result') {
          noResult.value = true
          answer.value = ev.message || ''
        } else if (ev.type === 'error') {
          askError.value = ev.message || '问答失败'
          toast.error(`${ev.message || '问答失败'}${ev.detail ? `（${ev.detail}）` : ''}`)
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
  }
}

function stop() {
  controller?.abort()
}

async function runSearch() {
  const q = question.value.trim()
  if (!q) return
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

function openAt(itemId, text, source) {
  openItemAt(itemId, { text, source })
  router.push('/')
}

function jump(source) {
  if (!source) return
  openAt(source.item_id, source.content, source.source)
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
          <button
            class="btn btn-primary btn-sm"
            type="button"
            :disabled="!question.trim() || asking"
            @click="submit"
          >
            {{ tab === 'ask' ? (asking ? '生成中…' : '提问') : '搜索' }}
          </button>
        </div>
      </div>

      <p v-if="fallbackHint" class="hint-line">{{ fallbackHint }}</p>

      <!-- 问答 -->
      <template v-if="tab === 'ask'">
        <p v-if="sources.length" class="stats">
          命中 {{ matchCount }} 段原文 · 来自 {{ itemCount }} 个条目
        </p>

        <article v-if="answer" class="answer" :class="{ dim: noResult }">
          <template v-for="(part, index) in answerParts" :key="index">
            <button
              v-if="part.cite"
              class="cite"
              type="button"
              :title="sources[part.cite - 1]?.item_title || ''"
              @click="jump(sources[part.cite - 1])"
            >
              [{{ part.cite }}]
            </button>
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
          <p class="state-title">问一个库里有答案的问题</p>
          <p>回答只依据检索到的原文片段，找不到就直接说没有</p>
        </div>
      </template>

      <!-- 原文命中 -->
      <template v-else>
        <div v-if="hitsLoading" class="skeletons">
          <div v-for="i in 4" :key="i" class="skeleton" style="height: 46px" />
        </div>

        <p v-else-if="hitsError" class="state-error">{{ hitsError }}</p>

        <p v-else-if="hitsQuery && !hits.length" class="state-empty">
          没有匹配「{{ hitsQuery }}」的原文片段，换个说法再试
        </p>

        <section v-else-if="hits.length" class="hits">
          <p class="stats">
            「{{ hitsQuery }}」命中 {{ hits.length }} 段
          </p>
          <ul class="hit-list">
            <li v-for="hit in hits" :key="hit.chunk_id">
              <button class="hit" type="button" @click="openAt(hit.item_id, hit.content, hit.source)">
                <span class="hit-head">
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
          <p>输入关键词后按回车；两字词也能搜（自动走模糊匹配）</p>
        </div>
      </template>
    </div>
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
}

.tab.on {
  color: var(--c-primary);
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
  color: var(--c-warning);
}

.stats {
  margin: var(--space-5) 0 var(--space-2);
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
  color: var(--c-primary);
  vertical-align: super;
  line-height: 1;
}

.cite:hover {
  text-decoration: underline;
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
  border-color: #cfe0d7;
  background: var(--c-primary-soft);
}

.source-n {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-primary);
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
  background: #fbeaa8;
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
  margin-top: var(--space-5);
}
</style>
