<script setup>
/**
 * 出题结果：能直接作答、立刻判对错，并显示讲解。
 *
 * 判分在本地，不走模型 —— 与桌面版一致（客观题本地比对，简答才交给人/模型）。
 * 所以这里看到的是真判分，不是预先写好的对错。
 */
import { computed, reactive } from 'vue'

const props = defineProps({
  questions: { type: Array, required: true },
})

const picked = reactive({})
const checked = reactive({})

const LETTERS = 'ABCDEFGH'

function typeLabel(q) {
  return { single: '单选', multiple: '多选', boolean: '判断', short: '简答' }[q.type] || q.type || '题目'
}

/** 选项统一成 `[{key, text}]`：判断题的 key 是「对 / 错」，单选的 key 是 A/B/C/D */
function optionsOf(q) {
  if (q.type === 'boolean') {
    return [
      { key: 'true', text: '对' },
      { key: 'false', text: '错' },
    ]
  }
  return (q.options || []).map((text, i) => ({ key: LETTERS[i], text }))
}

function verdictOf(q) {
  const got = picked[q.idx]
  if (got == null) return null
  if (q.type === 'short' || q.type === 'multiple') return null
  if (q.type === 'boolean') return String(got) === String(q.answer)
  return String(got) === String(q.answer).trim().toUpperCase()
}

const scored = computed(() => {
  let right = 0
  let total = 0
  for (const q of props.questions) {
    if (q.type === 'short' || q.type === 'multiple') continue
    if (picked[q.idx] == null) continue
    total += 1
    if (verdictOf(q)) right += 1
  }
  return { right, total }
})

function answerText(q) {
  if (q.type === 'boolean') return q.answer === true || q.answer === 'true' ? '对' : '错'
  if (Array.isArray(q.answer)) return q.answer.join('、')
  return String(q.answer ?? '')
}
</script>

<template>
  <div class="quiz">
    <div v-for="q in questions" :key="q.idx" class="q">
      <div class="stem">
        <span class="badge">{{ typeLabel(q) }}</span>
        <span>{{ q.question }}</span>
      </div>

      <div v-if="q.type === 'short'" class="short">
        <p class="hint">简答题，先自己想一下再看参考答案。</p>
        <button type="button" class="ghost" @click="checked[q.idx] = !checked[q.idx]">
          {{ checked[q.idx] ? '收起来' : '看参考答案' }}
        </button>
        <p v-if="checked[q.idx]" class="ref">{{ answerText(q) }}</p>
      </div>

      <template v-else>
        <div class="opts">
          <button
            v-for="opt in optionsOf(q)"
            :key="opt.key"
            type="button"
            class="opt"
            :class="{
              on: picked[q.idx] === opt.key,
              right: checked[q.idx] && String(opt.key) === String(q.answer),
              wrong:
                checked[q.idx] && picked[q.idx] === opt.key && String(opt.key) !== String(q.answer),
            }"
            @click="((picked[q.idx] = opt.key), (checked[q.idx] = true))"
          >
            <span class="key">{{ q.type === 'boolean' ? '' : opt.key }}</span>
            <span>{{ opt.text }}</span>
          </button>
        </div>

        <p v-if="checked[q.idx]" class="verdict" :class="verdictOf(q) ? 'ok' : 'bad'">
          <template v-if="q.type === 'multiple'">
            参考答案：{{ answerText(q) }}
          </template>
          <template v-else-if="verdictOf(q)">答对了</template>
          <template v-else>答错了，正确答案是 {{ answerText(q) }}</template>
        </p>
        <p v-if="checked[q.idx] && q.explanation" class="ref">{{ q.explanation }}</p>
      </template>
    </div>

    <p v-if="scored.total" class="score">
      已答 {{ scored.total }} 题，对 {{ scored.right }} 题
    </p>
  </div>
</template>

<style scoped>
.quiz {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.q {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-0);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.stem {
  display: flex;
  gap: var(--space-2);
  align-items: flex-start;
  line-height: var(--lh-body);
  color: var(--c-text-1);
}

.badge {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  padding: 1px var(--space-2);
  margin-top: 2px;
}

.opts {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.opt {
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  text-align: left;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  color: var(--c-text-1);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  cursor: pointer;
}

.opt:hover {
  border-color: var(--c-primary-border);
}

.opt.on {
  border-color: var(--c-primary-border);
  background: var(--c-primary-soft);
}

.opt.right {
  border-color: var(--c-success-border);
  background: var(--c-success-soft);
  color: var(--c-success-ink);
}

.opt.wrong {
  border-color: var(--c-danger-border);
  background: var(--c-danger-soft);
  color: var(--c-danger-ink);
}

.key {
  flex: none;
  color: var(--c-text-3);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.short {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

button.ghost {
  align-self: flex-start;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  color: var(--c-text-2);
  font-size: var(--fs-sm);
  cursor: pointer;
}

.verdict {
  margin: 0;
  font-size: var(--fs-sm);
}

.verdict.ok {
  color: var(--c-success-ink);
}

.verdict.bad {
  color: var(--c-danger-ink);
}

.ref {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-left: 3px solid var(--c-border);
  color: var(--c-text-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
}

.hint {
  margin: 0;
  color: var(--c-text-3);
  font-size: var(--fs-sm);
}

.score {
  margin: 0;
  color: var(--c-text-2);
  font-size: var(--fs-sm);
}
</style>
