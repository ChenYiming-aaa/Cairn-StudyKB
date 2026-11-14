<script setup>
/**
 * 试用页（只在演示站出现）：用自己的 Key 真跑一遍整理 / 追问 / 出题。
 *
 * 这个页面的存在理由：光看演示数据，没法判断「这东西整理出来到底有没有用」。
 * 把 Key 填进来、材料粘进来、点一下，看到的就是桌面版会给出的东西 ——
 * 因为提示词是构建时从后端原样注入的，请求体也和后端一致。
 *
 * 三条要守的：
 * 1. Key 只存在这台浏览器（localStorage），只发给用户填的那个端点。
 * 2. 三步都能看到「花了多少 token」，让人心里有数 —— 每次点都是真花钱。
 * 3. 报错要说清断在哪一步（跨域 / Key 不对 / 额度 / 超时），不许糊成一句「失败」。
 */
import { computed, ref } from 'vue'

import { PROVIDERS } from '../demo/llm'
import { useTry } from '../demo/useTry'
import TryAnswer from '../demo/TryAnswer.vue'
import TryNote from '../demo/TryNote.vue'
import TryQuiz from '../demo/TryQuiz.vue'

const {
  conn, material, question, ready, busy, steps, note, answer, quiz, paras, usage,
  pickProvider, forget, useSample, testConn, organize, ask, makeQuiz,
} = useTry()

const showKey = ref(false)
const openConn = ref(!ready.value)

const provider = computed(() => PROVIDERS.find((p) => p.id === conn.provider) || PROVIDERS[0])

function toggleKey() {
  showKey.value = !showKey.value
}

async function connect() {
  const ok = await testConn()
  if (ok) openConn.value = false
}
</script>

