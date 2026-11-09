/**
 * 设置窗口的唯一数据源（M6 T6.5 / T6.6）。
 *
 * 三条约定：
 * 1. **即时保存**：改完 300ms 防抖 PATCH，不设「保存」按钮（M6 §4 T6.6）
 * 2. **乐观更新**：本地先改再发请求，输入框不跟着网络抖；服务端返回后整体替换
 * 3. **失败不静默**：`error` 交给 tab 显示，绝不假装已保存
 *
 * 状态是模块级单例：顶栏齿轮、引导页、设置窗口必须看到同一份配置。
 */
import { ref } from 'vue'

import { api, friendlyMessage } from '../api/client'

const settings = ref(null)
const loading = ref(false)
const error = ref('')
// 最近一次保存成功的时间戳（ms）；tab 用它闪一下「已保存」
const savedAt = ref(0)
const saving = ref(false)

const SAVE_DELAY = 300
let pending = {}
let timer = null
let chain = Promise.resolve()

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

/** 深合并：只对普通对象递归，数组整体替换（模型列表不能并成两套并存）。 */
function deepMerge(base, patch) {
  const out = { ...(isPlainObject(base) ? base : {}) }
  for (const [key, value] of Object.entries(patch || {})) {
    out[key] = isPlainObject(value) && isPlainObject(out[key])
      ? deepMerge(out[key], value)
      : value
  }
  return out
}

async function load(force = false) {
  if (settings.value && !force) return settings.value
  loading.value = true
  error.value = ''
  try {
    settings.value = await api.settings()
  } catch (err) {
    error.value = friendlyMessage(err)
  } finally {
    loading.value = false
  }
  return settings.value
}

function applyLocally(patch) {
  if (!settings.value) return
  const next = deepMerge(settings.value, patch)
  // 本地改 provider 的地址/模型时，has_key 等派生字段保持原值（服务端会纠正）
  settings.value = next
}

async function flush() {
  timer = null
  if (!Object.keys(pending).length) return
  const patch = pending
  pending = {}
  saving.value = true
  error.value = ''
  try {
    const res = await api.patchSettings(patch)
    // 用服务端结果覆盖，但保留这段时间里新攒下的 pending 不被冲掉
    if (Object.keys(pending).length) {
      settings.value = deepMerge(res, pending)
    } else {
      settings.value = res
    }
    savedAt.value = Date.now()
  } catch (err) {
    error.value = friendlyMessage(err)
    // 失败后把这份 patch 再排一次队，用户不会看到「改了但没存」却毫无提示
    pending = deepMerge(patch, pending)
  } finally {
    saving.value = false
  }
}

/** 排一次保存（防抖）；本地立即生效。 */
function update(patch) {
  applyLocally(patch)
  pending = deepMerge(pending, patch)
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    chain = chain.then(flush).catch(() => {})
  }, SAVE_DELAY)
}

/** 立刻把待发的改动刷出去（关闭窗口、切 tab 时调）。 */
function flushNow() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  chain = chain.then(flush).catch(() => {})
  return chain
}

/** 用完整结果替换（保存 Key / 探测之后服务端返回了新的全量）。 */
function replace(next) {
  if (next) settings.value = next
}

export function useSettings() {
  return {
    settings,
    loading,
    saving,
    savedAt,
    error,
    load,
    update,
    flushNow,
    replace,
  }
}
