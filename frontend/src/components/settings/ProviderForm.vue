<script setup>
/**
 * 单个 provider 的配置卡（M6 T6.6）。
 *
 * 引导页（T6.9）与设置窗口共用这一个组件 —— 「两处各写一套表单」是 M6 明令禁止的事，
 * 因为两边的校验、提示、错误文案一旦分叉，用户会看到「同样的 Key 这里能存那里不能」。
 *
 * 硬约束：**Key 绝不回显**。输入框永远是空白，只显示「已配置 / 未配置」（红线 7）。
 */
import { computed, ref, watch } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { useToast } from '../../composables/useToast'

const props = defineProps({
  pid: { type: String, required: true },
  conf: { type: Object, required: true },
  defaultOpen: { type: Boolean, default: false },
})
const emit = defineEmits(['base-url', 'saved', 'models'])

const toast = useToast()
const baseUrl = ref(props.conf.base_url || '')
const apiKey = ref('')
const saving = ref(false)
const probing = ref(false)
const probe = ref(null)   // {ok, models, latency_ms, error_code, hint}
const probeUrl = ref('')  // 探测时用的地址：判断"这份列表能不能算在当前地址头上"
const open = ref(props.defaultOpen)

// 保存 Key 之后服务端会返回新配置（has_key 变 true），同步一下地址输入框
watch(() => props.conf.base_url, (value) => {
  if (!baseUrl.value) baseUrl.value = value || ''
})

const models = computed(() => props.conf.models || [])
const canProbe = computed(() => Boolean((baseUrl.value || '').trim()))
// 探测到列表，但和已保存的不一样 → 给一个明确的「记住」动作（S-1：不自动写盘）
const canRemember = computed(() => {
  const found = probe.value?.models || []
  if (!probe.value?.ok || !found.length) return false
  const saved = models.value
  return found.length !== saved.length || found.some((m) => !saved.includes(m))
})

function commitBase() {
  const value = baseUrl.value.trim()
  if (value === (props.conf.base_url || '')) return
  emit('base-url', value)
}

async function saveKey() {
  if (!apiKey.value.trim()) {
    toast.error('先填 API Key，再探测')
    return
  }
  saving.value = true
  try {
    const res = await api.saveProvider({
      provider: props.pid,
      api_key: apiKey.value.trim(),
      base_url: baseUrl.value.trim(),
    })
    apiKey.value = ''
    emit('saved', res.settings)
    // 地址没换过才把探测到的列表一起存：换了地址，那份列表就不属于它了。
    // 不额外弹提示 —— 保存 Key 的提示已经说了「已保存」。
    const found = probe.value?.models || []
    if (found.length && probeUrl.value === baseUrl.value.trim()) emit('models', found)
    toast.ok(`${props.conf.label} 的 Key 已保存，下一次调用就生效`)
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    saving.value = false
  }
}

/** 把探测到的模型列表交给父组件去存 —— 必须用户点，探测本身不写任何文件。 */
function rememberModels() {
  const found = probe.value?.models || []
  if (!found.length) return
  emit('models', found)
  toast.ok(`已记住 ${found.length} 个模型，下拉框里可以直接选`)
}

async function runProbe() {
  probing.value = true
  probe.value = null
  probeUrl.value = ''
  try {
    probe.value = await api.probeProvider({
      provider: props.pid,
      base_url: baseUrl.value.trim(),
      api_key: apiKey.value.trim(),
    })
    probeUrl.value = baseUrl.value.trim()
    if (probe.value.ok) {
      const count = probe.value.models.length
      toast.ok(`探测成功：${count ? `${count} 个模型 · ` : ''}${probe.value.latency_ms}ms`)
    }
  } catch (err) {
    probe.value = { ok: false, error_code: err.code, hint: friendlyMessage(err) }
  } finally {
    probing.value = false
  }
}
</script>

