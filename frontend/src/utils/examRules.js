/**
 * 复核页的三条本地判据 —— 与后端 `services/exam/audit.py: faults()` 同构。
 *
 * 为什么前端要重算这三条：用户当场就会补答案、补选项，补完还挂着旧提示等于骗人；
 * 其余问题（断句、串行、题干重复）要重算整道题，留给「检查题目」重新跑一遍。
 *
 * 为什么收在一个文件里：这三个判据原来散在 `ExamReview.vue` 里，还各写了一份
 * 边角版本（`answerLost` 只处理单选，多选答案指向不存在的选项时提示永远清不掉）。
 * 后端的 `_letters_of` 对 `multiple` 一样判越界，前端必须一样。
 */

const LETTERS = 'ABCDEFGH'

/** 单选 / 多选才谈得上"选项" */
export function isChoice(draft) {
  return draft.type === 'single' || draft.type === 'multiple'
}

/** 填了内容的选项（与后端 `[o for o in options if str(o).strip()]` 一致） */
export function filledOptions(draft) {
  return (draft.options || []).filter((o) => String(o || '').trim())
}

/** 答案是否为空：多选是数组，单选是字符串（对齐后端 `_blank`） */
export function isAnswerEmpty(draft) {
  const value = draft.answer
  if (Array.isArray(value)) return !value.length
  return value === null || value === undefined || !String(value).trim()
}

/**
 * 答案里出现的选项字母。
 * 与后端 `_letters_of` 同一口径：多选存的是数组，单选存的是字符串，只认 A–H。
 */
export function answerLetters(draft) {
  const raw = Array.isArray(draft.answer)
    ? draft.answer.map((v) => String(v)).join('')
    : String(draft.answer || '')
  return [...new Set(raw.toUpperCase().split('').filter((ch) => LETTERS.includes(ch)))]
}

/** 选项不足两个（后端 `FEW_OPTIONS`） */
export function fewOptions(draft) {
  return isChoice(draft) && filledOptions(draft).length < 2
}

/**
 * 答案指向不存在的选项（后端 `ANSWER_OUT_OF_RANGE`）。
 *
 * 三个条件都要与后端相同：单选/多选、选项够两个（否则后端根本不报这条）、
 * 且至少一个字母超出选项个数。多选漏判会让"已经改对了"的提示一直挂着。
 */
export function answerLost(draft) {
  if (!isChoice(draft)) return false
  const options = filledOptions(draft)
  if (options.length < 2) return false
  return answerLetters(draft).some((ch) => LETTERS.indexOf(ch) >= options.length)
}
