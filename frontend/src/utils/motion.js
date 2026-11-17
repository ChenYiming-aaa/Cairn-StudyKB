/**
 * 动效偏好（`docs/dev/动效审计-2026-11-17.md` §2 #11）。
 *
 * 全项目有 9 条路径会调平滑滚动，落点遍布「问答跳转高亮」「翻页定位」。
 * 平滑滚动是前庭敏感最主要的触发源 —— 它位移的是整页内容，幅度可达上千像素，
 * 比任何 opacity 淡入都更该被尊重。所以统一从这里取，而不是每处各写一遍。
 *
 * 只做一件事：把 `behavior` 的取值收成一个函数。别在这里加"动画时长""缓动"之类的参数，
 * 那是 CSS 的事（`styles/app.css`），JS 只管"这次该不该动"。
 */

/** 系统是否要求减少动效。拿不到 `matchMedia` 的环境（测试、SSR）按"不减少"处理。 */
export function prefersReducedMotion() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 给 `scrollIntoView` / `scrollTo` 的 `behavior` 用。 */
export function scrollBehavior() {
  return prefersReducedMotion() ? 'auto' : 'smooth'
}
