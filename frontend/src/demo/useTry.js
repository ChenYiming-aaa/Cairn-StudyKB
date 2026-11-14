/**
 * 「自带 Key 试用」的状态与三步动作（只在演示站加载）。
 *
 * 三个动作直接对应桌面版的三个核心能力，用的提示词是**构建时从后端原样注入**的
 * （`vite.config.js` 的 `demoPrompts()`），不是另抄一份 —— 否则演示效果会与产品慢慢对不上。
 *
 * 与桌面版的两处简化，界面上都如实写了：
 * 1. 问答不走向量检索，把材料切块后**全给**模型（桌面版按意思取最相关的几块）。
 *    所以这里的 `[1]` 是「第几段材料」，不是数据库里的 chunk id。
 * 2. 出题不做过往题面去重（桌面版会排除已经出过的题）。
 */
/* global __DEMO_PROMPTS__ */
import { computed, reactive, ref } from 'vue'

import { PROVIDERS, chat, clearConn, loadConn, parseJson, saveConn } from './llm'

export const PROMPTS = __DEMO_PROMPTS__ || {}

/** 材料切块：空行分段，超长的段再按句号切。只为了让模型能按 `[n]` 指回来。 */
export function splitParas(text, max = 700) {
  const paras = String(text || '')
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
  const out = []
  for (const para of paras) {
    if (para.length <= max) {
      out.push(para)
      continue
    }
    let buf = ''
    for (const sentence of para.split(/(?<=[。！？!?；;])/)) {
      if (buf.length + sentence.length > max && buf) {
        out.push(buf.trim())
        buf = ''
      }
      buf += sentence
    }
    if (buf.trim()) out.push(buf.trim())
  }
  return out
}

function fill(template, vars) {
  return String(template || '').replace(/\{\{([A-Z_]+)\}\}/g, (whole, key) =>
    key in vars ? String(vars[key]) : whole,
  )
}

const SAMPLE = `二级 Python 的命题以「读懂小程序」为核心：40 道选择题里有近半数给出一段 3～8 行的代码，要求判断输出结果或变量类型。这类题不考算法设计，考的是对运算符优先级、可变与不可变对象、字符串切片边界的熟悉程度。

切片是最容易丢分的一类。规则是左闭右开，步长为负时从右往左取。例如 s = "abcdef"，s[1:4] 得到 "bcd"，而 s[::-1] 得到整个串的反转。很多人错在把 s[4:1] 当成 "edc"，实际结果是空串——起点在终点右边且步长为正时，Python 直接返回空串，不会自动交换两端。

可变对象是第二个坑。列表是可变对象，把列表赋给另一个变量只是复制了引用，改其中一个另一个会跟着变。要真正复制，得用 list(a) 或 a[:]。元组不可变，所以元组里的元素不能被重新赋值；但如果元组里装的是列表，那个列表本身仍可修改。

运算符优先级里，比较运算符可以连写，a < b < c 等价于 a < b and b < c，这是 Python 特有的写法。而 and 的优先级高于 or，not 最高。位运算 & 的优先级高于比较运算符，这一点与 C 语言一致，容易写错。`

