/**
 * 演示站里的「自带 Key」调用层（只在 `VITE_DEMO=1` 构建时被引入）。
 *
 * 为什么能纯前端跑：DeepSeek / OpenAI / 阿里 DashScope 的 `/chat/completions`
 * 都返回了允许跨域的预检响应（2026-11-14 实测，带 Pages 站点的 Origin），
 * 所以浏览器可以直接把请求发到服务商官方端点，不需要任何中转服务器。
 * 智谱 GLM 没有返回 CORS 头，浏览器直连会被拦 —— 所以它不在预设里。
 *
 * 三条纪律：
 * 1. **Key 只存在这台机器的 localStorage**，只发给用户填的那个端点，
 *    不经过本项目的任何服务（本项目在 Pages 上根本没有服务）。
 * 2. **不做静默降级**：连不上就说清是哪一步断的（CORS / 401 / 429 / 超时），
 *    不要用一段像模像样的假结果糊过去 —— 演示站最容易在这里变成谎言。
 * 3. **请求体与后端一致**：同样是 `model + messages + max_tokens + stream`，
 *    结构化任务带 `response_format`。这样这里看到的效果才代表桌面版的效果。
 */

/** 预设：只放实测能跨域直连的。`base` 末尾不带斜杠，`url` 拼 `/chat/completions`。 */
export const PROVIDERS = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    base: 'https://api.deepseek.com',
    model: 'deepseek-chat',
    models: ['deepseek-chat', 'deepseek-reasoner'],
    keyUrl: 'https://platform.deepseek.com/api_keys',
    note: '便宜，中文稳。注册后在「API keys」里建一个',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    base: 'https://api.openai.com/v1',
    model: 'gpt-4o-mini',
    models: ['gpt-4o-mini', 'gpt-4o'],
    keyUrl: 'https://platform.openai.com/api-keys',
    note: '要能访问 openai.com',
  },
  {
    id: 'dashscope',
    label: '通义千问（阿里云）',
    base: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
    models: ['qwen-plus', 'qwen-max', 'qwen-turbo'],
    keyUrl: 'https://bailian.console.aliyun.com/?apiKey=1',
    note: '国内直连最稳',
  },
  {
    id: 'custom',
    label: '其他（OpenAI 兼容）',
    base: '',
    model: '',
    models: [],
    keyUrl: '',
    note: '填对方的地址；不返回跨域头的话浏览器会被拦，这是对方服务器的限制',
  },
]

const STORE_KEY = 'cairn.try.conn'

/** 读回上次填的连接信息。**只在本机 localStorage**，换浏览器就没了。 */
export function loadConn() {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return null
    const got = JSON.parse(raw)
    return got && got.base ? got : null
  } catch {
    return null
  }
}

export function saveConn(conn) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(conn))
  } catch {
    /* 隐私模式下写不进去，不影响这一次使用 */
  }
}

export function clearConn() {
  try {
    localStorage.removeItem(STORE_KEY)
  } catch {
    /* 同上 */
  }
}

/** 把「用户填的东西」变成一个能直接发请求的地址。 */
export function endpointOf(base) {
  const clean = String(base || '').trim().replace(/\/+$/, '')
  if (!clean) return ''
  // 已经填到 /chat/completions 就原样用，别拼成两遍
  if (/\/chat\/completions$/.test(clean)) return clean
  return `${clean}/chat/completions`
}

export class LlmError extends Error {
  constructor(code, message, detail = '') {
    super(message)
    this.name = 'LlmError'
    this.code = code
    this.detail = detail
  }
}

/**
 * 一次对话调用。`json` 为真时要求对方返回 JSON 对象。
 *
 * 为什么 `json` 失败要再试一次去掉 `response_format`：有些兼容实现不认这个字段，
 * 直接 400。桌面版对同样的服务也是这么兜的（`llm_route.payload` 里 json_mode 可关）。
 */