<template>
  <div class="try">
    <header class="head">
      <h1>用自己的 Key 试一遍</h1>
      <p class="lead">
        这是一个静态网页，没有后端。下面三步都直接把请求发到你填的那家服务商
        ——<b>不经过本项目的任何服务器</b>，Key 只存在这台浏览器里。
        提示词与桌面版完全一致，所以看到的结果就是桌面版会给你的结果。
      </p>
      <p class="cost">
        每次点「整理 / 追问 / 出题」都是一次真实调用，会计入你自己的账户（一篇材料整理约几百 token，
        单次几分钱）。页脚会累计显示这次用掉多少。
      </p>
    </header>

    <!-- ① 连接 -->
    <section class="card">
      <button class="card-head" type="button" @click="openConn = !openConn">
        <span class="step">1</span>
        <span class="card-title">连上模型</span>
        <span v-if="ready" class="pill ok">{{ provider.label }} · {{ conn.model }}</span>
        <span v-else class="pill">还没填</span>
        <span class="chev" :class="{ open: openConn }">▾</span>
      </button>

      <div v-if="openConn" class="card-body">
        <div class="providers">
          <button
            v-for="p in PROVIDERS"
            :key="p.id"
            type="button"
            class="provider"
            :class="{ on: p.id === conn.provider }"
            @click="pickProvider(p.id)"
          >
            {{ p.label }}
          </button>
        </div>
        <p class="hint">{{ provider.note }}</p>

        <div class="fields">
          <label>
            <span>接口地址</span>
            <input v-model="conn.base" type="text" spellcheck="false" placeholder="https://api.deepseek.com" />
          </label>
          <label>
            <span>
              Key
              <a v-if="provider.keyUrl" :href="provider.keyUrl" target="_blank" rel="noreferrer">去这里建一个</a>
            </span>
            <span class="key-row">
              <input
                v-model="conn.key"
                :type="showKey ? 'text' : 'password'"
                spellcheck="false"
                autocomplete="off"
                placeholder="sk-…"
              />
              <button type="button" class="ghost" @click="toggleKey">{{ showKey ? '藏起来' : '看一眼' }}</button>
            </span>
          </label>
          <label>
            <span>模型</span>
            <input v-model="conn.model" type="text" spellcheck="false" list="try-models" placeholder="deepseek-chat" />
            <datalist id="try-models">
              <option v-for="m in provider.models" :key="m" :value="m" />
            </datalist>
          </label>
        </div>

        <div class="row">
          <button type="button" class="primary" :disabled="!ready || steps.conn.state === 'running'" @click="connect">
            {{ steps.conn.state === 'running' ? '正在连…' : '试试能不能连上' }}
          </button>
          <button v-if="conn.key" type="button" class="ghost" @click="forget()">忘掉 Key</button>
        </div>

        <p v-if="steps.conn.state === 'done'" class="msg ok">{{ steps.conn.msg }}</p>
        <p v-if="steps.conn.state === 'error'" class="msg bad">
          {{ steps.conn.msg }}
          <span v-if="steps.conn.detail" class="detail">{{ steps.conn.detail }}</span>
        </p>

        <p class="fine">
          Key 存在这台浏览器的 localStorage 里，换设备就要重填。点「忘掉 Key」立刻清除。
          这个页面不发任何统计、不写任何远端存储。
        </p>
      </div>
    </section>

    <!-- ② 材料 -->
    <section class="card">
      <div class="card-head static">
        <span class="step">2</span>
        <span class="card-title">放一段材料</span>
        <span class="pill">{{ material.length }} 字 · {{ paras.length }} 段</span>
      </div>
      <div class="card-body">
        <textarea
          v-model="material"
          rows="8"
          spellcheck="false"
          placeholder="把一篇文章、一节课的笔记、一段讲义粘进来。也可以点下面的「用示例材料」。"
        />
        <div class="row">
          <button type="button" class="ghost" @click="useSample()">用示例材料</button>
          <span class="hint inline">示例是一段二级 Python 讲义节选，约 600 字</span>
        </div>
      </div>
    </section>

    <!-- ③ 三步 -->
    <section class="card">
      <div class="card-head static">
        <span class="step">3</span>
        <span class="card-title">跑三步</span>
        <span class="pill">{{ usage.calls }} 次调用 · 输入 {{ usage.in }} / 输出 {{ usage.out }} token</span>
      </div>

      <div class="card-body">
        <!-- 整理 -->
        <div class="step-block">
          <div class="step-row">
            <button
              type="button"
              class="primary"
              :disabled="!ready || !material.trim() || busy"
              @click="organize()"
            >
              {{ steps.note.state === 'running' ? '正在整理…' : '整理成笔记' }}
            </button>
            <span class="hint inline">桌面版的「整理」就是这一步：标题、分类、标签、摘要、要点、笔记</span>
          </div>
          <p v-if="steps.note.state === 'error'" class="msg bad">
            {{ steps.note.msg }} <span v-if="steps.note.detail" class="detail">{{ steps.note.detail }}</span>
          </p>
          <TryNote v-if="note" :note="note" />
        </div>

        <!-- 追问 -->
        <div class="step-block">
          <div class="step-row">
            <input
              v-model="question"
              class="q"
              type="text"
              placeholder="就这份材料问一句，例如：切片左闭右开是什么意思？"
              @keyup.enter="ready && !busy && ask()"
            />
            <button
              type="button"
              class="primary"
              :disabled="!ready || !question.trim() || !paras.length || busy"
              @click="ask()"
            >
              {{ steps.answer.state === 'running' ? '正在问…' : '问一句' }}
            </button>
          </div>
          <span class="hint inline">
            这里把材料切段后<b>全部</b>给模型（桌面版按意思只取最相关的几块），所以
            <code>[1]</code> 指的是「第几段」
          </span>
          <p v-if="steps.answer.state === 'error'" class="msg bad">
            {{ steps.answer.msg }} <span v-if="steps.answer.detail" class="detail">{{ steps.answer.detail }}</span>
          </p>
          <TryAnswer v-if="answer" :answer="answer" />
        </div>

        <!-- 出题 -->
        <div class="step-block">
          <div class="step-row">
            <button
              type="button"
              class="primary"
              :disabled="!ready || !material.trim() || busy"
              @click="makeQuiz()"
            >
              {{ steps.quiz.state === 'running' ? '正在出题…' : '出 3 道题并自测' }}
            </button>
            <span class="hint inline">出完可以直接选答案，对照讲解看自己理解得对不对</span>
          </div>
          <p v-if="steps.quiz.state === 'error'" class="msg bad">
            {{ steps.quiz.msg }} <span v-if="steps.quiz.detail" class="detail">{{ steps.quiz.detail }}</span>
          </p>
          <TryQuiz v-if="quiz.length" :questions="quiz" />
        </div>

        <p v-if="!ready" class="msg">
          先把第 1 步的 Key 填上，三步的按钮才会亮。
        </p>
      </div>
    </section>

    <footer class="foot">
      <p>
        想把这些材料真正存进自己的库、复习、看原件 ——
        <a href="https://github.com/ChenYiming-aaa/Cairn-StudyKB/releases" target="_blank" rel="noreferrer">
          装桌面版
        </a>
        。它会把这些整理结果、原件、复习记录都留在本机。
      </p>
    </footer>
  </div>