export function useTry() {
  const saved = loadConn()
  const conn = reactive({
    provider: saved?.provider || 'deepseek',
    base: saved?.base || PROVIDERS[0].base,
    key: saved?.key || '',
    model: saved?.model || PROVIDERS[0].model,
  })

  const material = ref('')
  const ready = computed(() => Boolean(conn.base.trim() && conn.key.trim() && conn.model.trim()))

  /** 三步各自的状态：idle / running / done / error */
  const steps = reactive({
    conn: { state: 'idle', msg: '', detail: '' },
    note: { state: 'idle', msg: '', detail: '' },
    answer: { state: 'idle', msg: '', detail: '' },
    quiz: { state: 'idle', msg: '', detail: '' },
  })

  const note = ref(null)
  const answer = ref(null)
  const quiz = ref([])
  const question = ref('')
  const paras = computed(() => splitParas(material.value))
  const usage = reactive({ in: 0, out: 0, calls: 0 })

  function pickProvider(id) {
    const got = PROVIDERS.find((p) => p.id === id) || PROVIDERS[0]
    conn.provider = got.id
    if (got.base) conn.base = got.base
    if (got.model) conn.model = got.model
    steps.conn = { state: 'idle', msg: '', detail: '' }
  }

  function remember() {
    saveConn({ provider: conn.provider, base: conn.base.trim(), key: conn.key.trim(), model: conn.model.trim() })
  }

  function forget() {
    conn.key = ''
    clearConn()
  }

  function useSample() {
    material.value = SAMPLE
    note.value = null
    answer.value = null
    quiz.value = []
    steps.note = { state: 'idle', msg: '', detail: '' }
    steps.answer = { state: 'idle', msg: '', detail: '' }
    steps.quiz = { state: 'idle', msg: '', detail: '' }
  }

  function failed(step, err) {
    const target = steps[step]
    target.state = 'error'
    target.msg = err?.message || '这步没成功'
    target.detail = err?.detail || ''
  }

  function consume(result) {
    usage.in += result.usage.in
    usage.out += result.usage.out
    usage.calls += 1
  }

  /** ① 连不连得上：一次 10 个 token 的调用，比什么都不发更能说明问题 */
  async function testConn() {
    steps.conn = { state: 'running', msg: '', detail: '' }
    try {
      const got = await chat({
        conn,
        maxTokens: 16,
        timeoutMs: 45000,
        messages: [{ role: 'user', content: '只回复两个字：可用' }],
      })
      consume(got)
      remember()
      steps.conn = { state: 'done', msg: `通了，对方回的是「${got.text.slice(0, 12)}」`, detail: '' }
      return true
    } catch (err) {
      failed('conn', err)
      return false
    }
  }

  /** ② 整理：对应桌面版的 organize */
  async function organize() {
    if (!material.value.trim()) return
    steps.note = { state: 'running', msg: '', detail: '' }
    try {
      const prompt = fill(PROMPTS.organize, {
        TITLE: material.value.trim().split('\n')[0].slice(0, 40),
        CONTENT: material.value.trim(),
      })
      const got = await chat({
        conn,
        json: true,
        messages: [{ role: 'user', content: prompt }],
      })
      consume(got)
      remember()
      const data = parseJson(got.text)
      note.value = {
        title: String(data.title || '').trim(),
        category: String(data.category || '').trim(),
        tags: Array.isArray(data.tags) ? data.tags.filter(Boolean).slice(0, 8) : [],
        summary: String(data.summary || '').trim(),
        key_points: Array.isArray(data.key_points) ? data.key_points.filter(Boolean) : [],
        structured_note: String(data.structured_note || '').trim(),
      }
      steps.note = { state: 'done', msg: '', detail: '' }
    } catch (err) {
      failed('note', err)
    }
  }

  /** ③ 追问：对应桌面版的 ask（材料切块后全给，编号 [1]..[n]） */
  async function ask() {
    const q = question.value.trim()
    if (!q) return
    steps.answer = { state: 'running', msg: '', detail: '' }
    answer.value = null
    try {
      const blocks = paras.value.map((text, idx) => `[${idx + 1}] ${text}`).join('\n\n')
      const prompt = fill(PROMPTS.ask, { CONTEXT: blocks, QUESTION: q })
      const got = await chat({ conn, messages: [{ role: 'user', content: prompt }] })
      consume(got)
      remember()
      answer.value = { text: got.text, question: q, blocks: paras.value }
      steps.answer = { state: 'done', msg: '', detail: '' }
    } catch (err) {
      failed('answer', err)
    }
  }

  /** ④ 出题：对应桌面版的 quiz（3 道单选 / 判断题） */
  async function makeQuiz() {
    steps.quiz = { state: 'running', msg: '', detail: '' }
    quiz.value = []
    try {
      const src = note.value?.structured_note || material.value
      const prompt = fill(PROMPTS.quiz, {
        TITLE: note.value?.title || material.value.trim().split('\n')[0].slice(0, 30),
        MATERIAL_NOTE: note.value?.structured_note ? '下面是整理好的笔记' : '下面是原始材料',
        MATERIAL: src,
        COUNT: 3,
        TYPES: 'single（单选）、boolean（判断）',
        DIFFICULTY: 'understand',
        EXCLUDE: '（没有出过的题）',
      })
      const got = await chat({ conn, json: true, messages: [{ role: 'user', content: prompt }] })
      consume(got)
      remember()
      const list = parseJson(got.text)
      quiz.value = (Array.isArray(list) ? list : list.questions || [])
        .slice(0, 6)
        // idx 是渲染与判分要用的稳定键：模型不给 id，数组下标就是它
        .map((q, idx) => ({ ...q, idx }))
      steps.quiz = { state: 'done', msg: '', detail: '' }
    } catch (err) {
      failed('quiz', err)
    }
  }

  const busy = computed(
    () => steps.note.state === 'running' || steps.answer.state === 'running' || steps.quiz.state === 'running',
  )

  return {
    conn,
    material,
    question,
    ready,
    busy,
    steps,
    note,
    answer,
    quiz,
    paras,
    usage,
    pickProvider,
    forget,
    useSample,
    testConn,
    organize,
    ask,
    makeQuiz,
  }
}
