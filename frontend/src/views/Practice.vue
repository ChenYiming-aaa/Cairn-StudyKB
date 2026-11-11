<script setup>
import { computed, onMounted, ref } from 'vue'

import { api, friendlyMessage, humanDetail, streamSSE } from '../api/client'
import QuizRunner from '../components/QuizRunner.vue'
import RailToggle from '../components/RailToggle.vue'
import SidePanel from '../components/SidePanel.vue'
import { useLayout } from '../composables/useLayout'
import { useTimer } from '../composables/useTimer'
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
// T5.3：练习页也能直接开一轮专注，目标带入当前选中的来源条目
const { start: startSession } = useTimer()
// T7.3：配置栏接入 SidePanel；出题开始后自动收成窄条（答题要的是屏占）
const { collapse, expand, isCollapsed } = useLayout()
// 只有「本页自动收的」才自动展开回来，用户自己收起的不抢方向盘
let autoCollapsedConfig = false

async function startFocus() {
  if (itemId.value === null) return
  const created = await startSession({
    target_type: 'item',
    target_id: itemId.value,
    planned_seconds: 1500,
  })
  if (created) toast.info(`开始专注：${pickedTitle.value}`)
}

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

const pickedTitle = computed(() => items.value.find((it) => it.id === itemId.value)?.title || '')
const canGenerate = computed(() => itemId.value !== null && types.value.length > 0)
const estimate = computed(() => (count.value > 10 ? '约需 30–60 秒' : '约 10–20 秒'))

async function loadItems() {
  loading.value = true
  listError.value = ''
  try {
    // 只有 ready 的条目有正文与 chunk，pending 的还出不了题
    const data = await api.listItems({ status: 'ready', page_size: PAGE_SIZE, q: keyword.value || undefined })
    items.value = data.items || []
    total.value = data.total || 0
    if (!items.value.some((it) => it.id === itemId.value)) itemId.value = items.value[0]?.id ?? null
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

async function generate() {
  if (!canGenerate.value || phase.value === 'generating') return
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
    if (!questions.value.length && !genError.value) {
      toast.error('一题都没出出来，换个内容或题型再试')
    }
  }
}

function stopGenerating() {
  controller?.abort()
  if (!questions.value.length) toast.info('已停止生成')
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
  // 「再来一组」要重新选题型/题数，本页自动收的那次顺手还回去
  restoreConfig()
}

/** 交卷后自动回到 idle 之外的「再来一组」由 QuizRunner 抛 restart，这里只提示一下 */
function onFinished(result) {
  if (result?.total) {
    toast.ok(`本组完成：${result.correct_count}/${result.total}`)
  }
}

function onRestart() {
  backToIdle()
}

onMounted(loadItems)
</script>

<template>
  <div class="practice">
    <header class="head">
      <div>
        <h1 class="page-title">练习</h1>
        <p class="page-sub">拿自己的材料出题考自己，答错的题目明天会自动回来找你</p>
      </div>
      <button class="btn btn-sm" type="button" :disabled="itemId === null" @click="startFocus">
        开始专注{{ pickedTitle ? `：${pickedTitle}` : '' }}
      </button>
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
            <input
              v-model="keyword"
              class="input"
              type="search"
              placeholder="搜标题…"
              @keydown.enter="loadItems"
            />
            <p v-if="loading" class="cfg-note">加载中…</p>
            <p v-else-if="listError" class="cfg-note error">{{ listError }}</p>
            <p v-else-if="!items.length" class="cfg-note">
              还没有整理好的内容。到知识库点「开始整理」，整理完就能出题。
            </p>
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
                  <span class="item-cat">{{ item.category || '未分类' }}</span>
                </button>
              </li>
            </ul>
            <p v-if="!loading && total > items.length" class="cfg-note">
              仅显示前 {{ items.length }} / {{ total }} 条，用关键词缩小范围
            </p>
          </section>

          <section class="cfg-block">
            <h2 class="cfg-title">题型</h2>
            <div class="chips">
              <button
                v-for="type in TYPES"
                :key="type"
                class="chip"
                type="button"
                :class="{ on: types.includes(type) }"
                :disabled="phase === 'generating'"
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

          <div class="cfg-foot">
            <button
              class="btn btn-primary"
              type="button"
              :disabled="!canGenerate || phase !== 'idle'"
              :title="phase === 'answering' ? '先做完这一组，或点结果页的「再来一组」' : ''"
              @click="generate"
            >
              {{ phase === 'generating' ? '出题中…' : `出题${pickedTitle ? `：${pickedTitle}` : ''}` }}
            </button>
            <p class="cfg-note">{{ estimate }}</p>
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
            <span class="pulse" />
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
                <p class="gen-meta">{{ TYPE_LABELS[q.type] }} · 已入库 #{{ q.id }}</p>
              </div>
            </li>
          </ul>
          <p class="gen-note">
            出完会自动开始作答。等太久可以点「停止生成」，已经出的题照样能做。
          </p>
        </div>

        <!-- 作答 / 交卷 / 结果 -->
        <QuizRunner
          v-else-if="phase === 'answering' && questions.length"
          :key="runKey"
          :questions="questions"
          @finished="onFinished"
          @restart="onRestart"
        />

        <!-- 空态 -->
        <div v-else class="state">
          <p class="state-title">{{ genError ? '出题失败' : '还没开始' }}</p>
          <p v-if="genError" class="state-error">{{ genError }}</p>
          <p v-else>左侧挑一条材料、选题型与题数，点「出题」</p>
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

.cfg-title {
  margin: 0;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--c-text-3);
  letter-spacing: 0.04em;
}

.cfg-note {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.cfg-note.error {
  color: var(--c-danger-ink);
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
  animation: pop-in 0.22s ease;
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

@keyframes pop-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
