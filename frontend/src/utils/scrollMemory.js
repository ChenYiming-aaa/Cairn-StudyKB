/**
 * 原文页签的阅读位置（H3）。
 *
 * 后台刷新（整理轮询 / 采集了新内容 / 批量移入）会让详情子树重挂：原文区从第 1 页开始，
 * 读者被挪走。这里按 `格式:内容 id` 记一份 scrollTop，重挂后放回去。
 *
 * 为什么不是 sessionStorage：这是「这一次打开应用里的手感」，像滚动位置这种像素级的记忆
 * 存到下次启动反而奇怪（而且是高频写）。真正需要跨刷新的草稿走 sessionStorage 的是笔记。
 *
 * 为什么不记「第几页」：只有 PDF 有稳定的页码语义，它在 `PdfView` 自己记页号；
 * Word / PPT / 图片 / 纯文本没有页概念，记像素最省事也最准。
 */
const store = new Map()

export function scrollKey(kind, itemId) {
  return `${kind}:${itemId}`
}

/** 记下当前位置（卸载前、或滚动时都可以调） */
export function saveScroll(key, el) {
  if (!el) return
  store.set(key, el.scrollTop)
}

/**
 * 恢复位置。内容高度常常是异步来的（取页、取版式），太早设 scrollTop 会被夹到 0，
 * 所以失败就隔 60ms 再试，最多 20 次（约 1.2s）。目标位置够不到时（内容变短了）
 * 自然停在最底部，不会报错。
 */
export function restoreScroll(key, el) {
  const top = store.get(key) || 0
  if (!el || top <= 0) return
  let tries = 0
  const apply = () => {
    if (!el || tries >= 20) return
    tries += 1
    el.scrollTop = top
    if (Math.abs(el.scrollTop - top) > 2) setTimeout(apply, 60)
  }
  apply()
}

/** 内容被删时清掉，别让同一个 id 复用后跳到旧位置 */
export function forgetScroll(key) {
  store.delete(key)
}
