/**
 * 三栏布局的宽度与折叠状态（T7.0）。
 *
 * 为什么不用 prop 逐层传：侧栏散在 7 个页面里，宽度是**全局视觉属性**，
 * 用 CSS 变量（--w-sidebar / --w-list）比让每个页面各自维护一份 state 更省。
 *
 * 三条约定（M7 §3.1）：
 * 1. 全部写 localStorage，刷新/切页/重启都保持
 * 2. 左栏折叠后是 **44px 窄条（rail）**，不是 0；条目列表折叠才是 0
 * 3. 用户手动动过（拖宽 / 折叠）之后，窗口变窄不再自动收 —— 「我调好了别再动我」
 *
 * 模块级单例，和 useUi / useTimer 同一套路（总纲 §3：不引 Pinia）。
 */

import { reactive } from 'vue'

/** 折叠成窄条的宽度，与 tokens.css 的 --w-rail 必须一致 */
export const RAIL_WIDTH = 44

const KEY = {
  sidebar: 'cairn.layout.sidebar',
  list: 'cairn.layout.list',
  panels: 'cairn.layout.panels',
}

/** 可拖拽的两栏：min/max 是 M7 §3.2 给的区间 */
const DEFAULT = {
  sidebar: { width: 232, min: 200, max: 320 },
  list: { width: 320, min: 260, max: 420 },
}

/** 其它侧栏的折叠态（问答历史 / 学习页选择器 / 练习配置），T7.3 接入 */
const PANELS = ['chat', 'picker', 'config']

const state = reactive({
  sidebar: { width: DEFAULT.sidebar.width, collapsed: false, touched: false },
  list: { width: DEFAULT.list.width, collapsed: false, touched: false },
  panels: { chat: false, picker: false, config: false },
})

// 自动收起的这一轮标记：只用于「变窄自动收、变宽自动还」，
// 用户手动折叠的不该被窗口变宽偷偷展开，所以两者必须分开记
let autoCollapsed = false
let booted = false

function clamp(target, width) {
  const { min, max } = DEFAULT[target]
  if (!Number.isFinite(width)) return DEFAULT[target].width
  return Math.min(max, Math.max(min, Math.round(width)))
}

function apply() {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.style.setProperty(
    '--w-sidebar',
    `${state.sidebar.collapsed ? RAIL_WIDTH : state.sidebar.width}px`
  )
  root.style.setProperty('--w-list', `${state.list.collapsed ? 0 : state.list.width}px`)
  // data 属性给 CSS 用（窄条内边距与拖动条的显隐），比再传一层 prop 稳
  root.dataset.sidebar = state.sidebar.collapsed ? 'rail' : 'open'
  root.dataset.list = state.list.collapsed ? 'off' : 'open'
}

function persist(target) {
  try {
    localStorage.setItem(KEY[target], JSON.stringify(state[target]))
  } catch {
    // 隐私模式/存储被禁：只影响「下次还记不记得」，不该让页面报错
  }
}

function hydrate() {
  if (booted) return
  booted = true
  for (const target of ['sidebar', 'list']) {
    try {
      const raw = localStorage.getItem(KEY[target])
      if (!raw) continue
      const saved = JSON.parse(raw)
      if (saved && typeof saved === 'object') {
        if (Number.isFinite(saved.width)) state[target].width = clamp(target, saved.width)
        if (typeof saved.collapsed === 'boolean') state[target].collapsed = saved.collapsed
        if (saved.touched === true) state[target].touched = true
      }
    } catch {
      // 坏 JSON 当没存过，用默认值
    }
  }
  try {
    const raw = localStorage.getItem(KEY.panels)
    if (raw) {
      const saved = JSON.parse(raw)
      for (const name of PANELS) {
        if (saved && typeof saved[name] === 'boolean') state.panels[name] = saved[name]
      }
    }
  } catch {
    // 同上
  }
  apply()
}

// 模块加载即对齐一次：默认 232px 写在 CSS 里，存过 300px 的用户不该看到先抖一下
hydrate()

/** 窗口变窄自动收成窄条；用户动过就不再自动收（M7 §3.3 前两档） */
export function installResponsiveLayout() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {}
  const mq = window.matchMedia('(max-width: 1199px)')
  const sync = () => {
    if (mq.matches) {
      if (!state.sidebar.touched && !state.sidebar.collapsed) {
        state.sidebar.collapsed = true
        autoCollapsed = true
        apply()
      }
    } else if (autoCollapsed) {
      state.sidebar.collapsed = false
      autoCollapsed = false
      apply()
    }
  }
  sync()
  mq.addEventListener('change', sync)
  return () => mq.removeEventListener('change', sync)
}

export function useLayout() {
  hydrate()

  return {
    state,
    width: (target) => state[target].width,
    isCollapsed: (target) => state[target].collapsed,

    /** 拖拽 / 键盘微调用；persist=false 时只改内存（拖动过程不必每次都写盘） */
    setWidth: (target, next, { persist: save = true } = {}) => {
      const width = clamp(target, next)
      if (state[target].width === width && !save) return
      state[target].width = width
      state[target].touched = true
      apply()
      if (save) persist(target)
    },

    /** 双击手柄复位到默认宽。touched 保持为 true：用户已经动过，就别再让自动收起抢方向盘 */
    resetWidth: (target) => {
      state[target].width = DEFAULT[target].width
      apply()
      persist(target)
    },

    toggle: (target) => {
      state[target].collapsed = !state[target].collapsed
      state[target].touched = true
      autoCollapsed = false
      apply()
      persist(target)
    },

    expand: (target) => {
      if (!state[target].collapsed) return
      state[target].collapsed = false
      state[target].touched = true
      autoCollapsed = false
      apply()
      persist(target)
    },

    collapse: (target) => {
      if (state[target].collapsed) return
      state[target].collapsed = true
      state[target].touched = true
      autoCollapsed = false
      apply()
      persist(target)
    },

    /** 其它侧栏（浮层/选择器/配置栏）：只有折叠态，没有宽度 */
    isPanelCollapsed: (name) => Boolean(state.panels[name]),
    setPanel: (name, collapsed) => {
      if (!PANELS.includes(name)) return
      state.panels[name] = Boolean(collapsed)
      try {
        localStorage.setItem(KEY.panels, JSON.stringify(state.panels))
      } catch {
        // 同 persist()
      }
    },
  }
}
