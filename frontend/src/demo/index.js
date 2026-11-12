/**
 * 静态演示层（只在 `VITE_DEMO=1` 构建时被加载，正式构建里这段代码会被整体摇掉）。
 *
 * 为什么需要它：Cairn 的网页版是「Vue 前端 + 本地 Python 后端」，而 github.io 只能放静态
 * 文件。为了让别人不装任何东西就能看清界面长什么样，这里把**真实后端曾经返回过的响应**
 * （`fixtures.json`，由真跑一遍整理/问答/出题后抓取）当成数据源顶上去。
 *
 * 三条原则，避免演示变成谎言：
 * 1. **不伪造 AI**：整理、采集、出题、问答一律拒绝，并明确告诉用户去装桌面版。
 *    宁可看到一个「这里需要后端」的提示，也不要让用户以为自己问的问题被答了。
 * 2. **只在读取路径上做重定向**：写入只能落在内存里（复习作答、交卷判分），刷新即还原。
 * 3. **判分是真算的**：客观题按 fixture 里的标准答案本地比对，不是预录结果。
 */
import { api } from '../api/client'
import { judgeLocal } from '../utils/quiz'

import fixtures from './fixtures.json'

const BASE = import.meta.env.BASE_URL || '/'

const clone = (value) => JSON.parse(JSON.stringify(value))
const data = clone(fixtures)

/** 演示期内的可变状态：复习答过的题、交卷结果。刷新页面即回到初始值。 */
const state = {
  reviewed: new Set(),
}

/** 题目库：复习队列 + 错题本里有标准答案的题，交卷时按它判分 */
const questionBank = new Map()
for (const q of [...(data.review_due?.items || []), ...(data.wrong?.items || [])]) {
  if (!questionBank.has(q.question_id)) questionBank.set(q.question_id, q)
}

const DEMO_BLOCKED =
  '演示版不能生成内容。装桌面版就能采集、整理、出题'

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
  })
}

function blocked() {
  return jsonResponse({ error: { code: 'DEMO_OFFLINE', message: DEMO_BLOCKED, detail: '' } }, 403)
}

/** 列表过滤：q 走标题/摘要子串，category/tag 精确匹配，status 精确匹配 */
function filterItems(list, params) {
  const q = (params.get('q') || '').trim().toLowerCase()
  const category = params.get('category') || ''
  const tag = params.get('tag') || ''
  const status = params.get('status') || ''
  return list.filter((it) => {
    if (category && it.category !== category) return false
    if (tag && !(it.tags || []).includes(tag)) return false
    if (status && it.status !== status) return false
    if (q && !`${it.title} ${it.summary || ''}`.toLowerCase().includes(q)) return false
    return true
  })
}

function snippetOf(text, needle) {
  const at = needle ? text.toLowerCase().indexOf(needle.toLowerCase()) : -1
  if (at < 0) return text.slice(0, 120)
  const from = Math.max(0, at - 40)
  return (from > 0 ? '…' : '') + text.slice(from, from + 140) + '…'
}

/** 演示版没有 FTS5/向量：用子串匹配兜底，结果里明说 match_type=demo */
function searchItems(q) {
  const needle = q.trim()
  if (!needle) return { items: [], total: 0, fallback: 'none', match_type: 'demo' }
  const hits = []
  for (const detail of Object.values(data.details)) {
    for (const [source, text] of [
      ['raw', detail.raw_content || ''],
      ['note', detail.structured_note || ''],
    ]) {
      if (!text.toLowerCase().includes(needle.toLowerCase())) continue
      hits.push({
        chunk_id: `${detail.id}-${source}`,
        item_id: detail.id,
        item_title: detail.title,
        snippet: snippetOf(text, needle),
        content: text,
        source,
        match_type: 'demo',
      })
    }
  }
  return { items: hits, total: hits.length, fallback: 'none', match_type: 'demo' }
}

function gradeOne(entry) {
  const q = questionBank.get(Number(entry.question_id))
  if (!q) {
    return {
      question_id: entry.question_id,
      is_correct: null,
      correct_answer: null,
      explanation: '',
      feedback: null,
    }
  }
  const isCorrect = q.type === 'short' ? null : judgeLocal(q, entry.user_answer)
  return {
    question_id: entry.question_id,
    is_correct: isCorrect,
    correct_answer: q.answer,
    explanation: q.explanation || '',
    feedback: null,
  }
}

/** 路由表：按 pathname 匹配，顺序有意义（更具体的放前面） */
// 演示站也要能打开设置窗口（M6 T6.7/T6.8）：没有这两个接口，齿轮一点就是一片报错。
// 外观读 localStorage 而不是写死，否则观众选了主题一刷新就被打回默认。
const look = () => ({
  theme: localStorage.getItem('cairn.theme') || 'paper',
  mode: localStorage.getItem('cairn.mode') || 'system',
  font_size: localStorage.getItem('cairn.fs') || 'md',
})

