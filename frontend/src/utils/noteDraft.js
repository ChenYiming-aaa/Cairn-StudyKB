/**
 * 笔记草稿按内容 id 暂存在会话里（H3）。
 *
 * 为什么需要：详情区被骨架屏替换、页面刷新、切到别的内容再回来，都会让编辑器卸载，
 * 而卸载 = 编辑器里的字消失。用 sessionStorage 而不是 localStorage：草稿是「这次打开应用
 * 期间的临时状态」，关掉应用还在反而会让人下次打开时对着一份不知道哪来的旧稿。
 *
 * 为什么单独放一个文件：写入方是 `NoteEditor`，清理方还有 `Knowledge`（内容被删时要顺手清掉）。
 * 两处各写一份前缀字符串，早晚会有一处改漏 —— 于是库里会留一堆看不见、也删不掉的残稿。
 */
const DRAFT_PREFIX = 'cairn.note.draft.'

export function draftKey(itemId) {
  return `${DRAFT_PREFIX}${itemId}`
}

export function readDraft(itemId) {
  try {
    return sessionStorage.getItem(draftKey(itemId))
  } catch {
    // 存储被禁用（隐私模式、配额满）：草稿保命退化成「只有 dirty 标记」，不影响编辑
    return null
  }
}

export function writeDraft(itemId, text) {
  try {
    sessionStorage.setItem(draftKey(itemId), text)
  } catch {
    /* 同上，存不进去不是错误 */
  }
}

export function clearDraft(itemId) {
  try {
    sessionStorage.removeItem(draftKey(itemId))
  } catch {
    /* 同上 */
  }
}
