<script setup>
/**
 * 设置窗口的「模型」tab（M6 T6.6）。
 *
 * 结构：顶部「当前生效」摘要 → 两张 provider 卡 → 四任务矩阵。
 * 保存策略是**即时保存**（改完 300ms 防抖 PATCH），没有「保存」按钮 ——
 * 数据在 `useSettings` 里，切 tab / 关窗口前会 flush。
 */
import { computed, onMounted } from 'vue'

import { useSettings } from '../../composables/useSettings'
import ProviderForm from './ProviderForm.vue'
import TaskMatrix from './TaskMatrix.vue'

const { settings, loading, error, update, replace, load } = useSettings()

const providers = computed(() => settings.value?.llm?.providers || {})
const tasks = computed(() => settings.value?.llm?.tasks || {})
const providerIds = computed(() => Object.keys(providers.value))

const AGENT_NAMES = { organizer: '整理', asker: '问答', quizzer: '出题', grader: '批改' }
const EFFORT_NAMES = { none: '关', low: '低', medium: '中', high: '高' }

/** 「现在到底用什么」——用户改完最想确认的就是这一行 */
const summary = computed(() =>
  Object.entries(tasks.value).map(([agent, task]) => ({
    agent: AGENT_NAMES[agent] || agent,
    label: providers.value[task.provider]?.label || task.provider,
    model: task.model || '默认',
    effort: providers.value[task.provider]?.supports_effort
      ? EFFORT_NAMES[task.effort] || task.effort
      : '不支持',
  }))
)

function onBaseUrl(pid, value) {
  update({ llm: { providers: { [pid]: { base_url: value } } } })
}

/** 用户在 provider 卡上点了「记住」才走这里：探测本身不写盘（S-1）。 */
function onModels(pid, list) {
  update({ llm: { providers: { [pid]: { models: list } } } })
}

function onSaved(next) {
  // 保存 Key 后服务端回了新全量；探测后只更新了模型列表，重新拉一次即可
  if (next) replace(next)
  else load(true)
}

function onTaskChange(patch) {
  update({ llm: { tasks: patch } })
}

onMounted(() => load())
</script>

<template>
  <div class="tab">
    <p v-if="loading && !settings" class="state">正在读取配置…</p>
    <p v-else-if="error" class="state bad">{{ error }}</p>

    <template v-else-if="settings">
      <div class="now">
        <span class="now-title">当前生效</span>
        <span v-for="item in summary" :key="item.agent" class="now-chip">
          {{ item.agent }} · {{ item.label }} · {{ item.model }} · 思考{{ item.effort }}
        </span>
      </div>

      <div class="cards">
        <ProviderForm
          v-for="(pid, index) in providerIds"
          :key="pid"
          :pid="pid"
          :conf="providers[pid]"
          :default-open="index === 0"
          @base-url="(value) => onBaseUrl(pid, value)"
          @models="(list) => onModels(pid, list)"
          @saved="onSaved"
        />
        <p class="tip">
          两套服务够用且界面简单：默认的 DeepSeek 与任意一个「OpenAI 兼容」服务。
          想换服务商不用改文件，在这里填地址和 Key 就行。
        </p>
      </div>

      <h4 class="section">每类任务用哪个模型</h4>
      <TaskMatrix :tasks="tasks" :providers="providers" @change="onTaskChange" />
    </template>
  </div>
</template>

<style scoped>
.tab {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.state {
  margin: var(--space-6) 0;
  color: var(--c-text-3);
  font-size: var(--fs-sm);
}

.state.bad {
  color: var(--c-danger-ink);
}

.now {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--c-primary-soft);
  font-size: var(--fs-xs);
}

.now-title {
  font-weight: 600;
  color: var(--c-primary-ink);
  margin-right: var(--space-1);
}

.now-chip {
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--c-bg-1);
  color: var(--c-text-2);
}

.cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.tip {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: var(--lh-body);
}

.section {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-sm);
  font-weight: 600;
}
</style>
