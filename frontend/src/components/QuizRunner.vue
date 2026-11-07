<script setup>
import { computed, ref } from 'vue'

import { api, friendlyMessage } from '../api/client'
import {
  answerText,
  difficultyLabel,
  judgeLocal,
  letterOf,
  typeLabel,
} from '../utils/quiz'

/**
 * 作答器（T4.5）：一题一屏 → 答完立刻知道对错与解析 → 全部答完一次性交卷 → 结果页。
 *
 * - **作答时不能回看已答题目**（M4 §6.6），只有结果页能全览
 * - 客观题用题目事件里带的 `answer` 本地即时判（`utils/quiz.judgeLocal`），
 *   交卷后以后端判分为准；简答本地不判，交卷后由 grader 批改
 * - `is_correct === null` 显示成「待人工判断」，**不许显示成答错**（M4 §1 约束 3）
 *
 * 父组件换题组时改 `:key`，本组件不监听 questions 变化（避免答题中途被打断）。
 */
const props = defineProps({
  questions: { type: Array, required: true },
  label: { type: String, default: '练习' },
})
const emit = defineEmits(['finished', 'restart'])

const phase = ref('answering')        // answering | submitting | result
const idx = ref(0)
const picked = ref([])                // 单选用 [letter]；多选用 letters
const typed = ref('')                 // 简答
const revealed = ref(false)
const verdict = ref(null)             // 本题本地判定：true/false/null
const answers = ref([])               // [{question_id, user_answer, duration_ms}]
const result = ref(null)
const error = ref('')
let startedAt = Date.now()

const current = computed(() => props.questions[idx.value] || null)
const total = computed(() => props.questions.length)
const isShort = computed(() => current.value?.type === 'short')
const canConfirm = computed(() => {
  if (!current.value) return false
  if (isShort.value) return typed.value.trim().length > 0
  return picked.value.length > 0
})
const isLast = computed(() => idx.value >= total.value - 1)

const drafts = computed(() => {
  const question = current.value
  if (!question) return null
  if (question.type === 'multiple') return picked.value
  if (question.type === 'boolean') return picked.value[0] === 'true'
  if (question.type === 'short') return typed.value.trim()
  return picked.value[0] || ''
})

const pendingManual = computed(
  () => (result.value?.items || []).filter((item) => item.is_correct === null).length
)

function choose(letter) {
  if (revealed.value) return
  if (current.value?.type === 'multiple') {
    const at = picked.value.indexOf(letter)
    if (at >= 0) picked.value.splice(at, 1)
    else picked.value.push(letter)
    picked.value.sort()
  } else {
    picked.value = [letter]
  }
}

function chooseBool(flag) {
  if (revealed.value) return
  picked.value = [flag ? 'true' : 'false']
}

function pickedLetters() {
  // 判断题用 'true'/'false' 占位，不能当成选项字母
  if (current.value?.type === 'boolean') return []
  return picked.value
}

function confirm() {
  if (!canConfirm.value || revealed.value) return
  const question = current.value
  const userAnswer = drafts.value
  answers.value.push({
    question_id: question.id,
    user_answer: userAnswer,
    duration_ms: Date.now() - startedAt,
  })
  verdict.value = judgeLocal(question, userAnswer)
  revealed.value = true
}

function next() {
  if (isLast.value) return submitAll()
  idx.value += 1
  picked.value = []
  typed.value = ''
  revealed.value = false
  verdict.value = null
  startedAt = Date.now()
}

async function submitAll() {
  phase.value = 'submitting'
  error.value = ''
  try {
    result.value = await api.quizSubmit({ answers: answers.value })
    phase.value = 'result'
    emit('finished', result.value)
  } catch (err) {
    error.value = friendlyMessage(err)
    phase.value = 'answering'
  }
}

function restart() {
  idx.value = 0
  picked.value = []
  typed.value = ''
  revealed.value = false
  verdict.value = null
  answers.value = []
  result.value = null
  error.value = ''
  phase.value = 'answering'
  startedAt = Date.now()
  emit('restart')
}

const questionOf = (questionId) =>
  props.questions.find((q) => q.id === questionId) || {}

/** 结果页要回显「我答了什么」：答案在本地 answers 里，后端响应只回判定 */
function lastAnswer(questionId) {
  const hit = answers.value.find((item) => item.question_id === questionId)
  return hit ? hit.user_answer : null
}

