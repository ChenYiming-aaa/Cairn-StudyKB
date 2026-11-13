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
  [/^LLM_NO_KEY$/, '还没配模型 Key，整理、问答、出题都用不了。点顶栏「还差一步」把 Key 填进去，不用重启'],
  [/^LLM_QUOTA$/, '模型额度不够或触发了限流，这次没调成功。检查账户余额，或等一会儿再试'],
  [/^LLM_TIMEOUT$/, '模型响应超时，这次没拿到结果。可以重试；简答会记成「待人工判断」，不会判错'],
  [/^LLM_BAD_JSON$/, '模型返回的不是合法 JSON，已自动重试过一次。再点一次；还不行就换个模型'],
  [/^LLM_/, '模型调用没成功。稍后重试；详细原因在任务中心'],
  [/^ENV_INVALID_VALUE$/, '填的内容不合法，这次没保存。去掉引号和换行再试'],
  [/^ENV_NOTHING_TO_SAVE$/, '这次没有可保存的内容。改了配置再点保存'],
  [/^ENV_WRITE_FAILED$/, '配置文件写不进去，这次改动没保存。确认数据目录可写，或用管理员身份重试'],
  [/^ENV_/, '配置没保存成功，改动会丢。再点一次保存；还不行看日志'],
  [/^SETTINGS_INVALID$/, '这项设置的值不合法，这次没保存。改一下再试'],
  [/^SETTINGS_WRITE_FAILED$/, '设置文件写不进去，这次改动没保存。确认数据目录可写'],
  [/^SETTINGS_/, '设置没保存成功，改动会丢。稍后重试'],
  [/^LLM_MODELS_UNSUPPORTED$/, '这个服务不提供模型列表。手动填模型名就能用'],
  [/^TRANSCRIBE_NO_FFMPEG$/, '缺少 ffmpeg，抽不了音频。内容照常保存，只是没有转录'],
  [/^COMPONENT_MISSING$/, '缺一个可选组件，这次没做成。去「设置 → 下载」装上再试，其他功能不受影响'],
  // 识别组件不是"可选增强"：不装就读不了 PDF 和图片（ADR-033），所以单独一条、说得更直白
  [/^OCR_MISSING$/, '这台机器还没装识别组件，PDF 和图片读不出字。去「设置 → 下载」装上就行'],
  [/^OCR_RUNNING$/, '这份文件正在读字，等它跑完再操作'],
  // T9.7 起 docx/pptx/xlsx/txt 也能重读，这条只剩「真的没有任何读法」才会出现
  [/^OCR_NOT_APPLICABLE$/, '这个格式读不出文字。换一份文件，或者另存为 Word、PDF 再试'],
  [/^OCR_PAGE_OUT_OF_RANGE$/, '页码超出这份文件的范围了，重新选一页'],
  [/^OCR_PAGE_EMPTY$/, '这页没认出文字，可以对照右边的页图看看'],
  [/^OCR_FAILED$/, '识别组件出错了，可以重试这一页'],
  [/^PAGE_NOT_FOUND$/, '这一页还没读出来，等识别跑完再看；也可以重试这一页'],
  [/^FILE_NOT_FOUND$/, '原件不在了，可能已经删掉。重新上传一次就能读'],
  [/^OCR_/, '这份文件没读成功，可以重试；失败原因见任务中心'],
  // 下载中心（M8 T8.3）：下面几条要能区分「网络没成」「包不对」「盘不够」，
  // 混成一句"重启应用"会让用户白折腾
  [/^COMPONENT_HASH_MISMATCH$/, '下载的文件校验没通过（可能是网络中断或被镜像改过），已自动删除。再点一次重试'],
  [/^COMPONENT_DOWNLOAD_FAILED$/, '下载没完成。再点一次会从断点接着下，不用从头来'],
  [/^COMPONENT_DISK_FULL$/, '磁盘空间不够。清一些空间再装，装完还能卸载'],
  [/^COMPONENT_BUSY$/, '这个组件正在安装（或旧版本还占着文件）。等它结束，或重启应用后再试'],
  [/^COMPONENT_/, '这个可选组件没跑起来。重启应用试一次；还不行去「设置 → 下载」重新装'],
  [/^TRANSCRIBE_/, '转录没成功，语音识别这一步中断了。详细原因见下方提示或任务中心'],
  [/^FETCH_BROWSER_UNAVAILABLE$/, '网页渲染组件没装，这条没采到。装好 Edge/Chrome 也行，或去「设置 → 下载」装上网页渲染'],
  [/^FETCH_LOGIN_REQUIRED$/, '这个站点要登录才给内容，这条没采到。先在采集面板登录对应站点，再点一次采集'],
  [/^FETCH_/, '采集没成功：站点拒绝访问，或者没抓到有效正文。这种情况改用粘贴更稳'],
  [/^ITEM_NOT_FOUND$/, '内容不存在，可能已经删掉了。刷新列表看看'],
  [/^WORKSPACE_NOT_FOUND$/, '这个工作区不在了，可能刚被删掉。左栏会自己刷新一次'],
  [/^WORKSPACE_/, '工作区没保存成功，改动会丢。再试一次'],
  [/^ITEM_BUSY$/, '这条正在整理中，等它结束再操作'],
  [/^TASK_NOT_RETRYABLE$/, '这个任务不是失败状态，不用重试'],
  [/^SESSION_ALREADY_RUNNING$/, '已经有一轮计时在跑。先结束或放弃它，再开新的'],
  [/^SESSION_STATE$/, '计时状态在别处变过了。刷新一下就是当前状态'],
  [/^SESSION_NOT_FOUND$/, '这次计时不存在，可能已经结束了。刷新看看'],
  [/^SESSION_/, '计时操作没成功。刷新后重试'],
  [/^NETWORK$/, '连不上 Cairn 的本地服务。等几秒再试；一直这样请重启 Cairn'],
  [/^POLL_TIMEOUT$/, '等了超过 20 分钟，先不等了。任务可能还在后台跑，去任务中心看进度'],
  // 只有静态演示版（VITE_DEMO）会返回这个，正式运行永远不会命中
  [/^DEMO_/, '演示版不能生成内容。装桌面版就能采集、整理、出题'],
]