export async function chat({ conn, messages, json = false, maxTokens = 4096, timeoutMs = 120000 }) {
  const url = endpointOf(conn.base)
  if (!url) throw new LlmError('NO_BASE', '还没填接口地址')
  if (!String(conn.key || '').trim()) throw new LlmError('NO_KEY', '还没填 Key')

  const body = {
    model: conn.model,
    messages,
    max_tokens: maxTokens,
    stream: false,
  }
  if (json) body.response_format = { type: 'json_object' }

  const send = async (payload) => {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
      return await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${conn.key.trim()}`,
        },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      })
    } finally {
      clearTimeout(timer)
    }
  }

  let resp
  try {
    resp = await send(body)
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new LlmError('TIMEOUT', `等了 ${Math.round(timeoutMs / 1000)} 秒没响应，再试一次`,
      )
    }
    // fetch 在网络层被挡下时抛 TypeError，浏览器**不会告诉你是谁挡的**
    throw new LlmError(
      'NETWORK',
      '请求没发出去。多半是这个接口不允许网页直接调用（跨域被拦），或者网络不通',
      '换 DeepSeek / 通义 试试；或确认能访问该地址。浏览器控制台的 Network 面板能看到具体原因',
    )
  }

  if (!resp.ok) {
    let text = ''
    try {
      text = await resp.text()
    } catch {
      /* 读不到正文就只能报状态码 */
    }
    let detail = text.slice(0, 300)
    try {
      const parsed = JSON.parse(text)
      detail = parsed?.error?.message || parsed?.message || detail
    } catch {
      /* 不是 JSON 就用原文 */
    }
    if (resp.status === 401 || resp.status === 403) {
      throw new LlmError('AUTH', 'Key 不对或没有权限（401/403）', detail)
    }
    if (resp.status === 429) {
      throw new LlmError('QUOTA', '额度不够或请求太频繁（429）', detail)
    }
    if (resp.status === 404) {
      throw new LlmError('NO_MODEL', '这个地址没有这个模型（404）', detail)
    }
    if (resp.status >= 500) {
      throw new LlmError('UPSTREAM', `对方服务出错（${resp.status}）`, detail)
    }
    // 400 里最常见的是「不认 response_format」或「模型名不对」
    if (json && resp.status === 400) {
      const retry = await send({ ...body, response_format: undefined })
      if (retry.ok) return readText(await retry.json())
      throw new LlmError('BAD_REQUEST', `请求被拒（${resp.status}）`, detail)
    }
    throw new LlmError('BAD_REQUEST', `请求被拒（${resp.status}）`, detail)
  }

  return readText(await resp.json())
}

function readText(payload) {
  const msg = payload?.choices?.[0]?.message || {}
  const text = msg.content ?? ''
  const usage = payload?.usage || {}
  return {
    text: String(text).trim(),
    usage: { in: usage.prompt_tokens || 0, out: usage.completion_tokens || 0 },
    model: payload?.model || '',
  }
}

/**
 * 把模型回的东西当 JSON 读。
 *
 * 它经常带 ```json 围栏、或者在 JSON 前后写一句「好的，这是结果：」——
 * 这两种都不该算失败，剥掉就行。真的解析不了才报错，并**把原文带出来**，
 * 否则用户只看到「解析失败」，不知道自己该改什么。
 */
export function parseJson(text) {
  let body = String(text || '').trim()
  const fence = body.match(/```(?:json)?\s*([\s\S]*?)```/)
  if (fence) body = fence[1].trim()
  const at = body.search(/[[{]/)
  if (at > 0) body = body.slice(at)
  const lastObj = body.lastIndexOf('}')
  const lastArr = body.lastIndexOf(']')
  const end = Math.max(lastObj, lastArr)
  if (end > 0) body = body.slice(0, end + 1)
  try {
    return JSON.parse(body)
  } catch {
    throw new LlmError('BAD_JSON', '模型这次没按格式回，再点一次', String(text).slice(0, 300))
  }
}
