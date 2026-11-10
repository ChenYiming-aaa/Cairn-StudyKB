<script setup>
import { computed, onMounted, ref } from 'vue'

import { api, friendlyMessage } from '../api/client'
import QuizRunner from '../components/QuizRunner.vue'
import { useToast } from '../composables/useToast'
import { shortTime } from '../utils/format'
import { TYPE_LABELS } from '../utils/quiz'

/**
 * 复习队列页（T4.7）：到期就回来找你。
 *
 * - 「今日待复习」= `due_at <= 现在`，由后端在 Python 侧比较（UTC 存储，数据契约 §3）
 * - 交卷时 `/api/quiz/submit` 已经顺手推进了间隔，本页**不再重复上报**
 *   （重复上报会把间隔推两格；`/api/review/{id}/result` 只在人工裁定待判题时用）
 * - 「错题本」是**最近一次作答明确答错**的题：复习答对后自动消失
 *
 * 空队列不是错误：答错的题 due 是明天，今天打开就该是空的（验收场景 B 第一段）。
 */
const toast = useToast()

const tab = ref('due')             // due | wrong
const loading = ref(true)
const error = ref('')
const items = ref([])
const total = ref(0)
const tracked = ref(0)
const wrongTotal = ref(0)

const wrongLoading = ref(false)
const wrongError = ref('')
const wrongItems = ref([])

const practicing = ref(false)
const runKey = ref(0)

/** QuizRunner 按 `id` 索引题目，复习项的主键叫 question_id，进来时统一一下 */
const questions = computed(() => items.value.map((item) => ({ ...item, id: item.question_id })))

async function loadDue() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.dueReviews({ limit: 20 })
    items.value = data.items || []
    total.value = data.total || 0
    tracked.value = data.tracked || 0
    wrongTotal.value = data.wrong || 0
  } catch (err) {
    error.value = friendlyMessage(err)
    items.value = []
  } finally {
    loading.value = false
  }
}

async function loadWrong() {
  wrongLoading.value = true
  wrongError.value = ''
  try {
    const data = await api.wrongQuestions({ limit: 50, offset: 0 })
    wrongItems.value = data.items || []
  } catch (err) {
    wrongError.value = friendlyMessage(err)
    wrongItems.value = []
  } finally {
    wrongLoading.value = false
  }
}

function switchTab(key) {
  tab.value = key
  if (key === 'wrong' && !wrongItems.value.length) loadWrong()
}

function startPractice() {
  if (!questions.value.length) return
  practicing.value = true
  runKey.value += 1
}

function onFinished(result) {
  toast.ok(`本轮复习完成：${result.correct_count}/${result.total}`)
  // 交卷已经把间隔推进了，这里只刷新时间表；错题本可能变短，下次切过去再拉
  wrongItems.value = []
  loadDue()
}

function onRestart() {
  practicing.value = false
  loadDue()
}

onMounted(loadDue)
</script>

