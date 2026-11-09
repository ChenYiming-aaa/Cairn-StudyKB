<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useToast } from '../composables/useToast'
import { useSettings } from '../composables/useSettings'
import { useUi } from '../composables/useUi'
import ProviderForm from '../components/settings/ProviderForm.vue'

/**
 * 首次引导（T5.7）。
 *
 * 只解决"装完打不开/打开了什么都不能干"这一个问题，所以清单固定三步且**不解释原理**：
 *   1. 模型 Key —— 唯一必须由用户提供的输入（后台已经写进 %APPDATA%/Cairn/.env）
 *   2. ffmpeg  —— 安装包自带，正常就该是绿的；红了说明安装不完整
 *   3. 本地模型 —— 可选，首次用时自动下载，只是提前告诉用户"会下 600MB"
 *
 * T6.9 改造：Key 表单换成设置窗口里那个 `ProviderForm`（两处共用一个组件，
 * 校验/提示/错误文案只有一份），「接口地址 / 模型名」的折叠直接删掉 ——
 * 那些属于设置窗口的「模型」tab，引导页只负责"把 Key 填进去、能立刻用"。
 */
const router = useRouter()
const toast = useToast()
const { envState, envLoaded, loadEnv, dismissSetup, openSettings } = useUi()
const { settings, load: loadSettings, update, replace } = useSettings()

const checking = ref(false)
// 引导页只暴露默认 provider 的 Key/地址；换服务商、按任务分模型都在设置里
const deepseek = computed(() => settings.value?.llm?.providers?.deepseek || null)

const env = computed(() => envState.value || {})
const envPath = computed(() => env.value.env_file || '')
const llmOk = computed(() => Boolean(env.value.llm?.ok))
const blocking = computed(() => {
  const list = []
  if (!llmOk.value) list.push('模型 Key')
  if (env.value.ffmpeg && !env.value.ffmpeg.ok) list.push('ffmpeg')
  return list
})

/** 三项的展示状态：ok / miss；whisper 这类"可自动补齐"的缺了不算问题 */
function tone(item) {
  if (!item) return 'pending'
  return item.ok ? 'ok' : 'miss'
}

async function refresh() {
  checking.value = true
  try {
    await Promise.all([loadEnv(), loadSettings(true)])
  } finally {
    checking.value = false
  }
}

/** 保存 Key 之后：配置换成服务端的新全量，再重新自检一次（顶栏黄点要跟着灭） */
async function onSaved(next) {
  if (next) replace(next)
  await loadEnv()
}

/** 改接口地址：与设置页同一条路（即时保存），避免两处行为不一致 */
function onBaseUrl(value) {
  update({ llm: { providers: { deepseek: { base_url: value } } } })
}

/** 引导页也要能「记住模型列表」：与设置页同一个动作，只是 provider 固定是 deepseek */
function onModels(list) {
  update({ llm: { providers: { deepseek: { models: list } } } })
}

function later() {
  dismissSetup()
  toast.info('随时点顶栏的齿轮回到这里')
  router.push('/')
}

onMounted(async () => {
  if (!envLoaded.value) await loadEnv()
  await loadSettings()
})
</script>