const DEMO_SETTINGS = () => ({
  llm: {
    active: 'deepseek',
    providers: {
      deepseek: {
        label: 'DeepSeek',
        base_url: 'https://api.deepseek.com',
        has_key: true,
        supports_effort: true,
        models: ['deepseek-flash', 'deepseek-reasoner'],
      },
      custom: {
        label: 'OpenAI 兼容',
        base_url: '',
        has_key: false,
        supports_effort: false,
        models: [],
      },
    },
    tasks: {
      organizer: { provider: 'deepseek', model: 'deepseek-flash', effort: 'low' },
      asker: { provider: 'deepseek', model: 'deepseek-flash', effort: 'low' },
      quizzer: { provider: 'deepseek', model: 'deepseek-flash', effort: 'low' },
      grader: { provider: 'deepseek', model: 'deepseek-flash', effort: 'low' },
    },
  },
  appearance: look(),
  components: {},
  env_file: '%APPDATA%\\Cairn\\.env',
})

// 下载中心：演示版没有后端，也没法往磁盘写 690 MB。这里给出**真实形状**的空状态，
// 让设置窗口的「下载」tab 能正常渲染并说明"演示版不能装"，而不是弹一句
// 跟组件无关的"整理/采集要本地后端"。
const DEMO_COMPONENTS = () => ({
  items: [
    {
      id: 'embed', name: '向量检索', why: '让问答能按意思找，而不只是按字面。不装也能用，搜得糙一点。',
      size: 261959001, version: '', min_app_version: '0.2.0', state: 'missing',
      mode: null, bytes: 0,
      install: { status: '', phase: '', got: 0, total: 0, pct: 0, error_code: '', error_msg: '', task_id: '' },
    },
    {
      id: 'asr', name: '视频转录', why: '没有字幕的视频也能转成文字。不装的话，只支持本来就带字幕的视频。',
      size: 99980567, version: '', min_app_version: '0.2.0', state: 'missing',
      mode: null, bytes: 0,
      install: { status: '', phase: '', got: 0, total: 0, pct: 0, error_code: '', error_msg: '', task_id: '' },
    },
    {
      id: 'browser', name: '网页渲染', why: '知乎这类必须跑脚本才出正文的站点要用。不装也能采大部分网页。',
      size: 48922004, version: '', min_app_version: '0.2.0', state: 'missing',
      mode: null, bytes: 0,
      install: { status: '', phase: '', got: 0, total: 0, pct: 0, error_code: '', error_msg: '', task_id: '' },
    },
    {
      id: 'ocr', name: '本地识别', why: '读 PDF 和图片要用。不装的话，这两类内容读不出字。',
      size: 130000000, version: '', min_app_version: '0.2.0', state: 'missing',
      mode: null, bytes: 0,
      install: { status: '', phase: '', got: 0, total: 0, pct: 0, error_code: '', error_msg: '', task_id: '' },
    },
  ],
  repo: 'ChenYiming-aaa/Cairn-StudyKB',
  release_tag: 'components-v1',
  manifest_version: 1,
  min_app_version: '0.2.0',
  mirror: '',
  demo: true,
})

const ROUTES = [
  [/^\/api\/health$/, () => data.health],
  [/^\/api\/components$/, () => DEMO_COMPONENTS()],
  // 版本号由 vite.config.js 的 define 从 package.json 注入，别写死（发版会忘）
  [/^\/api\/version$/, () => ({ version: __APP_VERSION__, commit: null, built_at: null })],
  [/^\/api\/settings$/, () => DEMO_SETTINGS()],
  [/^\/api\/env\/check$/, () => data.env],
  [/^\/api\/knowledge\/categories$/, () => data.categories],
  [
    /^\/api\/knowledge$/,
    (_m, { params }) => {
      const list = filterItems(data.items.items, params)
      const pageSize = Number(params.get('page_size') || list.length || 50)
      return { items: list.slice(0, pageSize), total: list.length }
    },
  ],
  [/^\/api\/knowledge\/(\d+)$/, (m) => data.details[m[1]] || { error: { code: 'ITEM_NOT_FOUND' } }],
  [
    /^\/api\/tasks$/,
    (_m, { params }) => {
      const limit = Number(params.get('limit') || 50)
      return { items: data.tasks.items.slice(0, limit), total: data.tasks.total }
    },
  ],
  [/^\/api\/tasks\/([^/]+)$/, () => data.tasks.items[0] || { status: 'done' }],
  [
    /^\/api\/ask\/history$/,
    (_m, { params }) => {
      const limit = Number(params.get('limit') || 50)
      const offset = Number(params.get('offset') || 0)
      const items = data.ask_history.items.slice(offset, offset + limit)
      return { items, total: data.ask_history.total }
    },
  ],
  [/^\/api\/ask\/history\/(\d+)$/, (m) => data.ask_details[m[1]] || { error: { code: 'NOT_FOUND' } }],
  [/^\/api\/search$/, (_m, { params }) => searchItems(params.get('q') || '')],
  [
    /^\/api\/html$/,
    (_m, { params }) => {
      const limit = Number(params.get('limit') || 30)
      return { items: data.html_pages.items.slice(0, limit), total: data.html_pages.total }
    },
  ],
  [
    /^\/api\/review\/due$/,
    (_m, { params }) => {
      const limit = Number(params.get('limit') || 20)
      const items = data.review_due.items.filter((q) => !state.reviewed.has(q.question_id))
      return {
        items: items.slice(0, limit),
        total: items.length,
        tracked: data.review_due.tracked,
        wrong: data.review_due.wrong,
        now: data.review_due.now,
      }
    },
  ],
  [
    /^\/api\/quiz\/wrong$/,
    (_m, { params }) => {
      const limit = Number(params.get('limit') || 50)
      return { items: data.wrong.items.slice(0, limit), total: data.wrong.total }
    },
  ],
  [/^\/api\/session\/current$/, () => data.session_current],
  [
    /^\/api\/session$/,
    (_m, { params }) => {
      const targetId = params.get('target_id')
      const items = data.session_history.items.filter(
        (s) => !targetId || String(s.target_id) === String(targetId)
      )
      return { items, total: items.length }
    },
  ],
  [/^\/api\/stats\/today$/, () => data.stats_today],
  [/^\/api\/stats\/week$/, () => data.stats_week],
]