const accuracyText = computed(() => {
  const value = Number(result.value?.accuracy)
  return Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—'
})
</script>

<template>
  <div class="runner">
    <!-- 作答 -->
    <template v-if="phase === 'answering' && current">
      <div class="q-head">
        <span class="q-step">第 {{ idx + 1 }} / {{ total }} 题</span>
        <span class="q-tag">{{ typeLabel(current.type) }}</span>
        <span v-if="difficultyLabel(current.difficulty)" class="q-tag ghost">
          {{ difficultyLabel(current.difficulty) }}
        </span>
        <span v-if="current.source_title" class="q-src">{{ current.source_title }}</span>
      </div>

      <p class="q-text">{{ current.question }}</p>

      <div v-if="current.type === 'short'" class="q-body">
        <textarea
          v-model="typed"
          class="textarea"
          rows="6"
          :disabled="revealed"
          placeholder="凭记忆写下来，不用照抄原文；交卷后由模型指出漏掉的要点"
        />
      </div>

      <div v-else-if="current.type === 'boolean'" class="q-body opts">
        <button
          v-for="flag in [true, false]"
          :key="String(flag)"
          class="opt"
          type="button"
          :class="{ on: picked[0] === String(flag), right: revealed && verdict === flag,
                   wrong: revealed && picked[0] === String(flag) && verdict !== flag }"
          :disabled="revealed"
          @click="chooseBool(flag)"
        >
          <span class="opt-key">{{ flag ? '√' : '×' }}</span>
          <span class="opt-text">{{ flag ? '正确' : '错误' }}</span>
        </button>
      </div>

      <div v-else class="q-body opts">
        <button
          v-for="(option, index) in current.options"
          :key="index"
          class="opt"
          type="button"
          :class="{
            on: pickedLetters().includes(letterOf(index)),
            right: revealed && (current.answer || []).includes(letterOf(index)),
            wrong: revealed && pickedLetters().includes(letterOf(index))
              && !(current.answer || '').includes(letterOf(index)),
          }"
          :disabled="revealed"
          @click="choose(letterOf(index))"
        >
          <span class="opt-key">{{ letterOf(index) }}</span>
          <span class="opt-text">{{ option }}</span>
        </button>
        <p v-if="current.type === 'multiple'" class="opt-hint">多选题：选出所有正确项再确认</p>
      </div>

      <div v-if="revealed" class="verdict" :class="verdict === true ? 'ok' : verdict === false ? 'bad' : 'hold'">
        <strong v-if="verdict === true">答对了</strong>
        <strong v-else-if="verdict === false">
          答错了<template v-if="!isShort">，正确答案 {{ answerText(current, current.answer) }}</template>
        </strong>
        <strong v-else>已记录，交卷后由模型批改</strong>
        <p v-if="current.explanation" class="verdict-exp">{{ current.explanation }}</p>
      </div>

      <p v-if="error" class="runner-error">{{ error }}</p>

      <div class="q-actions">
        <button v-if="!revealed" class="btn btn-primary" type="button" :disabled="!canConfirm" @click="confirm">
          确认作答
        </button>
        <button v-else class="btn btn-primary" type="button" @click="next">
          {{ isLast ? '交卷并看结果' : '下一题' }}
        </button>
        <span v-if="!revealed && !canConfirm" class="q-hint">
          {{ isShort ? '写点东西再确认' : '选一个再确认' }}
        </span>
      </div>
    </template>

    <!-- 交卷中 -->
    <div v-else-if="phase === 'submitting'" class="state">
      <p class="state-title">交卷中…</p>
      <p>客观题很快；有简答题时要等模型批改，最多一分钟</p>
    </div>

    <!-- 结果 -->
    <div v-else-if="phase === 'result' && result" class="result">
      <div class="score">
        <div class="score-main">
          <b>{{ result.correct_count }}</b><span>/ {{ result.total }}</span>
        </div>
        <div class="score-side">
          <p class="score-acc">正确率 {{ accuracyText }}</p>
          <p v-if="pendingManual" class="score-hold">
            {{ pendingManual }} 题待人工判断（不计入正确、也不算错）
          </p>
          <button class="btn btn-sm" type="button" @click="restart">再来一组</button>
        </div>
      </div>

      <ul class="review-list">
        <li v-for="(item, index) in result.items" :key="item.question_id" class="review-item">
          <div class="review-head">
            <span
              class="mark"
              :class="item.is_correct === true ? 'ok' : item.is_correct === false ? 'bad' : 'hold'"
            >
              {{ item.is_correct === true ? '✓' : item.is_correct === false ? '✗' : '待判' }}
            </span>
            <span class="review-index">{{ index + 1 }}.</span>
            <span class="review-q">{{ questionOf(item.question_id).question }}</span>
          </div>
          <p class="review-line">
            <span>你的答案：<b>{{ answerText(questionOf(item.question_id), lastAnswer(item.question_id)) }}</b></span>
            <span v-if="questionOf(item.question_id).type !== 'short'">
              正确答案：<b>{{ answerText(questionOf(item.question_id), item.correct_answer) }}</b>
            </span>
          </p>
          <p v-if="item.feedback" class="review-feedback">{{ item.feedback }}</p>
          <p v-if="item.explanation" class="review-exp">{{ item.explanation }}</p>
        </li>
      </ul>
    </div>

    <div v-else class="state">
      <p class="state-title">没有题目</p>
      <p>题组是空的，换个条目或稍后再试</p>
    </div>
  </div>