</template>

<style scoped>
.try {
  max-width: 900px;
  margin: 0 auto;
  padding: var(--space-6) var(--space-4) var(--space-8);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.head h1 {
  font-size: var(--fs-xl);
  line-height: var(--lh-title);
  margin: 0 0 var(--space-2);
}

.lead {
  color: var(--c-text-2);
  line-height: var(--lh-body);
  margin: 0 0 var(--space-2);
}

.cost,
.fine,
.hint {
  color: var(--c-text-3);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
}

.cost {
  margin: 0;
}

.hint.inline {
  margin: 0;
}

.card {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  overflow: hidden;
}

.card-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: none;
  border: 0;
  text-align: left;
  cursor: pointer;
  font-size: var(--fs-md);
}

.card-head.static {
  cursor: default;
  border-bottom: 1px solid var(--c-border);
}

.step {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-size: var(--fs-xs);
  flex: none;
}

.card-title {
  font-weight: 600;
  flex: none;
}

.pill {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  border: 1px solid var(--c-border);
  border-radius: 999px;
  padding: 1px var(--space-2);
  white-space: nowrap;
}

.pill.ok {
  color: var(--c-success-ink);
  border-color: var(--c-success-border);
  background: var(--c-success-soft);
}

.chev {
  color: var(--c-text-3);
  transition: transform 0.15s;
}

.chev.open {
  transform: rotate(180deg);
}

.card-body {
  padding: var(--space-3) var(--space-4) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.providers {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.provider {
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  color: var(--c-text-2);
  font-size: var(--fs-sm);
  cursor: pointer;
}

.provider.on {
  border-color: var(--c-primary-border);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.fields {
  display: grid;
  gap: var(--space-3);
}

.fields label {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.fields a {
  color: var(--c-primary);
  margin-left: var(--space-2);
}

.key-row {
  display: flex;
  gap: var(--space-2);
}

input,
textarea {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  color: var(--c-text-1);
  font-size: var(--fs-md);
  font-family: var(--font-ui);
}

textarea {
  resize: vertical;
  line-height: var(--lh-body);
  font-family: var(--font-reading);
}

input:focus,
textarea:focus {
  outline: 2px solid var(--c-primary-border);
  outline-offset: -1px;
}

.row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

button.primary {
  padding: var(--space-2) var(--space-4);
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--c-primary);
  color: var(--c-on-primary);
  font-size: var(--fs-sm);
  cursor: pointer;
  flex: none;
}

button.primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

button.ghost {
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  color: var(--c-text-2);
  font-size: var(--fs-sm);
  cursor: pointer;
  flex: none;
}

.msg {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.msg.ok {
  color: var(--c-success-ink);
}

.msg.bad {
  color: var(--c-danger-ink);
  background: var(--c-danger-soft);
  border: 1px solid var(--c-danger-border);
  border-radius: var(--radius-sm);
  padding: var(--space-2) var(--space-3);
}

.detail {
  display: block;
  margin-top: var(--space-1);
  color: var(--c-text-3);
  font-size: var(--fs-xs);
  word-break: break-word;
}

.step-block {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--c-border);
}

.step-block:first-child {
  border-top: 0;
  padding-top: 0;
}

.step-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}

input.q {
  flex: 1 1 240px;
  width: auto;
}

.foot {
  color: var(--c-text-3);
  font-size: var(--fs-sm);
  line-height: var(--lh-body);
}

.foot a {
  color: var(--c-primary);
}
</style>