<template>
  <div class="setup">
    <header class="hero">
      <img class="hero-mark" src="/logo.svg" alt="" width="56" height="56" />
      <div>
        <h1>把 Cairn 准备好</h1>
        <p class="hero-sub">
          三件事，缺哪件补哪件。全部就绪后就不用再来了。
          <span v-if="blocking.length" class="hero-flag">现在卡在：{{ blocking.join('、') }}</span>
          <span v-else class="hero-done">已全部就绪 ✓</span>
        </p>
      </div>
    </header>

    <p v-if="!envLoaded" class="state">正在检查本机环境…</p>

    <ol v-else class="steps">
      <!-- 1. 模型 Key -->
      <li class="step" :class="tone(env.llm)">
        <div class="step-head">
          <span class="step-no">1</span>
          <h2 class="step-title">模型 Key</h2>
          <span class="chip" :class="tone(env.llm)">
            {{ env.llm?.ok ? '已配置' : '必需' }}
          </span>
        </div>
        <p class="step-desc">
          问答、整理、出题全靠它。填一次就够，卸载重装也不会丢。
        </p>

        <!-- 与设置窗口共用同一个表单（M6 §4 T6.9 明令禁止两处各写一套） -->
        <ProviderForm
          v-if="deepseek"
          pid="deepseek"
          :conf="deepseek"
          default-open
          @base-url="onBaseUrl"
          @models="onModels"
          @saved="onSaved"
        />
        <p v-else class="step-foot">配置还没读出来，稍等一秒或点下面的「重新检查」。</p>

        <p class="step-foot">
          想换服务商、或者给整理/问答/出题/批改分别挑模型？点这里
          <button class="link-btn" type="button" @click="openSettings('model')">打开设置</button>
        </p>

        <p v-if="env.llm?.ok" class="step-foot ok-line">
          当前模型：{{ env.llm.detail }}。已经生效，不用重启。
        </p>
        <p v-else-if="env.llm?.hint" class="step-foot">{{ env.llm.hint }}</p>
        <p v-if="envPath" class="step-foot">
          保存位置 <code>{{ envPath }}</code>
        </p>
      </li>

      <!-- 2. ffmpeg -->
      <li class="step" :class="tone(env.ffmpeg)">
        <div class="step-head">
          <span class="step-no">2</span>
          <h2 class="step-title">视频转录引擎（ffmpeg）</h2>
          <span class="chip" :class="tone(env.ffmpeg)">
            {{ env.ffmpeg?.ok ? '已就绪' : '缺失' }}
          </span>
        </div>
        <p class="step-desc">
          只有「视频链接转录」用它，网页采集和问答都不用。安装包自带，正常情况下这一项本来就是绿的。
        </p>
        <p v-if="env.ffmpeg" class="step-foot">
          {{ env.ffmpeg.ok ? `版本 ${env.ffmpeg.detail}` : env.ffmpeg.hint || env.ffmpeg.detail }}
        </p>
      </li>

      <!-- 3. 本地模型 -->
      <li class="step" :class="env.whisper?.ok && env.embedding?.ok ? 'ok' : 'optional'">
        <div class="step-head">
          <span class="step-no">3</span>
          <h2 class="step-title">本地模型</h2>
          <span class="chip optional">
            {{ env.whisper?.ok && env.embedding?.ok ? '已下载' : '用到才下' }}
          </span>
        </div>
        <p class="step-desc">
          不用管，第一次真正用到时会自动下载。提前说一声，免得以为卡住了。
        </p>
        <div class="rows">
          <div class="row" :class="tone(env.whisper)">
            <span class="row-name">语音识别</span>
            <span class="row-name-sub">whisper small · 约 500MB</span>
            <span class="row-value">{{ env.whisper?.ok ? '已下载' : '未下载' }}</span>
          </div>
          <div class="row" :class="tone(env.embedding)">
            <span class="row-name">向量检索</span>
            <span class="row-name-sub">bge-small-zh · 约 100MB</span>
            <span class="row-value">{{ env.embedding?.ok ? '已下载' : '未下载' }}</span>
          </div>
          <div class="row" :class="tone(env.sqlite_vec)">
            <span class="row-name">向量加速</span>
            <span class="row-name-sub">sqlite-vec · 可选</span>
            <span class="row-value">{{ env.sqlite_vec?.ok ? '已就绪' : '未安装' }}</span>
          </div>
        </div>
      </li>
    </ol>

    <!-- 配置来源（S-3）：正常情况下这里什么都不显示；出现说明配置被两处拼起来了 -->
    <p v-if="env.config && !env.config.ok" class="src-warn">
      配置并不完全来自本数据目录：<code>{{ env.config.legacy_keys.join('、') }}</code>
      是从 <code>{{ env.config.legacy_file }}</code> 补进来的。
    </p>

    <footer class="setup-foot">
      <button class="btn" type="button" :disabled="checking" @click="refresh">
        {{ checking ? '检查中…' : '重新检查' }}
      </button>
      <div class="grow" />
      <button class="btn btn-ghost" type="button" @click="later">稍后再说</button>
      <button class="btn btn-primary" type="button" @click="router.push('/')">去知识库</button>
    </footer>
  </div>
</template>

<style scoped>
.setup {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-6) var(--space-6) var(--space-8);
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
}

.hero {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.hero-mark {
  flex: none;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
}

.hero h1 {
  margin: 0 0 var(--space-1);
  font-size: var(--fs-xl);
  font-weight: 600;
}

.hero-sub {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: var(--lh-body);
}

.hero-flag {
  color: var(--c-warning);
}

.hero-done {
  color: var(--c-success);
}

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.step {
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  border-left: 3px solid var(--c-border);
}

.step.ok {
  border-left-color: var(--c-success);
}

.step.miss {
  border-left-color: var(--c-warning);
}

.step.optional {
  border-left-color: var(--c-text-3);
}

.step-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.step-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--c-bg-2);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.step-title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.chip {
  margin-left: auto;
  padding: 2px var(--space-2);
  border-radius: 999px;
  font-size: var(--fs-xs);
  background: var(--c-bg-2);
  color: var(--c-text-2);
}

.chip.ok {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.chip.miss {
  background: var(--c-warning-soft);
  color: var(--c-warning);
}

.chip.optional {
  background: var(--c-bg-2);
  color: var(--c-text-3);
}

.step :deep(.pcard) {
  margin-top: var(--space-3);
}

.step-desc {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  line-height: var(--lh-body);
}

.step-desc code {
  padding: 1px 4px;
  border-radius: 4px;
  background: var(--c-bg-2);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  word-break: break-all;
}

.link-btn {
  padding: 0;
  border: none;
  background: none;
  color: var(--c-primary-ink);
  font-size: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.link-btn:hover {
  color: var(--c-primary-hover);
}

.step-foot {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: var(--lh-body);
}

.ok-line {
  color: var(--c-success);
}

.rows {
  margin-top: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  font-size: var(--fs-xs);
}

.row-name {
  color: var(--c-text-1);
}

.row-name-sub {
  color: var(--c-text-3);
}

.row-value {
  margin-left: auto;
  color: var(--c-text-2);
}

.row.ok .row-value {
  color: var(--c-success);
}

.row.miss .row-value {
  color: var(--c-text-3);
}

.setup-foot {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-6);
}

.src-warn {
  margin: var(--space-4) 0 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-warning-border);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
}

.src-warn code {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--c-bg-1);
  font-family: var(--font-mono);
  word-break: break-all;
}

.grow {
  flex: 1;
}
</style>
