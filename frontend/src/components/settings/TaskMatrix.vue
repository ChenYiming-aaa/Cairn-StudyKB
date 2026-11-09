<script setup>
/**
 * 四类任务的模型矩阵（M6 T6.6）。
 *
 * 一行一个任务：整理 / 问答 / 出题 / 批改。改完即时保存（父组件做 300ms 防抖），
 * **下一次调用就生效**，不需要重启 —— 这里不做「应用」按钮，因为用户不会记得点。
 *
 * 「思考强度」在该 provider 不支持时置灰，并说明原因（很多第三方网关会 400，见 ADR-026）。
 */
import { computed } from 'vue'

const props = defineProps({
  tasks: { type: Object, required: true },
  providers: { type: Object, required: true },
})
const emit = defineEmits(['change'])

const AGENTS = [
  { id: 'organizer', name: '整理', desc: '重写标题、摘要、要点、笔记' },
  { id: 'asker', name: '问答', desc: '对整库提问，带引用' },
  { id: 'quizzer', name: '出题', desc: '按条目生成题目' },
  { id: 'grader', name: '批改', desc: '简答判分与解析' },
]

const EFFORTS = [
  { id: 'none', name: '关' },
  { id: 'low', name: '低' },
  { id: 'medium', name: '中' },
  { id: 'high', name: '高' },
]

const providerIds = computed(() => Object.keys(props.providers || {}))

function task(agent) {
  return props.tasks?.[agent] || { provider: 'deepseek', model: '', effort: 'low' }
}

function conf(agent) {
  return props.providers?.[task(agent).provider] || {}
}

function modelsOf(agent) {
  return conf(agent).models || []
}

function supportsEffort(agent) {
  return Boolean(conf(agent).supports_effort)
}

function emitChange(agent, key, value) {
  emit('change', { [agent]: { [key]: value } })
}

/** 换 provider：模型跟着换（新 provider 的默认模型），否则会拿着 A 的名字问 B */
function changeProvider(agent, pid) {
  const models = props.providers?.[pid]?.models || []
  emitChange(agent, 'provider', pid)
  emitChange(agent, 'model', models[0] || '')
  if (!props.providers?.[pid]?.supports_effort) emitChange(agent, 'effort', 'none')
}
</script>

<template>
  <div class="matrix">
    <div class="mhead">
      <span class="c-task">任务</span>
      <span class="c-prov">服务</span>
      <span class="c-model">模型</span>
      <span class="c-eff">思考强度</span>
    </div>

    <div v-for="agent in AGENTS" :key="agent.id" class="mrow">
      <div class="c-task">
        <b>{{ agent.name }}</b>
        <small>{{ agent.desc }}</small>
      </div>

      <select
        class="input"
        :value="task(agent.id).provider"
        @change="changeProvider(agent.id, $event.target.value)"
      >
        <option v-for="pid in providerIds" :key="pid" :value="pid">
          {{ providers[pid].label || pid }}
        </option>
      </select>

      <select
        v-if="modelsOf(agent.id).length"
        class="input"
        :value="task(agent.id).model"
        @change="emitChange(agent.id, 'model', $event.target.value)"
      >
        <option value="">默认（{{ modelsOf(agent.id)[0] }}）</option>
        <option v-for="m in modelsOf(agent.id)" :key="m" :value="m">{{ m }}</option>
      </select>
      <input
        v-else
        class="input mono"
        :value="task(agent.id).model"
        placeholder="手动填模型名"
        spellcheck="false"
        @change="emitChange(agent.id, 'model', $event.target.value.trim())"
      />

      <div class="seg" :class="{ off: !supportsEffort(agent.id) }">
        <button
          v-for="e in EFFORTS"
          :key="e.id"
          class="seg-btn"
          :class="{ on: task(agent.id).effort === e.id }"
          type="button"
          :disabled="!supportsEffort(agent.id)"
          :title="supportsEffort(agent.id) ? '' : '该服务不支持思考强度参数（发了会 400）'"
          @click="emitChange(agent.id, 'effort', e.id)"
        >
          {{ e.name }}
        </button>
      </div>
    </div>

    <p class="foot">
      换服务或换模型后下一次调用就生效；「思考强度」只对声明支持的服务发送。
    </p>
  </div>
</template>

<style scoped>
.matrix {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  padding: var(--space-2) var(--space-3) var(--space-3);
}

.mhead,
.mrow {
  display: grid;
  grid-template-columns: 132px 150px 1fr 150px;
  gap: var(--space-2);
  align-items: center;
}

.mhead {
  padding: var(--space-1) var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  border-bottom: 1px solid var(--c-border);
}

.mrow {
  padding: var(--space-2) var(--space-1);
  border-bottom: 1px dashed var(--c-border);
}

.mrow:last-of-type {
  border-bottom: none;
}

.c-task {
  display: flex;
  flex-direction: column;
  font-size: var(--fs-sm);
}

.c-task small {
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}

.mono {
  font-family: var(--font-mono);
}

.seg {
  display: inline-flex;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.seg.off {
  opacity: 0.45;
}

.seg-btn {
  flex: 1;
  padding: 3px 0;
  border: none;
  background: var(--c-bg-1);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.seg-btn + .seg-btn {
  border-left: 1px solid var(--c-border);
}

.seg-btn.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-weight: 600;
}

.seg-btn:disabled {
  cursor: not-allowed;
}

.foot {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