<template>
  <div class="review">
    <header class="head">
      <div>
        <h1 class="page-title">复习</h1>
        <p class="page-sub">答错的题按 1 → 2 → 4 → 7 → 15 天回来，答对一次往后推一格</p>
      </div>
      <div class="stats">
        <span class="stat" :class="{ hot: total > 0 }">
          <b>{{ total }}</b> 今日到期
        </span>
        <span class="stat"><b>{{ tracked }}</b> 队列中</span>
        <span class="stat"><b>{{ wrongTotal }}</b> 错题</span>
      </div>
    </header>

    <nav class="tabs">
      <button class="tab" type="button" :class="{ on: tab === 'due' }" @click="switchTab('due')">
        今日待复习
      </button>
      <button class="tab" type="button" :class="{ on: tab === 'wrong' }" @click="switchTab('wrong')">
        错题本
      </button>
    </nav>

    <!-- 复习模式 -->
    <section v-if="practicing && questions.length" class="panel">
      <QuizRunner
        :key="runKey"
        :questions="questions"
        @finished="onFinished"
        @restart="onRestart"
      />
    </section>

    <!-- 待复习列表 -->
    <section v-else-if="tab === 'due'" class="panel">
      <div class="panel-bar">
        <span class="panel-note">
          {{ total ? `到期的 ${total} 题，一次最多做 20 题` : '今天没有到期的题' }}
        </span>
        <button class="btn btn-primary btn-sm" type="button" :disabled="!items.length" @click="startPractice">
          开始复习{{ items.length ? `（${items.length}）` : '' }}
        </button>
      </div>

      <p v-if="loading" class="panel-note pad">加载中…</p>
      <p v-else-if="error" class="panel-note pad error">{{ error }}</p>
      <div v-else-if="!items.length" class="state">
        <p class="state-title">今天没有到期的题</p>
        <p>去练习里答错几道，明天它们就回到这里。</p>
      </div>
      <ul v-else class="rows">
        <li v-for="item in items" :key="item.question_id" class="row">
          <span class="row-tag">{{ TYPE_LABELS[item.type] || item.type }}</span>
          <span class="row-main">{{ item.question }}</span>
          <span class="row-sub">{{ item.source_title || '未命名条目' }}</span>
          <span class="row-meta">
            间隔 {{ item.interval_days }} 天
            <template v-if="item.lapses"> · 忘过 {{ item.lapses }} 次</template>
          </span>
          <span class="row-time">{{ shortTime(item.due_local || item.due_at) }}</span>
        </li>
      </ul>
    </section>

    <!-- 错题本 -->
    <section v-else class="panel">
      <div class="panel-bar">
        <span class="panel-note">最近一次作答仍答错的题。复习答对后自动移出。</span>
        <button class="btn btn-sm" type="button" @click="loadWrong">刷新</button>
      </div>

      <p v-if="wrongLoading" class="panel-note pad">加载中…</p>
      <p v-else-if="wrongError" class="panel-note pad error">{{ wrongError }}</p>
      <div v-else-if="!wrongItems.length" class="state">
        <p class="state-title">错题本是空的</p>
        <p>没有「最近一次答错」的题，或者都已经复习对了。</p>
      </div>
      <ul v-else class="rows">
        <li v-for="item in wrongItems" :key="item.question_id" class="row">
          <span class="row-tag">{{ TYPE_LABELS[item.type] || item.type }}</span>
          <span class="row-main">{{ item.question }}</span>
          <span class="row-sub">{{ item.source_title || '未命名条目' }}</span>
          <span class="row-meta">
            错 {{ item.wrong_count }} 次
            <template v-if="item.due_at"> · 下次 {{ shortTime(item.due_at) }}</template>
            <template v-else> · 未排期</template>
          </span>
          <span class="row-time">{{ shortTime(item.last_wrong_at) }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.review {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--space-4) var(--space-6);
  background: var(--c-bg-0);
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.page-title {
  margin: 0;
  font-size: var(--fs-xl);
  color: var(--c-text-1);
}

.page-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.stats {
  display: flex;
  gap: var(--space-3);
  flex: none;
}

.stat {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.stat b {
  font-size: var(--fs-lg);
  color: var(--c-text-1);
  font-variant-numeric: tabular-nums;
  margin-right: var(--space-1);
}

.stat.hot b {
  color: var(--c-primary-ink);
}

.tabs {
  display: flex;
  gap: var(--space-1);
  margin-top: var(--space-4);
}

.tab {
  padding: var(--space-1) var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  background: none;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  cursor: pointer;
}

.tab.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  margin-top: var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  overflow: hidden;
}

.panel-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--c-border);
}

.panel-note {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.panel-note.pad {
  padding: var(--space-4);
}

.panel-note.error {
  color: var(--c-danger-ink);
}

.rows {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0;
  padding: var(--space-2);
  list-style: none;
}

.row {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) 150px 175px 84px;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}

.row:hover {
  background: var(--c-bg-2);
}

.row-tag {
  font-size: var(--fs-xs);
  color: var(--c-primary-ink);
}

.row-main {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--c-text-1);
}

.row-sub,
.row-meta,
.row-time {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.row-time {
  text-align: right;
}
</style>
