<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, friendlyMessage, humanDetail, streamSSE } from '../api/client'
import QuizRunner from '../components/QuizRunner.vue'
import RailToggle from '../components/RailToggle.vue'
import SidePanel from '../components/SidePanel.vue'
import { useLayout } from '../composables/useLayout'
import { useToast } from '../composables/useToast'
import { DIFFICULTY_LABELS, TYPE_LABELS } from '../utils/quiz'

/**
 * 练习页（T4.5）：选条目 → 出题（SSE 逐题浮现）→ 作答 → 交卷 → 结果。
 *
 * 状态机（M4 §6.6）：idle → generating → answering → submitting → result。
 * submitting/result 在 `QuizRunner` 里（它是唯一知道答案与交卷时机的组件），
 * 本页只管「出题」和「交出题组」。
 *
 * 生成过程中允许「停止生成」：中断的是 SSE 连接，**已收到的题保留**——
 * 后端的题在 emit 之前就已经入库，中断不会留下半截题。
 */
const PAGE_SIZE = 100
const COUNTS = [5, 10, 20]
const TYPES = ['single', 'multiple', 'boolean', 'short']
const DIFFICULTIES = ['basic', 'understand', 'apply']

const toast = useToast()
const router = useRouter()
const route = useRoute()
// 详情页「练这条」带过来的材料 id。**只消费一次**：之后用户自己搜索、自己点选，
// 不该被这个参数反复拽回去（否则列表一刷新就被打回原来那条）。
const preselect = ref(Number(route.query.item) || null)
// 试卷复核页「导入完直接做」带过来的标记（2026-11-17）：材料已选好就不该再让用户
// 点一次「按卷练」。同样只消费一次，且只在选中的确实是试卷时才动手。
const openPaper = ref(route.query.paper === '1')
// T7.3：配置栏接入 SidePanel；出题开始后自动收成窄条（答题要的是屏占）
const { collapse, expand, isCollapsed } = useLayout()
// 只有「本页自动收的」才自动展开回来，用户自己收起的不抢方向盘
let autoCollapsedConfig = false

const phase = ref('idle')          // idle | generating | answering
const items = ref([])
const total = ref(0)
const loading = ref(true)
const listError = ref('')
const keyword = ref('')

const itemId = ref(null)
const types = ref(['single'])
const difficulty = ref('understand')
const count = ref(5)

const questions = ref([])
const skips = ref(0)
const requested = ref(0)
const genError = ref('')
const runKey = ref(0)
let controller = null

/**
 * 中途离开的续跑记录（4-3）。
 *
 * 复习页重进时题组还在队列里，作答器自己就能接上草稿；练习页不同 —— 题是现出的，
 * 重进页面只剩配置栏，作答器那份草稿找不到它的题组。所以这里连题组一起存一份。
 * 作答进度本身仍由 `QuizRunner` 存（`cairn.quiz.draft`），两边靠题组签名对齐。
 */
const RUN_KEY = 'cairn.practice.run'
const QUIZ_DRAFT_KEY = 'cairn.quiz.draft'
// 已经替用户问过「是否继续」：作答器静默接上，不再弹第二次
const resumeQuiet = ref(false)

function readJson(key) {
  try {
    return JSON.parse(sessionStorage.getItem(key) || 'null')
  } catch {
    return null
  }
}

function clearRun() {
  try {
    sessionStorage.removeItem(RUN_KEY)
  } catch {
    // 存储被禁只影响「能不能续跑」
  }
}

function saveRun() {
  if (phase.value !== 'answering' || !questions.value.length) return
  try {
    sessionStorage.setItem(RUN_KEY, JSON.stringify({
      questions: questions.value,
      itemId: itemId.value,
      types: types.value,
      difficulty: difficulty.value,
      count: count.value,
      paper: paperRun.value,
      pool: poolRun.value,
    }))
  } catch {
    // 同上
  }
}

watch([phase, questions], saveRun)

/**
 * 回来时先问一句「是否继续上次答题」：题组、配置、作答进度一起搬回来。
 * 只有**确实答过几道**才问 —— 刚出完题没答就丢了，再出一组就行，不值得拦一下。
 */
