<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage } from '../api/client'
import QuizRunner from '../components/QuizRunner.vue'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'
import { shortTime } from '../utils/format'
import { TYPE_LABELS, answerText } from '../utils/quiz'

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
const router = useRouter()
const { openItemAt } = useUi()

const tab = ref('due')             // due | wrong | pending
const loading = ref(true)
const error = ref('')
const items = ref([])
const total = ref(0)
const tracked = ref(0)
const wrongTotal = ref(0)
// 待人工判断（H5）：批改失败的简答既不进队列也不进错题本，只能从这里找
const pending = ref(0)
const pendingItems = ref([])
const pendingLoading = ref(false)
const pendingError = ref('')
const judging = ref({})            // questionId → 正在上报
const judgeError = ref({})         // questionId → 失败原因（就地显示，不弹 toast）

const wrongLoading = ref(false)
const wrongError = ref('')
const wrongItems = ref([])

const practicing = ref(false)
const runKey = ref(0)
/**
 * 这一批题的**快照**（4-1 / 4-2）。
 *
 * 交卷会把到期题推到明天，若此刻 `loadDue()` 换掉 `items`，作答器的 props 就跟着变：
 * 到期题全在这批时 `questions` 归零 → 结果页被 `v-if` 整块卸载；
 * 队列里还有剩时题干全空（结果页按 id 在新 props 里找不到题）。所以这批题单独存一份，
 * 回列表时才清掉。
 */
const runQuestions = ref([])
const runSource = ref('due')        // due | wrong：决定交卷后回哪张列表
const restartLabel = computed(() => (runSource.value === 'wrong' ? '回到错题本' : '回到复习列表'))
/** 还没到期的题数：`tracked` 是全库排期数，减掉今天到期的就是它们（4-5 的第二个数） */
const notYet = computed(() => Math.max(0, tracked.value - total.value))

/** QuizRunner 按 `id` 索引题目，复习项的主键叫 question_id，进来时统一一下 */
function asRunnerItems(list) {
  return list.map((item) => ({ ...item, id: item.question_id }))
}

/** 头部数字统一从一次 `/review/due` 里取，避免两处各算一套（4-5） */
function applyCounts(data) {
  total.value = data.total || 0
  tracked.value = data.tracked || 0
  wrongTotal.value = data.wrong || 0
  pending.value = data.pending || 0
}

async function loadDue() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.dueReviews({ limit: 20 })
    items.value = data.items || []
    applyCounts(data)
  } catch (err) {
    error.value = friendlyMessage(err)
    items.value = []
  } finally {
    loading.value = false
  }
}

async function loadPending() {
  pendingLoading.value = true
  pendingError.value = ''
  try {
    const data = await api.pendingReviews({ limit: 50 })
    pendingItems.value = data.items || []
    pending.value = data.total ?? pendingItems.value.length
  } catch (err) {
    pendingError.value = friendlyMessage(err)
    pendingItems.value = []
  } finally {
    pendingLoading.value = false
  }
}

/**
 * 人工裁定一道「待判」题（H5）。
 *
 * 上报完立刻从列表里移除，并让头部计数跟着减：这道题已经从「不知道」变成明确的
 * 对/错，再留在待判列表里只会让人以为没生效。答错进明天的队列；答对则往后推
 * （2026-11-17 起首次答对也排期——2 天后回来，不再是「不进队列」）。
 */
async function judge(item, correct) {
  const id = item.question_id
  if (judging.value[id]) return
  judging.value = { ...judging.value, [id]: true }
  judgeError.value = { ...judgeError.value, [id]: '' }
  try {
    await api.reportReview(id, { correct })
    pendingItems.value = pendingItems.value.filter((row) => row.question_id !== id)
    pending.value = Math.max(0, pending.value - 1)
    toast.ok(correct ? '已记为答对，下次复习往后推' : '已记为答错，明天回到复习队列')
  } catch (err) {
    judgeError.value = { ...judgeError.value, [id]: friendlyMessage(err) }
  } finally {
    const next = { ...judging.value }
    delete next[id]
    judging.value = next
  }
}