<template>
  <section class="pcard" :class="{ collapsed: !open }">
    <header class="pcard-head" @click="open = !open">
      <span class="chev">{{ open ? '▾' : '▸' }}</span>
      <h3 class="pcard-title">{{ conf.label || pid }}</h3>
      <span class="chip" :class="conf.has_key ? 'ok' : 'miss'">
        {{ conf.has_key ? 'Key 已配置' : 'Key 未配置' }}
      </span>
      <span v-if="!open" class="pcard-sub">{{ conf.base_url || '未设置接口地址' }}</span>
      <span class="spacer" />
      <span class="pcard-count">{{ models.length }} 个模型</span>
    </header>

    <div v-if="open" class="pcard-body">
      <div class="field">
        <span class="field-label">接口地址</span>
        <input
          v-model="baseUrl"
          class="input"
          placeholder="https://api.deepseek.com（DeepSeek 不带 /v1）"
          spellcheck="false"
          @blur="commitBase"
          @keyup.enter="commitBase"
        />
      </div>

      <div class="field">
        <span class="field-label">API Key</span>
        <div class="key-row">
          <input
            v-model="apiKey"
            class="input mono"
            type="password"
            autocomplete="off"
            spellcheck="false"
            :placeholder="conf.has_key ? '已配置，粘贴新 Key 可替换' : '粘贴 Key（sk-…）'"
            @keyup.enter="saveKey"
          />
          <button class="btn btn-sm btn-primary" type="button" :disabled="saving" @click="saveKey">
            {{ saving ? '保存中…' : '保存 Key' }}
          </button>
        </div>
        <p class="hint">Key 只写进本机 <code>.env</code>，不显示、不上传、不进日志。</p>
      </div>

      <div class="probe-row">
        <button
          class="btn btn-sm"
          type="button"
          :disabled="probing || !canProbe"
          :title="canProbe ? '列出对方模型并测一次延迟（只读，不改配置）' : '先填接口地址'"
          @click="runProbe"
        >
          {{ probing ? '探测中…' : '探测' }}
        </button>
        <span v-if="probe && probe.ok" class="probe-ok">
          可用 · {{ probe.latency_ms }}ms<template v-if="probe.models.length">
            · {{ probe.models.length }} 个模型</template>
        </span>
        <span v-else-if="probe" class="probe-bad">
          {{ probe.hint || probe.error_code }}
        </span>
        <span v-else-if="models.length" class="probe-idle">
          已存 {{ models.length }} 个模型
        </span>
        <button
          v-if="canRemember"
          class="btn btn-sm"
          type="button"
          title="把这次探测到的模型名字存下来，供下面的模型下拉框使用（不改接口地址与 Key）"
          @click="rememberModels"
        >
          记住这 {{ probe.models.length }} 个模型
        </button>
      </div>
      <p class="hint">探测只读：不改地址、不改 Key、不写文件。要留下列表就点「记住」。</p>
    </div>
  </section>
</template>

<style scoped>
.pcard {
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  overflow: hidden;
}

.pcard-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
}

.pcard-head:hover {
  background: var(--c-bg-2);
}

.chev {
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}

.pcard-title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.pcard-sub {
  color: var(--c-text-3);
  font-size: var(--fs-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pcard-count {
  color: var(--c-text-3);
  font-size: var(--fs-xs);
}

.spacer {
  flex: 1;
}

.chip {
  padding: 1px var(--space-2);
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
  background: var(--c-bg-2);
  color: var(--c-warning-ink);
}

.pcard-body {
  padding: 0 var(--space-4) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.field-label {
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

.key-row {
  display: flex;
  gap: var(--space-2);
}

.key-row .input {
  flex: 1;
}

.mono {
  font-family: var(--font-mono);
}

.hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.hint code {
  padding: 0 3px;
  border-radius: 3px;
  background: var(--c-bg-2);
  font-family: var(--font-mono);
}

.probe-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-xs);
}

.probe-ok {
  color: var(--c-success-ink);
}

.probe-bad {
  color: var(--c-danger-ink);
}

.probe-idle {
  color: var(--c-text-3);
}
</style>