function resumeRun() {
  const run = readJson(RUN_KEY)
  if (!run || !Array.isArray(run.questions) || !run.questions.length) {
    clearRun()
    return
  }
  const draft = readJson(QUIZ_DRAFT_KEY)
  const same = draft
    && draft.sign === run.questions.map((q) => q.id).join(',')
    && (draft.answers || []).length
  if (!same) {
    clearRun()
    return
  }
  const at = Math.min(Math.max(0, Number(draft.idx) || 0), run.questions.length - 1)
  if (!window.confirm(`发现您上次中途退出答题（第 ${at + 1} / ${run.questions.length} 题），是否继续上次答题？`)) {
    clearRun()
    try {
      sessionStorage.removeItem(QUIZ_DRAFT_KEY)
    } catch {
      // 清不掉也不影响下一次（签名对不上会自己失效）
    }
    return
  }
  questions.value = run.questions
  if (run.itemId !== undefined) itemId.value = run.itemId
  if (Array.isArray(run.types) && run.types.length) types.value = run.types
  if (run.difficulty) difficulty.value = run.difficulty
  if (run.count) count.value = run.count
  paperRun.value = Boolean(run.paper)
  poolRun.value = Boolean(run.pool)
  resumeQuiet.value = true
  phase.value = 'answering'
  runKey.value += 1
}

const pickedTitle = computed(() => items.value.find((it) => it.id === itemId.value)?.title || '')
const canGenerate = computed(() => itemId.value !== null && types.value.length > 0)
const estimate = computed(() => (count.value > 10 ? '约需 30–60 秒' : '约 10–20 秒'))

/**
 * 选中的是不是一份试卷（T10.5）。
 *
 * 试卷的题是导进来的、题号原样保留，题型/难度/题数都不该让用户再选一遍 ——
 * 选了也不会生效（按卷练拿的是整份卷子）。所以选中试卷时配置区切成「按卷练」。
 */
const pickedItem = computed(() => items.value.find((it) => it.id === itemId.value) || null)
const isExam = computed(() => pickedItem.value?.kind === 'exam')
const paperLoading = ref(false)
// 这一轮是不是按卷练。快照而不是读 `isExam`：作答中途换材料不该改掉正在做的那一轮
const paperRun = ref(false)

// 这条内容上已经有多少题（「做已有题」的入口与计数，方案 §3.2）
const poolTotal = = ref(0)   // 故意改坏：验 CI 会拦
const poolLoading = ref(false)
// 这一轮是不是在做已有题。与 paperRun 分开：题号只有试卷有，两者的呈现不一样
const poolRun = ref(false)
// 点材料点得快时会有多个请求在飞，只认最后一次的回包（否则先发的慢回包会盖掉后选的）
let poolSeq = 0

// 舞台失败标题：出题失败和取题失败是两件事，用户看标题就知道刚才点的是哪个
const errorTitle = ref('出题失败')

/**
 * 取「已有题」的条数。只对非试卷取：试卷的入口是「按卷练」，两颗入口按钮会互相抢戏。
 * 失败不提示 —— 拿不到数只是少一个次要入口，配置栏不该因此报红。
 */
async function loadPool() {
  const seq = ++poolSeq
  poolTotal.value = 0
  if (itemId.value === null || isExam.value) return
  try {
    const data = await api.itemQuestions(itemId.value)
    if (seq === poolSeq) poolTotal.value = Number(data.total) || 0
  } catch {
    // 见上：静默。下次换材料或出完题会再问一次
  }
}

// 换材料就重新数一遍（首次加载时 itemId 由 null 变成首条，也会走到这里）
watch(itemId, loadPool)