/**
 * 「看原文」：行上只有标题，想核对内容时不该让用户自己去知识库搜一遍标题（M4）。
 *
 * 走的是全站同一条通道（`openItemAt` + 回知识库），所以焦点高亮、页签归位
 * 都与从检索结果跳过去时一致。
 */
function openSource(item) {
  if (!item?.source_item_id) return
  openItemAt(item.source_item_id)
  router.push('/')
}

/** 队列空了想养题：给一句话一个落点，而不是让用户自己找「练习」在哪 */
function goPractice() {
  router.push('/practice')
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
  if (key === 'pending') loadPending()
}

function startPractice() {
  if (!items.value.length) return
  runQuestions.value = asRunnerItems(items.value)
  runSource.value = 'due'
  practicing.value = true
  runKey.value += 1
}

/**
 * 错题本「练这些错题」（4-4）：直接把这批错题喂给作答器。
 *
 * 原来这里的「去练习」跳到练习页，由模型**另出一组新题** —— 那 6 道错题一道都不出现，
 * 用户做完以为练过了。这条通道不调 `generate`，交卷照样落作答记录、推进排期。
 */
function startWrongPractice() {
  if (!wrongItems.value.length) return
  runQuestions.value = asRunnerItems(wrongItems.value)
  runSource.value = 'wrong'
  practicing.value = true
  runKey.value += 1
}

async function onFinished(result) {
  toast.ok(`本轮复习完成：${result.correct_count}/${result.total}`)
  // 交卷已经把间隔推进了；错题本可能变短，下次切过去再拉
  wrongItems.value = []
  // **只更新头部数字，不动这一批题**：一 reload 队列，作答器的 props 就变了，
  // 到期题全在这批时结果页会被整块卸载（4-1），有剩余时每行题干会变空（4-2）
  try {
    const data = await api.dueReviews({ limit: 20 })
    applyCounts(data)
  } catch {
    // 数字没刷上不影响结果页；回列表时还会再拉一次
  }
}

function onRestart() {
  practicing.value = false
  runQuestions.value = []
  if (runSource.value === 'wrong') {
    wrongItems.value = []
    loadWrong()
    return
  }
  loadDue()
}

onMounted(loadDue)
</script>

