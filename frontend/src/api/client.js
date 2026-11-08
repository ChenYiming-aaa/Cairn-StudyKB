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
  [/^LLM_NO_KEY$/, '未配置模型 Key：点顶栏「环境待配置」填入 Key 即可，不用重启'],
  [/^LLM_QUOTA$/, '模型额度不足或触发限流：检查账户余额，或稍后再试'],
  [/^LLM_TIMEOUT$/, '模型响应超时：可以重试；简答批改会记成「待人工判断」而不是判错'],
  [/^LLM_BAD_JSON$/, '模型返回的内容不是合法 JSON，已自动重试过一次'],
  [/^LLM_/, '模型调用失败，请稍后重试（详细原因见任务记录）'],
  [/^ENV_INVALID_VALUE$/, '填写的内容不合法：去掉引号和换行再试'],
  [/^ENV_NOTHING_TO_SAVE$/, '没有需要保存的内容'],
  [/^ENV_WRITE_FAILED$/, '写不进配置文件：确认数据目录可写，或用管理员身份重试'],
  [/^ENV_/, '保存配置失败，请稍后重试'],
  [/^TRANSCRIBE_NO_FFMPEG$/, '缺少 ffmpeg，无法抽取音频：录制内容照常入库，转录不可用'],
  [/^TRANSCRIBE_/, '转录失败，详细原因见下方提示或任务记录'],
  [/^FETCH_BROWSER_UNAVAILABLE$/, '浏览器渲染不可用：请安装 Edge/Chrome，或让后端执行 playwright install chromium'],
  [/^FETCH_LOGIN_REQUIRED$/, '该页面需要登录才能看，请先在采集面板里登录对应站点'],
  [/^FETCH_/, '采集失败：目标站点拒绝访问或没有有效正文'],
  [/^ITEM_NOT_FOUND$/, '条目不存在，可能已被删除'],
  [/^ITEM_BUSY$/, '该条目正在整理中，请等它结束'],
  [/^TASK_NOT_RETRYABLE$/, '该任务不是失败状态，不能重试'],
  [/^SESSION_ALREADY_RUNNING$/, '已经有一个计时在进行中，先把它结束或放弃'],
  [/^SESSION_STATE$/, '计时状态已经变了，刷新一下就正确了'],
  [/^SESSION_NOT_FOUND$/, '这次计时不存在，可能已经结束'],
  [/^SESSION_/, '计时操作失败，请刷新后重试'],
  [/^NETWORK$/, '连不上后端服务，请确认 uvicorn 已在 8756 端口启动'],
  [/^POLL_TIMEOUT$/, '任务超时未返回，请稍后在任务记录里查看'],
  // 只有静态演示版（VITE_DEMO）会返回这个，正式运行永远不会命中
  [/^DEMO_/, '这是静态演示版：生成、采集、整理、问答都要本地后端，请下载桌面版运行'],
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