async function loadItems() {
  loading.value = true
  listError.value = ''
  try {
    // 只有 ready 的条目有正文与 chunk，pending 的还出不了题
    const data = await api.listItems({ status: 'ready', page_size: PAGE_SIZE, q: keyword.value || undefined })
    items.value = data.items || []
    total.value = data.total || 0
    const wanted = preselect.value
    preselect.value = null
    if (wanted && items.value.some((it) => it.id === wanted)) {
      itemId.value = wanted
    } else if (!items.value.some((it) => it.id === itemId.value)) {
      // 带过来的那条不在列表里（还没整理好，或排在前 100 条之外）：说一句，别默默换成第一条
      if (wanted) toast.info('这条还没整理好，出不了题。先从下面选一条。')
      itemId.value = items.value[0]?.id ?? null
    }
  } catch (err) {
    listError.value = friendlyMessage(err)
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function toggleType(type) {
  const at = types.value.indexOf(type)
  if (at >= 0) {
    if (types.value.length === 1) return   // 至少留一种题型
    types.value.splice(at, 1)
  } else {
    types.value.push(type)
  }
}

/** 只剩一种题型时，那个 chip 点了没反应 —— 置灰并说明，别让用户以为自己点漏了 */
function isLastType(type) {
  return types.value.length === 1 && types.value.includes(type)
}

async function generate() {
  if (!canGenerate.value || phase.value === 'generating') return
  paperRun.value = false
  poolRun.value = false
  errorTitle.value = '出题失败'
  // 新出一组就是新的一轮：上一轮的续跑记录（如果还有）到此作废
  clearRun()
  phase.value = 'generating'
  questions.value = []
  skips.value = 0
  requested.value = count.value
  genError.value = ''
  controller = new AbortController()
  // 开始出题后配置就不该再占屏占了；收成窄条，回来点一下就能展开
  autoCollapsedConfig = !isCollapsed('config')
  if (autoCollapsedConfig) collapse('config')

  try {
    await streamSSE(
      '/api/quiz/generate',
      {
        item_id: itemId.value,
        types: types.value,
        difficulty: difficulty.value,
        count: count.value,
      },
      (ev) => {
        if (ev.type === 'question') questions.value.push(ev.question)
        else if (ev.type === 'skip') skips.value += 1
        else if (ev.type === 'error') {
          const detail = humanDetail(ev.detail)
          genError.value = `${ev.message || '出题失败'}${detail ? `（${detail}）` : ''}`
        }
        else if (ev.type === 'done') requested.value = ev.requested ?? requested.value
      },
      { signal: controller.signal }
    )
  } catch (err) {
    if (err?.name !== 'AbortError') genError.value = friendlyMessage(err)
  } finally {
    controller = null
    phase.value = questions.value.length ? 'answering' : 'idle'
    // 一题都没出出来（失败/手动停）：配置得还回去，否则用户改不了题型再来一次
    if (phase.value === 'idle') restoreConfig()
    runKey.value += 1
    // 这一轮往库里加了题：回到配置时「做已有题（N）」上的数字要是新的
    if (questions.value.length) loadPool()
    if (!questions.value.length && !genError.value) {
      toast.error('一题都没出出来，换个内容或题型再试')
    }
  }
}

function stopGenerating() {
  controller?.abort()
  if (!questions.value.length) toast.info('已停止生成')
}

/**
 * 按卷练（T10.5）：把整份卷子的题取回来直接作答，不走模型。
 *
 * 没有「出题」这一步，所以不显示进度条也不占 SSE —— 试卷导入时题已经在库里了。
 * 排序由后端按原卷题号给，前端不再排（TEXT 题号直接排会把第 10 题排到第 2 题前面）。
 */
async function startPaper() {
  if (!itemId.value || phase.value !== 'idle' || paperLoading.value) return
  paperLoading.value = true
  genError.value = ''
  errorTitle.value = '取题失败'
  try {
    const data = await api.quizPaper(itemId.value)
    questions.value = data.questions || []
    requested.value = questions.value.length
    skips.value = 0
    if (!questions.value.length) toast.info('这份试卷还没有导进题目')
    else {
      paperRun.value = true
      poolRun.value = false
      phase.value = 'answering'
    }
  } catch (err) {
    genError.value = `${friendlyMessage(err)}${humanDetail(err.detail) ? `（${humanDetail(err.detail)}）` : ''}`
  } finally {
    paperLoading.value = false
    runKey.value += 1
  }
}

/**
 * 做已有题：把这条内容上现存的题取回来直接作答，不走模型（方案 §3.2）。
 *
 * 和「按卷练」只差来源与题号：题池里的题没有原卷题号，所以不标「原卷 N 题」。
 * 相同的是「题已经在库里」—— 交卷后能原样再做一遍，不用再花一次调用重新出题。
 */
async function startPool() {
  if (!itemId.value || phase.value !== 'idle' || poolLoading.value) return
  poolLoading.value = true
  genError.value = ''
  errorTitle.value = '取题失败'
  try {
    const data = await api.itemQuestions(itemId.value)
    questions.value = data.questions || []
    poolTotal.value = questions.value.length
    requested.value = questions.value.length
    skips.value = 0
    if (!questions.value.length) {
      toast.info('这条内容还没有题，先出几道')
    } else {
      poolRun.value = true
      paperRun.value = false
      phase.value = 'answering'
    }
  } catch (err) {
    genError.value = `${friendlyMessage(err)}${humanDetail(err.detail) ? `（${humanDetail(err.detail)}）` : ''}`
  } finally {
    poolLoading.value = false
    runKey.value += 1
  }
}

/** 本页自动收起的那一次，换回展开；用户自己收的不管 */
function restoreConfig() {
  if (!autoCollapsedConfig) return
  autoCollapsedConfig = false
  expand('config')
}

function backToIdle() {
  phase.value = 'idle'
  questions.value = []
  genError.value = ''
  skips.value = 0
  resumeQuiet.value = false
  // 这一轮结束了：别再让下次进来问「是否继续」
  clearRun()
  // 「再来一组」要重新选题型/题数，本页自动收的那次顺手还回去
  restoreConfig()
}

/** 交卷后自动回到 idle 之外的「再来一组」由 QuizRunner 抛 restart，这里只提示一下 */
function onFinished(result) {
  clearRun()
  if (result?.total) {
    toast.ok(`${paperRun.value ? '本卷' : '本组'}完成：${result.correct_count}/${result.total}`)
  }
}

async function onRestart() {
  backToIdle()
  // 试卷与已有题都一样：题在库里，重开同一批，不必让用户回左侧再点一次。
  // 生成的题组仍然回配置 —— 题是现出的，得重选题型与题数。
  if (paperRun.value) await startPaper()
  else if (poolRun.value) await startPool()
}

onMounted(async () => {
  await loadItems()
  // 从试卷复核页进来的：材料已选好、题已在库里，直接开卷
  if (openPaper.value) {
    openPaper.value = false
    if (isExam.value) {
      await startPaper()
      return
    }
  }
  // 上次做到一半的那组：进来先问一句「是否继续上次答题」（4-3）
  resumeRun()
})
</script>

<template>
  <div class="practice">
    <header class="head">
      <div>
        <h1 class="page-title">练习</h1>
        <p class="page-sub">用自己的材料出题；答错的明天回来</p>
      </div>
    </header>

    <div class="body">
      <SidePanel target="config" class="config" rail title="出题配置">
        <div class="config-body">
          <div class="panel-bar">
            <span class="panel-name">出题配置</span>
            <RailToggle target="config" />
          </div>

          <section class="cfg-block">
            <h2 class="cfg-title">从哪条材料出题</h2>
            <!-- 列表一长就滚出视野、收起后更是看不见；这一行随时回答「现在拿的是哪条」 -->
            <p v-if="pickedTitle" class="cfg-current" :title="pickedTitle">当前材料：{{ pickedTitle }}</p>
            <input
              v-model="keyword"
              class="input"
              type="search"
              placeholder="搜标题…"
              @keydown.enter="loadItems"
            />
            <p v-if="loading" class="cfg-note">加载中…</p>
            <p v-else-if="listError" class="cfg-note error">{{ listError }}</p>
            <!-- 空态：一句现状 + 一个能点的出口（L 组）。只说「到知识库去」而不给按钮，
                 等于让用户自己找路 —— 与列表空态（已有采集按钮）的句式对齐 -->
            <div v-else-if="!items.length" class="cfg-empty">
              <p v-if="keyword" class="cfg-note">标题里没有「{{ keyword }}」。换个词，或者<button class="link-btn" type="button" @click="router.push('/ask')">去检索正文</button></p>
              <template v-else>
                <p class="cfg-note">还没有整理好的内容，整理完就能出题。</p>
                <button class="btn btn-ghost btn-sm" type="button" @click="router.push('/')">
                  去知识库
                </button>
              </template>
            </div>
            <ul v-else class="item-list">
              <li v-for="item in items" :key="item.id">
                <button
                  class="item-row"
                  type="button"
                  :class="{ on: item.id === itemId }"
                  :disabled="phase === 'generating'"
                  @click="itemId = item.id"
                >
                  <span class="item-title">{{ item.title }}</span>
                  <span v-if="item.kind === 'exam'" class="item-cat exam">试卷</span>
                  <span v-else class="item-cat">{{ item.category || '未分类' }}</span>
                </button>
              </li>
            </ul>
            <p v-if="!loading && total > items.length" class="cfg-note">
              显示前 {{ items.length }} / {{ total }} 条
            </p>
          </section>

          <template v-if="!isExam">
            <section class="cfg-block">
              <h2 class="cfg-title">题型</h2>
              <div class="chips">
                <button
                  v-for="type in TYPES"
                  :key="type"
                  class="chip"
                  type="button"
                  :class="{ on: types.includes(type) }"
                  :disabled="phase === 'generating' || isLastType(type)"
                  :title="isLastType(type) ? '至少留一种题型' : ''"
                  @click="toggleType(type)"
                >
                  {{ TYPE_LABELS[type] }}
                </button>
              </div>
            </section>

            <section class="cfg-block">
              <h2 class="cfg-title">难度</h2>
              <div class="chips">
                <button
                  v-for="level in DIFFICULTIES"
                  :key="level"
                  class="chip"
                  type="button"
                  :class="{ on: difficulty === level }"
                  :disabled="phase === 'generating'"
                  @click="difficulty = level"
                >
                  {{ DIFFICULTY_LABELS[level] }}
                </button>
              </div>
            </section>

            <section class="cfg-block">
              <h2 class="cfg-title">题数</h2>
              <div class="chips">
                <button
                  v-for="n in COUNTS"
                  :key="n"
                  class="chip"
                  type="button"
                  :class="{ on: count === n }"
                  :disabled="phase === 'generating'"
                  @click="count = n"
                >
                  {{ n }} 题
                </button>
              </div>
            </section>
          </template>

          <div class="cfg-foot">
            <button
              v-if="isExam"
              class="btn btn-primary"
              type="button"
              :disabled="phase !== 'idle' || paperLoading"
              :title="paperLoading ? '' : `按卷练：${pickedTitle}`"
              @click="startPaper"
            >
              <span class="btn-label">{{ paperLoading ? '正在取题…' : `按卷练：${pickedTitle}` }}</span>
            </button>
            <template v-else>
              <button
                class="btn btn-primary"
                type="button"
                :disabled="!canGenerate || phase !== 'idle'"
                :title="phase === 'answering'
                  ? '先做完这一组，或点结果页的「再来一组」'
                  : (pickedTitle ? `出题：${pickedTitle}` : '出题')"
                @click="generate"
              >
                <span class="btn-label">{{ phase === 'generating' ? '出题中…' : `出题${pickedTitle ? `：${pickedTitle}` : ''}` }}</span>
              </button>
              <p class="cfg-note">{{ estimate }}</p>
              <!-- 已有的题可以重做：不花一次调用重新出，做过的也能再走一遍（方案 §3.2）。
                   没有题就不渲染 —— 一个点下去只弹「还没有题」的按钮不如不出现 -->
              <button
                v-if="poolTotal > 0"
                class="btn cfg-alt"
                type="button"
                :disabled="phase !== 'idle' || poolLoading"
                @click="startPool"
              >
                <span class="btn-label">{{ poolLoading ? '正在取题…' : `做已有题（${poolTotal}）` }}</span>
              </button>
            </template>
          </div>
        </div>

        <template #rail>
          <RailToggle target="config" />
          <span class="rail-label">出题配置</span>
        </template>
      </SidePanel>

      <section class="stage">
        <!-- 出题中：题面逐题浮现 -->
        <div v-if="phase === 'generating'" class="gen">
          <div class="gen-bar">
            <span class="gen-text">
              正在出题，已收到 {{ questions.length }} / {{ count }} 题
            </span>
            <button class="btn btn-sm" type="button" @click="stopGenerating">停止生成</button>
          </div>
          <ul class="gen-list">
            <li v-for="(q, index) in questions" :key="q.id" class="gen-card">
              <span class="gen-index">{{ index + 1 }}</span>
              <div class="gen-body">
                <p class="gen-q">{{ q.question }}</p>
                <p class="gen-meta">{{ TYPE_LABELS[q.type] }} · #{{ q.id }}</p>
              </div>
            </li>
          </ul>
          <p class="gen-note">
            出完自动开始作答；停止后已出的题照样能做
          </p>
        </div>

        <!-- 作答 / 交卷 / 结果 -->
        <QuizRunner
          v-else-if="phase === 'answering' && questions.length"
          :key="runKey"
          :questions="questions"
          :numbered="paperRun"
          :restart-label="paperRun || poolRun ? '再做一遍' : '回配置再出一组'"
          :auto-resume="resumeQuiet"
          @finished="onFinished"
          @restart="onRestart"
        />

        <!-- 空态 -->
        <div v-else class="state">
          <p class="state-title">{{ genError ? errorTitle : '还没开始' }}</p>
          <p v-if="genError" class="state-error">{{ genError }}</p>
          <p v-else-if="isExam">左侧已选好试卷，点「按卷练」开始</p>
          <p v-else-if="poolTotal > 0">左侧选好材料，点「出题」新出一组，或点「做已有题」重做</p>
          <p v-else>左侧选好材料，点「出题」</p>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.practice {
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

.body {
  flex: 1;
  min-height: 0;
  display: grid;
  /* T7.3：配置栏宽度归 useLayout（可拖可记），收起时是 44px 窄条 */
  grid-template-columns: var(--w-config) minmax(0, 1fr);
  gap: var(--space-4);
  margin-top: var(--space-4);
}

/* 边框与底色由 SidePanel 给，这里只管滚动与内间距 */
.config-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  overflow-y: auto;
  padding: var(--space-3);
}

.cfg-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-height: 0;
}

/* 字段标签（题型 / 难度 / 题数）：比面板名（panel-name）低一档，比说明文字高一档。
   原先 12/600/text-3 —— 与提示文字同色，整列三层全是灰的。 */
.cfg-title {
  margin: 0;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--c-text-2);
  letter-spacing: 0.04em;
}