<template>
  <div class="review">
    <header class="head">
      <div>
        <h1 class="page-title">复习</h1>
        <p class="page-sub">答错的题明天回来；答对一次就往后推，2 → 4 → 7 → 15 天</p>
      </div>
      <div class="stats">
        <!-- 一个数只有一个名字（4-5）：今日待复习 / 还没到期 / 错题 / 待人工判断 -->
        <span class="stat" :class="{ hot: total > 0 }">
          <b>{{ total }}</b> 今日待复习
        </span>
        <span class="stat"><b>{{ notYet }}</b> 还没到期</span>
        <span class="stat"><b>{{ wrongTotal }}</b> 错题</span>
        <span v-if="pending" class="stat"><b>{{ pending }}</b> 待人工判断</span>
      </div>
    </header>

    <nav class="tabs">
      <button class="tab" type="button" :class="{ on: tab === 'due' }" @click="switchTab('due')">
        今日待复习
      </button>
      <button class="tab" type="button" :class="{ on: tab === 'wrong' }" @click="switchTab('wrong')">
        错题本
      </button>
      <!-- 只在真有待判时出现：没有就不给一个永远空着的页签 -->
      <button
        v-if="pending"
        class="tab"
        type="button"
        :class="{ on: tab === 'pending' }"
        @click="switchTab('pending')"
      >
        待人工判断 {{ pending }}
      </button>
    </nav>

    <!-- 复习模式：吃 `runQuestions` 快照，交卷后队列变化不影响这一屏 -->
    <section v-if="practicing && runQuestions.length" class="panel">
      <QuizRunner
        :key="runKey"
        :questions="runQuestions"
        :restart-label="restartLabel"
        @finished="onFinished"
        @restart="onRestart"
      />
    </section>

    <!-- 待复习列表 -->
    <section v-else-if="tab === 'due'" class="panel">
      <div class="panel-bar">
        <span class="panel-note">
          {{ total ? `今日待复习 ${total} 题，一次最多做 20 题` : '今天没有待复习的题' }}
        </span>
        <button class="btn btn-primary btn-sm" type="button" :disabled="!items.length" @click="startPractice">
          开始复习{{ items.length ? `（${items.length}）` : '' }}
        </button>
      </div>

      <p v-if="loading" class="panel-note pad">加载中…</p>
      <p v-else-if="error" class="panel-note pad error">{{ error }}</p>
      <div v-else-if="!items.length" class="state">
        <p class="state-title">今天没有待复习的题</p>
        <p>去练习做几道，答过的题会按间隔回到这里。</p>
        <button class="btn btn-sm state-actions" type="button" @click="goPractice">去练习</button>
      </div>
      <ul v-else class="rows">
        <li v-for="item in items" :key="item.question_id" class="row">
          <span class="row-tag">{{ TYPE_LABELS[item.type] || item.type }}</span>
          <span class="row-main">{{ item.question }}</span>
          <button
            class="row-sub row-link"
            type="button"
            title="回知识库看这道题出自哪份内容"
            @click="openSource(item)"
          >{{ item.source_title || '未命名内容' }}</button>
          <span class="row-meta">
            间隔 {{ item.interval_days }} 天
            <template v-if="item.lapses"> · 忘过 {{ item.lapses }} 次</template>
          </span>
          <span class="row-time">{{ shortTime(item.due_local || item.due_at) }}</span>
        </li>
      </ul>
    </section>

    <!-- 错题本 -->
    <section v-else-if="tab === 'wrong'" class="panel">
      <div class="panel-bar">
        <span class="panel-note">最近一次作答仍答错的题。复习答对后自动移出。</span>
        <!-- 错题本的作用是「再练一遍」，所以有数据时也要给出口：此前只有空态才有「去练习」，
             翻着一屏错题却没有下一步，用户只能自己回导航找。
             两个出口要能分清：左边练**这些**错题（4-4），右边按内容重新出题。 -->
        <span class="panel-actions">
          <button
            v-if="wrongItems.length"
            class="btn btn-sm btn-primary"
            type="button"
            @click="startWrongPractice"
          >练这些错题（{{ wrongItems.length }}）</button>
          <button class="btn btn-sm" type="button" title="按选中的内容重新出一组题" @click="goPractice">
            去练习出新题
          </button>
          <button class="btn btn-sm" type="button" @click="loadWrong">刷新</button>
        </span>
      </div>
      <p v-if="wrongLoading" class="panel-note pad">加载中…</p>
      <p v-else-if="wrongError" class="panel-note pad error">{{ wrongError }}</p>
      <div v-else-if="!wrongItems.length" class="state">
        <p class="state-title">错题本是空的</p>
        <p>没有「最近一次答错」的题，或者都已经复习对了。</p>
        <button class="btn btn-sm state-actions" type="button" @click="goPractice">去练习</button>
      </div>
      <ul v-else class="rows">
        <li v-for="item in wrongItems" :key="item.question_id" class="row">
          <span class="row-tag">{{ TYPE_LABELS[item.type] || item.type }}</span>
          <span class="row-main">{{ item.question }}</span>
          <button
            class="row-sub row-link"
            type="button"
            title="回知识库看这道题出自哪份内容"
            @click="openSource(item)"
          >{{ item.source_title || '未命名内容' }}</button>
          <span class="row-meta">
            错 {{ item.wrong_count }} 次
            <template v-if="item.due_at"> · 下次 {{ shortTime(item.due_at) }}</template>
            <template v-else> · 未排期</template>
          </span>
          <span class="row-time">{{ shortTime(item.last_wrong_at) }}</span>
        </li>
      </ul>
    </section>

    <!-- 待人工判断（H5）：批改失败的简答，只有这里能裁定 -->
    <section v-else class="panel">
      <div class="panel-bar">
        <span class="panel-note">
          模型没判出来的简答。你看过之后算它对或错，判完就按正常规则排下一次复习。
        </span>
        <button class="btn btn-sm" type="button" @click="loadPending">刷新</button>
      </div>

      <p v-if="pendingLoading" class="panel-note pad">加载中…</p>
      <p v-else-if="pendingError" class="panel-note pad error">{{ pendingError }}</p>
      <div v-else-if="!pendingItems.length" class="state">
        <p class="state-title">没有待人工判断的题</p>
        <p>模型没判出来的简答会先留在这里，等你定对错。</p>
      </div>
      <ul v-else class="rows">
        <li v-for="item in pendingItems" :key="item.question_id" class="row row-pending">
          <span class="row-tag">{{ TYPE_LABELS[item.type] || item.type }}</span>
          <span class="row-main">{{ item.question }}</span>
          <button
            class="row-sub row-link"
            type="button"
            title="回知识库看这道题出自哪份内容"
            @click="openSource(item)"
          >{{ item.source_title || '未命名内容' }}</button>
          <span class="row-meta">{{ shortTime(item.last_pending_at) }} 判不出来</span>
          <span class="row-actions">
            <button
              class="btn btn-sm"
              type="button"
              :disabled="Boolean(judging[item.question_id])"
              @click="judge(item, true)"
            >算我对</button>
            <button
              class="btn btn-sm"
              type="button"
              :disabled="Boolean(judging[item.question_id])"
              @click="judge(item, false)"
            >算我错</button>
          </span>
          <span v-if="judgeError[item.question_id]" class="row-error">{{ judgeError[item.question_id] }}</span>
          <!-- 判「算我对 / 算我错」时得看见自己写了什么：只看题干和出处，用户只能靠回忆裁决。
               正确答案一直跟着接口回来（`answer`），此前只是没渲染；`user_answer` 由 M12 补进
               `_PENDING_SQL`。措辞与作答结果页统一（你的答案 / 正确答案）。 -->
          <span class="row-answer">
            <span class="ans"><b>你的答案</b>{{ answerText(item, item.user_answer) }}</span>
            <span class="ans">
              <b>正确答案</b>{{ item.answer ? answerText(item, item.answer) : '这题没存答案' }}
            </span>
          </span>
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