export function friendlyMessage(err) {
  if (!err) return '这次没成功，再试一次；还不行去任务中心看详情'
  for (const [pattern, text] of FRIENDLY) {
    if (pattern.test(err.code || '')) return text
  }
  return err.message || (err.code ? `出了点问题（错误码 ${err.code}）` : '出了点问题')
}

/**
 * detail 只承载排查信息（`provider=deepseek`、`timeout`、`HTTP 429`），
 * 拼进用户提示就是噪音。这里只放行含中文的 detail —— 人话才配出现在 toast 里。
 */
export function humanDetail(detail) {
  const text = String(detail || '').trim()
  return /[\u4e00-\u9fa5]/.test(text) ? text : ''
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
    throw new ApiError({ code: 'NETWORK', message: '连不上 Cairn 的本地服务', detail: 'uvicorn:8756 unreachable' })
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
 * 上传文件（T9.8）：**只有它用 XHR** —— `fetch` 拿不到上传百分比。
 *
 * `onProgress(pct)` 是**上传**进度（0–100），传完就没有了；识别是后台任务，
 * 进度要另外用 `api.ocrProgress()` 轮询。两件事别混成一个条：
 * 上传 100% 不代表字读出来了，用户面对的是「传完 0.3 秒、读字 8 分钟」。
 *
 * `signal` 一 abort 就 `xhr.abort()`：后端读流会断，临时文件被删，不会留半份内容。
 */
export function postFile(path, file, { onProgress, signal, field = 'file', form } = {}) {
  return new Promise((resolve, reject) => {
    const body = new FormData()
    body.append(field, file, file.name)
    for (const [k, v] of Object.entries(form || {})) {
      if (v !== undefined && v !== null && v !== '') body.append(k, String(v))
    }

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${baseUrl()}${path}`)
    xhr.responseType = 'text'
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return
      onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)))
    }
    xhr.onload = () => {
      let data
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null
      } catch {
        data = null
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(data)
      const payload = data?.error || {}
      reject(new ApiError({
        code: payload.code || `HTTP_${xhr.status}`,
        message: payload.message || `HTTP ${xhr.status}`,
        detail: payload.detail || (xhr.responseText || '').slice(0, 300),
        status: xhr.status,
      }))
    }
    xhr.onerror = () => reject(new ApiError({
      code: 'NETWORK',
      message: '上传中断了，网络或本地服务没接住',
      detail: 'xhr upload failed',
    }))
    xhr.onabort = () => {
      const exc = new Error('已取消上传')
      exc.name = 'AbortError'
      reject(exc)
    }
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    xhr.send(body)
  })
}

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
    throw new ApiError({ code: 'NETWORK', message: '连不上 Cairn 的本地服务', detail: 'uvicorn:8756 unreachable' })
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
  // category / tag 只让 counts 跟着筛选走（分类树本身仍是全库）
  categories: (params) => get('/api/knowledge/categories', params),
  getItem: (id) => get(`/api/knowledge/${id}`),
  createItem: (payload) => post('/api/knowledge', payload),
  patchItem: (id, payload) => patch(`/api/knowledge/${id}`, payload),
  deleteItem: (id) => del(`/api/knowledge/${id}`),
  /** 工作区（T9.9）：列表带每条的内容数与 `none_count`（未归类的数量） */
  workspaces: () => get('/api/workspaces'),
  createWorkspace: (payload) => post('/api/workspaces', payload),
  patchWorkspace: (id, payload) => patch(`/api/workspaces/${id}`, payload),
  /** 删工作区只把内容移出，不删内容（后端 SET NULL） */
  deleteWorkspace: (id) => del(`/api/workspaces/${id}`),
  organize: (id) => post(`/api/knowledge/${id}/organize`),
  // 带当前筛选：左栏筛着某分类时，整理的就是这一批
  organizePending: (params) =>
    post(`/api/knowledge/organize-pending${buildQuery(params)}`),
  getTask: (taskId) => get(`/api/tasks/${taskId}`),
  /** 最近任务列表（T2.9 任务中心），失败项可 retry */
  listTasks: (params) => get('/api/tasks', params),
  retryTask: (taskId) => post(`/api/tasks/${taskId}/retry`),
  /** 网页采集：已存在同 URL 时返回 {task_id: null, existing_item_id} */
  ingestUrl: (payload) => post('/api/ingest/url', payload),
  /** 视频采集：返回 {task_id}，四阶段进度靠 pollTask 追 */
  ingestVideo: (payload) => post('/api/ingest/video', payload),
  /** 上传原件（T9.8）：onProgress 给的是上传百分比；落盘后后端自动排队读字 */
  uploadFile: (file, opts) => postFile('/api/files', file, opts),
  /** 读字进度（T9.6）：{status, done_pages, total_pages, failed_pages} */
  ocrProgress: (itemId) => get(`/api/knowledge/${itemId}/ocr`),
  /** 原文页签（T9.10）：{page_no, text, source, avg_conf, image_url, line_conf, html} */
  getPage: (itemId, n) => get(`/api/knowledge/${itemId}/pages/${n}`),
  /** 页图地址（PDF / 扫描页）；图片原件用 fileUrl 拿原格式，别经这层固定 image/jpeg */
  pageImageUrl: (itemId, n) => `${baseUrl()}/api/knowledge/${itemId}/file?page=${n}`,
  fileUrl: (itemId) => `${baseUrl()}/api/knowledge/${itemId}/file`,
  envCheck: () => get('/api/env/check'),
  /** 首次引导（T5.7）：把 llm 配置写进 .env 并热加载，返回 {saved, env_file, check} */
  saveEnvKey: (payload) => post('/api/env/key', payload),
  /** 设置窗口（M6）：全量配置，不含任何密钥，只有 has_key */
  settings: () => get('/api/settings'),
  /** 局部更新配置；返回更新后全量 */
  patchSettings: (payload) => patch('/api/settings', payload),
  /** 探测 provider：{ok, models, latency_ms, error_code, hint} */
  probeProvider: (payload) => post('/api/settings/probe', payload),
  /** 写 provider 的 Key（.env）与地址（settings.json），返回 {saved, env_file, settings} */
  saveProvider: (payload) => post('/api/settings/llm', payload),
  /** 版本元数据 {version, commit, built_at}（T8.5 更新器用） */
  version: () => get('/api/version'),
  /** 可选组件清单 + 状态（M8 T8.3）：{items, repo, release_tag, mirror} */
  components: () => get('/api/components'),
  /** 起后台下载任务，返回 {task_id}；装完的状态要靠 components()/progress 轮询 */
  installComponent: (id) => post(`/api/components/${id}/install`),
  /** 下载进度：{status, phase, got, total, pct, error_code, error_msg} */
  componentProgress: (id) => get(`/api/components/${id}/progress`),
  cancelComponent: (id) => post(`/api/components/${id}/cancel`),
  /** 卸载：停进程 → 删目录，返回 {freed} */
  uninstallComponent: (id) => del(`/api/components/${id}`),
  /** 各站点登录态 + 当前登录任务进度（轮询用，只读文件很快） */
  authStatus: () => get('/api/auth/status'),
  /** 起一个受控浏览器窗口让用户登录，立即返回，结果靠 authStatus 轮询 */
  authLogin: (site) => post(`/api/auth/login/${site}`),
  /** 思维导图（T3.7）：后端出 SVG，直接当图片用；v 是缓存戳，笔记一改就要换 */
  mindmapUrl: (id, theme = 'paper', mode = 'light', version = '') =>
    `${baseUrl()}/api/knowledge/${id}/mindmap?theme=${encodeURIComponent(theme)}` +
    `&mode=${encodeURIComponent(mode)}&v=${encodeURIComponent(version)}`,
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