.cfg-current {
  margin: 0;
  overflow: hidden;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cfg-note {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.cfg-note.error {
  color: var(--c-danger-ink);
}

.cfg-empty {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  align-items: flex-start;
}

.item-list {
  flex: 1;
  min-height: 0;
  max-height: 220px;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}

.item-row {
  width: 100%;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: none;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text-1);
  cursor: pointer;
}

.item-row:hover:not(:disabled) {
  background: var(--c-bg-2);
}

.item-row.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-cat {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

/* 试卷用主色标一下：列表里混着「试卷」和「材料」，两者点了之后行为不一样 */
.item-cat.exam {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.chip {
  padding: 3px var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: 999px;
  background: var(--c-bg-1);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  cursor: pointer;
}

.chip.on {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.cfg-foot {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: auto;
  padding-top: var(--space-3);
  border-top: 1px solid var(--c-border);
}

/* 次要入口（做已有题）和主入口之间留一档：贴太近会像同一件事的两种说法 */
.cfg-alt {
  margin-top: var(--space-1);
}

/* 配置栏能拖到 240px，标题却可能 20 字以上。`.btn` 是 inline-flex + nowrap，
   不压窄就只会把文字顶到按钮边框外面硬切掉 —— 看不出少了字，也没提示全文。
   统一走省略号，全文由按钮的 title 兜住（2026-11-26 修）。 */
.cfg-foot .btn {
  min-width: 0;
}

.cfg-foot .btn-label {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  overflow: hidden;
}

.gen {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--space-4) var(--space-6);
}

.gen-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.gen-text {
  flex: 1;
}

.gen-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.gen-card {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  /* 只淡入，不做位移：一屏可能连着出十来题，每条各往上游 6px，叠起来是"整页往上涌"
     —— 那是整页尺度的空间运动，前庭负担最大的一类，而它传达的信息（"这张卡是新的"）
     淡入已经说全了。同理不再需要 reduce 覆盖：淡入不属于空间运动。 */
  animation: fade-in var(--dur-enter) ease;
}

.gen-index {
  flex: none;
  width: 20px;
  color: var(--c-text-3);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.gen-body {
  flex: 1;
  min-width: 0;
}

.gen-q {
  margin: 0;
  font-size: var(--fs-md);
  color: var(--c-text-1);
  line-height: var(--lh-body);
}

.gen-meta {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.gen-note {
  margin: var(--space-3) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
