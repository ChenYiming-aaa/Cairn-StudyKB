<script setup>
/**
 * 问答结果：把回答里的 `[n]` 变成可点的角标，点一下就把对应的那段材料摊出来。
 *
 * 为什么不做成纯文本：`[1]` 是 Cairn 的核心承诺 —— 每句话都能回到原文那一句。
 * 演示里如果只是「[1] 挂在句尾」，用户看不出这个承诺兑现了没有。
 * 这里的 `[n]` 指第 n 段材料（不是数据库 chunk id，桌面版才是）。
 */
import { computed, ref } from 'vue'

const props = defineProps({
  answer: { type: Object, required: true },
})

const picked = ref(0)

/** 把回答切成「文字 / 角标」两类片段，避免用 v-html 渲染模型输出 */
const pieces = computed(() => {
  const text = props.answer.text || ''
  return text.split(/(\[\d+\])/).map((chunk) => {
    const hit = chunk.match(/^\[(\d+)\]$/)
    return hit ? { kind: 'cite', n: Number(hit[1]) } : { kind: 'text', text: chunk }
  })
})

const cited = computed(() => {
  const set = new Set()
  for (const piece of pieces.value) {
    if (piece.kind === 'cite') set.add(piece.n)
  }
  return [...set].sort((a, b) => a - b)
})

const activeText = computed(() => props.answer.blocks[picked.value - 1] || '')

/**
 * 模型回退（`ask.md` 规则 2 的原句）时给一段说明。
 *
 * 为什么不在界面上一笔带过：这句话在产品里是**有意为之**的防线（材料没有就说没有，
 * 不许拿常识补），但访客第一次撞见只会以为「坏了 / 没接上」。2026-11-14 实测
 * 同一段材料同一句问题，模型约 17% 的情况会这样回（6+6 次对照，与材料段带不带标题无关），
 * 所以这个分支在演示里必然会被人看到，得当场解释清楚。
 */
const FALLBACK = '知识库中没有找到相关内容'
const isFallback = computed(() => !cited.value.length && String(props.answer.text || '').includes(FALLBACK))

function pick(n) {
  picked.value = picked.value === n ? 0 : n
}
</script>

<template>
  <div class="answer">
    <div class="question">{{ answer.question }}</div>

    <p class="body">
      <template v-for="(piece, i) in pieces" :key="i">
        <button
          v-if="piece.kind === 'cite'"
          type="button"
          class="cite"
          :class="{ on: picked === piece.n }"
          @click="pick(piece.n)"
        >
          {{ piece.n }}
        </button>
        <span v-else>{{ piece.text }}</span>
      </template>
    </p>

    <div v-if="cited.length" class="cites">
      <span class="hint">这句用到的材料：</span>
      <button
        v-for="n in cited"
        :key="n"
        type="button"
        class="cite"
        :class="{ on: picked === n }"
        @click="pick(n)"
      >
        {{ n }}
      </button>
    </div>

    <blockquote v-if="activeText" class="source">
      <div class="source-head">材料第 {{ picked }} 段</div>
      {{ activeText }}
    </blockquote>

    <div v-if="isFallback" class="fallback">
      <p class="fb-head">模型说这段材料里没有能回答这个问题的内容。</p>
      <p>
        这不是没接上：问答规则要求它只依据材料回答，材料里没有就回这一句，
        宁可空手也不许拿常识补一段。桌面版问到材料外的东西时，也是这样回答的。
      </p>
      <p>换个问法，或者退回上一步点「用示例材料」再问一次。</p>
    </div>
  </div>
</template>

<style scoped>
.answer {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-0);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.question {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  border-left: 3px solid var(--c-primary-border);
  padding-left: var(--space-2);
}

.body {
  margin: 0;
  font-family: var(--font-reading);
  line-height: var(--lh-body);
  color: var(--c-text-1);
  white-space: pre-wrap;
}

.cite {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 3px;
  margin: 0 1px;
  border: 1px solid var(--c-primary-border);
  border-radius: var(--radius-sm);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-size: var(--fs-xs);
  line-height: 1;
  vertical-align: super;
  cursor: pointer;
}

.cite.on {
  background: var(--c-primary);
  color: var(--c-on-primary);
}

.cites {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.source {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-left: 3px solid var(--c-mark);
  background: var(--c-bg-1);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  color: var(--c-text-2);
  font-family: var(--font-reading);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
}

.source-head {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  margin-bottom: var(--space-1);
}

.fallback {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px dashed var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
  color: var(--c-text-2);
}

.fallback p {
  margin: 0;
}

.fb-head {
  color: var(--c-text-1);
}
</style>