const POST_ROUTES = [
  [
    /^\/api\/settings$/,
    (_m, { body }) => {
      // PATCH 在演示里只回显，不落盘：界面「改完即时生效」的手感在，但刷新就复原
      const merged = DEMO_SETTINGS()
      return { ...merged, ...(body || {}) }
    },
  ],
  [
    /^\/api\/settings\/probe$/,
    () => ({
      ok: false,
      models: [],
      latency_ms: 0,
      error_code: 'DEMO_OFFLINE',
      hint: '演示模式不会真的去连模型服务。下载桌面版后，这里能列出对方的模型',
    }),
  ],
  [
    /^\/api\/quiz\/submit$/,
    (_m, { body }) => {
      const answers = body?.answers || []
      const items = answers.map(gradeOne)
      const graded = items.filter((it) => it.is_correct !== null)
      const correct = graded.filter((it) => it.is_correct).length
      return {
        items,
        correct_count: correct,
        total: graded.length,
        accuracy: graded.length ? Number((correct / graded.length).toFixed(4)) : 0,
      }
    },
  ],
  [
    /^\/api\/review\/(\d+)\/result$/,
    (m) => {
      state.reviewed.add(Number(m[1]))
      return { ok: true }
    },
  ],
]

function resolve(url, method, body) {
  const path = url.pathname.replace(/^.*?\/api\//, '/api/')
  const params = url.searchParams
  if (method === 'GET') {
    for (const [pattern, handler] of ROUTES) {
      const match = path.match(pattern)
      if (match) return { ok: true, payload: handler(match, { params }) }
    }
    return { ok: false }
  }
  for (const [pattern, handler] of POST_ROUTES) {
    const match = path.match(pattern)
    if (match) return { ok: true, payload: handler(match, { body }) }
  }
  return { ok: false }
}

export function installDemo() {
  const original = window.fetch.bind(window)
  window.fetch = async (input, init = {}) => {
    const raw = typeof input === 'string' ? input : input?.url || ''
    let url
    try {
      url = new URL(raw, window.location.href)
    } catch {
      return original(input, init)
    }
    if (!url.pathname.includes('/api/')) return original(input, init)

    const method = String(init.method || 'GET').toUpperCase()
    let body = null
    if (typeof init.body === 'string') {
      try {
        body = JSON.parse(init.body)
      } catch {
        body = null
      }
    }

    // 给交互留一点网络感，避免界面闪得太假（也让 loading 态能被看见）
    await new Promise((resolve) => setTimeout(resolve, 80))

    const hit = resolve(url, method, body)
    if (!hit.ok) return blocked()
    return jsonResponse(hit.payload)
  }

  // 这两类 URL 由 <img>/<iframe> 直接请求，不经过 fetch，只能把地址指到静态资源
  api.mindmapUrl = (_id, _theme, mode) =>
    `${BASE}demo/mindmap-${mode === 'dark' ? 'dark' : 'light'}.svg`
  api.htmlUrl = (id) => `${BASE}demo/page-${id}.html`
  api.htmlDownloadUrl = (id) => `${BASE}demo/page-${id}.html`

  // 顶栏的「已连接」是真判断，这里补一句，免得用户以为连到了什么远端服务
  window.__CAIRN_DEMO__ = true
}
