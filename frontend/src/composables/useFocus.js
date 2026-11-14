/**
 * 引用跳转在原文里的落地方式（T11.2 补齐 Word / PPT / 图片）。
 *
 * PDF 有「页」可翻，所以它走 `knowledge/{id}/locate` 拿到页号再滚（见 `raw/PdfView.vue`）。
 * 其余三种没有页图这一层：Word 整份一次渲染、图片单页一屏、PPT 按页翻但只有大纲。
 * 所以这里只做一件事 —— **在已经渲染出来的文字里找到那段话，标一下、滚过去**。
 * 找不到就什么都不做：停在开头不是错误，弹个提示才是打扰。
 */
import { ref, watch } from 'vue'

import { api } from '../api/client'

// 只在这些块级元素里找：命中要标在「一句/一段」上，标在整个容器上等于没标
const BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, td, th, pre'

/**
 * 在 `root` 里找到那段话并标出来，返回被标的元素（找不到返回 null）。
 *
 * **比对忽略空白**：chunk 是 chunker 拼回来的，换行被规整成空格、标题里的
 * 「考试 二级」在原文里可能是连着的 —— 带空白比会在第一个空格处就断掉。
 * 所以两边都去掉空白再比，长短仍按原文字符数递减。
 *
 * 标的是**行内样式**而不是 class：这段内容来自 `v-html` 或别人的模板，
 * 加 class 既要 `:deep` 又要担心组件重渲染把它冲掉，行内样式最省心，
 * 颜色仍走令牌（`--c-mark`），换主题照样跟着变。
 */
export function highlightIn(root, chunk, hint) {
  if (!root) return null
  const nodes = [...root.querySelectorAll(BLOCKS)].filter((el) => !el.querySelector(BLOCKS))
  if (!nodes.length) return null
  const haystacks = nodes.map((el) => squash(el.textContent))

  // 搜索词优先：用户点的是「这一句」，而 chunk 的起点可能在上一页/上一段
  for (const [text, floor] of [[hint, 4], [chunk, 8]]) {
    const needle = squash(text)
    if (needle.length < floor) continue
    for (const size of [600, 400, 240, 160, 120, 80, 48, 24, 16, 12, needle.length]) {
      const cut = needle.slice(0, size)
      if (cut.length < floor) continue
      const at = haystacks.findIndex((hay) => hay.includes(cut))
      if (at < 0) continue
      const node = nodes[at]
      node.style.background = 'var(--c-mark)'
      node.style.color = 'var(--c-text-1)'
      node.style.borderRadius = '3px'
      // 留个标记：行内样式既是高亮也是线索，`data-hit` 让"到底标中了哪一块"可被检查
      node.dataset.hit = '1'
      node.scrollIntoView({ block: 'center', behavior: 'smooth' })
      return node
    }
  }
  return null
}

/** 去掉全部空白（含全角空格）：切块与渲染对空白的处理本来就不一致 */
function squash(text) {
  return (text || '').replace(/[\s\u3000]+/g, '')
}

/**
 * 问后端「这段字在第几页第几行」。`{page, from, to, matched}`，落不到页时 value 为 null。
 *
 * 两个参数都传 getter：调用方多是 props，取值时机在异步回来之后，直接传值会拿到旧值。
 */
export function useLocate(itemId, focus) {
  const marks = ref(null)
  watch(
    focus,
    async (target) => {
      marks.value = null
      if (!target?.chunkId) return
      const hit = await api.locate(itemId(), target.chunkId, target.hint).catch(() => null)
      if (!hit?.page_no) return
      marks.value = {
        page: Number(hit.page_no),
        from: Number(hit.line_from) || 0,
        to: Number(hit.line_to) || 0,
        matched: String(hit.matched || ''),
      }
    },
    { immediate: true }
  )
  return marks
}
