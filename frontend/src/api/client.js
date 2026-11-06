/**
 * 唯一允许发起网络请求的模块（接口契约 §4：组件里不许手写 URL）。
 * - baseUrl：window.api.baseUrl（Electron 注入） > VITE_API_BASE > 空（走 Vite 代理）
 * - 统一错误形状：{ error: { code, message, detail } }
 * - 错误按前缀映射成人话，组件只负责展示
 */

export class ApiError extends Error {
  constructor({ code, message, detail, status }) {
    super(message || code || '请求失败')
    this.name = 'ApiError'
    this.code = code || 'UNKNOWN'
    this.detail = detail || ''
    this.status = status || 0
  }
}

const FRIENDLY = [
  [/^LLM_NO_KEY$/, '未配置模型 Key：请在后端 .env 里填写 LLM_API_KEY 后重启服务'],
  [/^LLM_BAD_JSON$/, '模型返回的内容不是合法 JSON，已自动重试过一次'],
  [/^LLM_/, '模型调用失败，请稍后重试（详细原因见任务记录）'],
  [/^FETCH_/, '采集失败：目标站点拒绝访问或没有有效正文'],
  [/^ITEM_NOT_FOUND$/, '条目不存在，可能已被删除'],
  [/^ITEM_BUSY$/, '该条目正在整理中，请等它结束'],
  [/^NETWORK$/, '连不上后端服务，请确认 uvicorn 已在 8756 端口启动'],
  [/^POLL_TIMEOUT$/, '任务超时未返回，请稍后在任务记录里查看'],
]

export function friendlyMessage(err) {
  if (!err) return '未知错误'
  for (const [pattern, text] of FRIENDLY) {
    if (pattern.test(err.code || '')) return text
  }
  return err.message || (err.code ? `请求失败（${err.code}）` : '请求失败')
}

function baseUrl() {
  const injected = typeof window !== 'undefined' && window.api && window.api.baseUrl
  return (injected || import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '')
}

function buildQuery(params) {
  const pairs = Object.entries(params || {}).filter(
    ([, v]) => v !== undefined && v !== null && v !== ''
  )
  if (!pairs.length) return ''
  const usp = new URLSearchParams()
  for (const [k, v] of pairs) usp.append(k, String(v))
  return `?${usp.toString()}`
}

async function request(method, path, { body, params, signal } = {}) {
  const url = `${baseUrl()}${path}${buildQuery(params)}`
  let res
  try {
    res = await fetch(url, {
      method,
      signal,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (exc) {
    if (exc?.name === 'AbortError') throw exc
    throw new ApiError({ code: 'NETWORK', message: '无法连接后端服务' })
  }

  const raw = await res.text()
  let data = null
  if (raw) {
    try {
      data = JSON.parse(raw)
    } catch {
      data = null
    }
  }
  if (!res.ok) {
    const payload = data?.error || {}
    throw new ApiError({
      code: payload.code || `HTTP_${res.status}`,
      message: payload.message || `HTTP ${res.status}`,
      detail: payload.detail || (raw ? raw.slice(0, 300) : ''),
      status: res.status,
    })
  }
  return data
}

export const get = (path, params) => request('GET', path, { params })
export const post = (path, body) => request('POST', path, { body })
export const patch = (path, body) => request('PATCH', path, { body })
export const del = (path) => request('DELETE', path)

/** 语义化端点：路径只在这里出现一次。 */
export const api = {
  health: () => get('/api/health'),
  listItems: (params) => get('/api/knowledge', params),
  /** 分类/标签两级计数 + 状态计数（左侧树与「整理全部」气泡） */
  categories: () => get('/api/knowledge/categories'),
  getItem: (id) => get(`/api/knowledge/${id}`),
  createItem: (payload) => post('/api/knowledge', payload),
  patchItem: (id, payload) => patch(`/api/knowledge/${id}`, payload),
  deleteItem: (id) => del(`/api/knowledge/${id}`),
  organize: (id) => post(`/api/knowledge/${id}/organize`),
  organizePending: () => post('/api/knowledge/organize-pending'),
  getTask: (taskId) => get(`/api/tasks/${taskId}`),
}

const POLL_START = 1500
const POLL_MAX = 5000
const POLL_TIMEOUT = 20 * 60 * 1000

/**
 * 轮询任务：1.5s 起，指数退避到 5s，最多 20 分钟（接口契约 §4）。
 * 返回 stop()，组件卸载必须调用，否则定时器泄漏。
 */
export function pollTask(taskId, { onUpdate } = {}) {
  let stopped = false
  let timer = null
  let delay = POLL_START
  const startedAt = Date.now()

  const finish = (task) => {
    stopped = true
    onUpdate?.(task)
  }

  const tick = async () => {
    if (stopped) return
    try {
      const task = await api.getTask(taskId)
      if (task.status === 'done' || task.status === 'failed') return finish(task)
      onUpdate?.(task)
    } catch (err) {
      return finish({
        status: 'failed',
        error_code: err?.code || 'POLL_FAILED',
        error_msg: err?.message || '轮询任务失败',
      })
    }
    if (Date.now() - startedAt > POLL_TIMEOUT) {
      return finish({
        status: 'failed',
        error_code: 'POLL_TIMEOUT',
        error_msg: '任务超过 20 分钟未完成',
      })
    }
    delay = Math.min(POLL_MAX, Math.round(delay * 1.25))
    timer = setTimeout(tick, delay)
  }

  timer = setTimeout(tick, POLL_START)
  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
  }
}