/* 面板条右侧两个按钮要成组：`space-between` 会把它们各自撑到中间和右边 */
.panel-actions {
  display: flex;
  gap: var(--space-2);
  margin-left: auto;
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

/* 出处做成按钮：颜色与普通副文本一致，hover 才显出可点，避免整行看起来像一堆链接 */
.row-link {
  padding: 0;
  border: 0;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.row-link:hover,
.row-link:focus-visible {
  color: var(--c-primary-ink);
  text-decoration: underline;
}

/* 待判行多一列按钮：多出来的宽度从题干列挤，别让按钮把标题顶成两行 */
.row-pending {
  grid-template-columns: 44px minmax(0, 1fr) 150px 130px auto;
  align-items: center;
}

.row-actions {
  display: flex;
  gap: var(--space-1);
  justify-self: end;
}

.row-error {
  grid-column: 2 / -1;
  font-size: var(--fs-xs);
  color: var(--c-danger-ink);
}

/* 待判行的「你的答案 / 正确答案」：单独占一行，左缘与题干列对齐。
   简答可能是好几行，允许换行；别用 nowrap，否则第二次裁定时只看得见前半句。 */
.row-answer {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-4);
  padding-left: calc(44px + var(--space-2));
  font-size: var(--fs-xs);
  line-height: 1.5;
  color: var(--c-text-2);
}

.row-answer b {
  margin-right: var(--space-1);
  font-weight: 500;
  color: var(--c-text-3);
}
</style>