</template>

<style scoped>
.runner {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: var(--space-4) var(--space-6);
}

.q-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.q-step {
  font-variant-numeric: tabular-nums;
  color: var(--c-text-2);
}

.q-tag {
  padding: 0 6px;
  border-radius: 999px;
  background: var(--c-primary-soft);
  color: var(--c-primary);
}

.q-tag.ghost {
  background: var(--c-bg-2);
  color: var(--c-text-2);
}

.q-src {
  margin-left: auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 40%;
}

.q-text {
  margin: var(--space-3) 0 var(--space-4);
  font-family: var(--font-reading);
  font-size: var(--fs-lg);
  line-height: var(--lh-title);
  color: var(--c-text-1);
}

.q-body {
  margin-bottom: var(--space-4);
}

.opts {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.opt {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  text-align: left;
  font-size: var(--fs-md);
  color: var(--c-text-1);
  cursor: pointer;
}

.opt:hover:not(:disabled) {
  border-color: var(--c-primary);
}

.opt.on {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}

.opt.right {
  border-color: var(--c-success);
  background: #edf6ef;
}

.opt.wrong {
  border-color: var(--c-danger);
  background: #fbeeec;
}

.opt:disabled {
  cursor: default;
}

.opt-key {
  flex: none;
  width: 20px;
  color: var(--c-text-3);
  font-family: var(--font-mono);
}

.opt-text {
  flex: 1;
  min-width: 0;
  white-space: pre-wrap;
}

.opt-hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.verdict {
  padding: var(--space-3);
  border-left: 3px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  font-size: var(--fs-sm);
}

.verdict.ok {
  border-left-color: var(--c-success);
}

.verdict.bad {
  border-left-color: var(--c-danger);
}

.verdict.hold {
  border-left-color: var(--c-warning);
}

.verdict-exp {
  margin: var(--space-2) 0 0;
  color: var(--c-text-2);
  line-height: var(--lh-body);
  white-space: pre-wrap;
}

.q-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.q-hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.runner-error {
  margin: var(--space-3) 0 0;
  color: var(--c-danger);
  font-size: var(--fs-sm);
}

.score {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
}

.score-main {
  font-size: var(--fs-xl);
  color: var(--c-text-1);
  font-variant-numeric: tabular-nums;
}

.score-main b {
  font-size: 32px;
  color: var(--c-primary);
}

.score-main span {
  margin-left: var(--space-1);
  color: var(--c-text-3);
}

.score-side {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.score-acc {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.score-hold {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-warning);
}

.review-list {
  margin: var(--space-3) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.review-item {
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.review-head {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  font-size: var(--fs-md);
  color: var(--c-text-1);
}

.mark {
  flex: none;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}

.mark.ok {
  color: var(--c-success);
}

.mark.bad {
  color: var(--c-danger);
}

.mark.hold {
  color: var(--c-warning);
}

.review-index {
  flex: none;
  color: var(--c-text-3);
}

.review-q {
  flex: 1;
  min-width: 0;
}

.review-line,
.review-feedback,
.review-exp {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: var(--lh-body);
}

.review-line {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-4);
}

.review-exp {
  color: var(--c-text-3);
}

.review-feedback {
  color: var(--c-primary);
}
</style>
