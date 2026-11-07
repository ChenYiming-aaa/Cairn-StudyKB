/**
 * 题目展示与「本地即时判分」的小工具（T4.5）。
 *
 * 为什么前端要判一次：M4 §6.6 要求「答完一题立刻知道对错和解析」，而提交是最后一次性
 * 批量发给后端的。所以客观题先用题目事件里带的 answer 本地比一遍给即时反馈，
 * 交卷时后端**重新判**（`/api/quiz/submit`）——前端改答案骗不到自己。
 * 简答没法本地判，返回 null，界面上写「交卷后由模型批改」。
 *
 * 判定口径必须与 `agents/grader.py` 一致：多选按集合、单选大小写归一、判断转布尔。
 */

export const TYPE_LABELS = { single: '单选', multiple: '多选', boolean: '判断', short: '简答' }
export const DIFFICULTY_LABELS = { basic: '基础', understand: '理解', apply: '应用' }

export const letterOf = (index) => String.fromCharCode(65 + index)

export function typeLabel(type) {
  return TYPE_LABELS[type] || type || '题目'
}

export function difficultyLabel(level) {
  return DIFFICULTY_LABELS[level] || ''
}

/** 用户没作答：空串、空数组、null 都算（后端同样判错并回显参考答案） */
export function isEmptyAnswer(value) {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

function letters(value) {
  if (Array.isArray(value)) return [...new Set(value.map((v) => String(v).trim().toUpperCase()))].sort()
  const text = String(value || '').trim()
  if (!text) return []
  const parts = /[,，、\s]/.test(text) ? text.split(/[,，、\s]+/) : [...text]
  return [...new Set(parts.map((p) => p.trim().charAt(0).toUpperCase()).filter(Boolean))].sort()
}

function asBool(value) {
  if (typeof value === 'boolean') return value
  const text = String(value ?? '').trim().toLowerCase()
  if (['true', '对', '正确', '是', '1'].includes(text)) return true
  if (['false', '错', '错误', '否', '0'].includes(text)) return false
  return null
}

/**
 * 本地判分：true / false / null。
 * null 有两种含义，界面靠 `question.type` 区分：简答（交卷后批改）或 待人工判断。
 */
export function judgeLocal(question, userAnswer) {
  if (isEmptyAnswer(userAnswer)) return false
  const expected = question?.answer

  if (question?.type === 'multiple') {
    const want = letters(expected)
    const got = letters(userAnswer)
    return want.length > 0 && want.join(',') === got.join(',')
  }
  if (question?.type === 'boolean') {
    const got = asBool(userAnswer)
    const want = asBool(expected)
    return got !== null && want !== null && got === want
  }
  if (question?.type === 'short') return null
  return String(userAnswer).trim().toUpperCase() === String(expected ?? '').trim().toUpperCase()
}

/** 把答案转成人话（结果页回显用） */
export function answerText(question, value) {
  if (isEmptyAnswer(value)) return '未作答'
  if (question?.type === 'multiple') return letters(value).join('、')
  if (question?.type === 'boolean') {
    const flag = asBool(value)
    return flag === null ? String(value) : flag ? '对' : '错'
  }
  if (question?.type === 'single') return letters(value).join('') || String(value)
  return String(value)
}