/** 给 `navigator.sendBeacon` 用：闭窗前必须拿到绝对 URL（相对路径在 beacon 里不保证能解析）*/
export function apiBase() {
  return baseUrl()
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

/**
 * SSE：POST + ReadableStream 手工解析（不用 EventSource，它不支持 POST 与请求体）。
 * 接口契约 §4 的约定形状：每帧 `data: {json}\n\n`。
 * 返回 Promise，流结束（或出错）后 resolve；传 signal 可中断。
 */
export async function streamSSE(path, body, onEvent, { signal } = {}) {
  const url = `${baseUrl()}${path}`
  let res
  try {
    res = await fetch(url, {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
    })
  } catch (exc) {
    if (exc?.name === 'AbortError') throw exc
    throw new ApiError({ code: 'NETWORK', message: '无法连接后端服务' })
  }

  if (!res.ok || !res.body) {
    const raw = await res.text().catch(() => '')
    let payload = {}
    try {
      payload = JSON.parse(raw)?.error || {}
    } catch {
      // 非 JSON 错误体（例如代理返回的 HTML）：保持空对象，下面用状态码兜底
    }
    throw new ApiError({
      code: payload.code || `HTTP_${res.status}`,
      message: payload.message || `HTTP ${res.status}`,
      detail: payload.detail || raw.slice(0, 300),
      status: res.status,
    })
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let cut = buffer.indexOf('\n\n')
    while (cut >= 0) {
      const frame = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      const data = frame
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('\n')
      if (data) {
        try {
          onEvent?.(JSON.parse(data))
        } catch {
          // 坏帧不该让整条流中断：跳过，继续读下一帧
        }
      }
      cut = buffer.indexOf('\n\n')
    }
  }
}

/** 语义化端点：路径只在这里出现一次。 */
export const api = {
  health: () => get('/api/health'),
  /** 全文 + 向量融合检索（M3 T3.1/T3.4），返回 {items,total,fallback,match_type} */
  search: (params) => get('/api/search', params),
  /** 问答历史（T3.12）：列表不带来源快照，详情才有 */
  askHistory: (params) => get('/api/ask/history', params),
  askHistoryDetail: (id) => get(`/api/ask/history/${id}`),
  deleteAskHistory: (id) => del(`/api/ask/history/${id}`),
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
  /** 最近任务列表（T2.9 任务中心），失败项可 retry */
  listTasks: (params) => get('/api/tasks', params),
  retryTask: (taskId) => post(`/api/tasks/${taskId}/retry`),
  /** 网页采集：已存在同 URL 时返回 {task_id: null, existing_item_id} */
  ingestUrl: (payload) => post('/api/ingest/url', payload),
  /** 视频采集：返回 {task_id}，四阶段进度靠 pollTask 追 */
  ingestVideo: (payload) => post('/api/ingest/video', payload),
  envCheck: () => get('/api/env/check'),
  /** 首次引导（T5.7）：把 llm 配置写进 .env 并热加载，返回 {saved, env_file, check} */
  saveEnvKey: (payload) => post('/api/env/key', payload),
  /** 各站点登录态 + 当前登录任务进度（轮询用，只读文件很快） */
  authStatus: () => get('/api/auth/status'),
  /** 起一个受控浏览器窗口让用户登录，立即返回，结果靠 authStatus 轮询 */
  authLogin: (site) => post(`/api/auth/login/${site}`),
  /** 思维导图（T3.7）：后端出 SVG，直接当图片用；v 是缓存戳，笔记一改就要换 */
  mindmapUrl: (id, theme = 'light', version = '') =>
    `${baseUrl()}/api/knowledge/${id}/mindmap?theme=${theme}&v=${encodeURIComponent(version)}`,
  /** 学习页（T3.9）：生成是同步的，返回 {id,title,size_bytes} */
  htmlGenerate: (payload) => post('/api/html/generate', payload),
  htmlPages: (params) => get('/api/html', params),
  deleteHtml: (id) => del(`/api/html/${id}`),
  htmlUrl: (id) => `${baseUrl()}/api/html/${id}`,
  htmlDownloadUrl: (id) => `${baseUrl()}/api/html/${id}/download`,
  /** 批量交卷并判分（T4.4）；is_correct 可能是 null = 待人工判断，不是答错 */
  quizSubmit: (payload) => post('/api/quiz/submit', payload),
  /** 错题本（T4.6）：最近一次作答仍答错的题 */
  wrongQuestions: (params) => get('/api/quiz/wrong', params),
  /** 今日待复习（T4.6）：拿到的题自带 options/answer/explanation，可直接作答 */
  dueReviews: (params) => get('/api/review/due', params),
  /** 单个上报复习结果（T4.7）：只用于人工裁定「待人工判断」的题 */
  reportReview: (questionId, payload) => post(`/api/review/${questionId}/result`, payload),
  /** 番茄钟（T5.1）：同一时刻只允许一个，409 会带上现有 id */
  sessionStart: (payload) => post('/api/session/start', payload),
  sessionCurrent: () => get('/api/session/current'),
  /** action ∈ pause/resume/finish/abandon；finish 可带 {note} */
  sessionAction: (id, action, payload) => post(`/api/session/${id}/${action}`, payload),
  sessionHeartbeat: (id) => post(`/api/session/${id}/heartbeat`),
  /** 学习记录（按 target 过滤，只列 done/abandoned） */
  sessionHistory: (params) => get('/api/session', params),
  statsToday: () => get('/api/stats/today'),
  statsWeek: () => get('/api/stats/week'),
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
