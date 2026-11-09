/**
 * 主题（M6 T6.7）：6 套配色 × 浅色/深色/跟随系统 × 字号三档。
 *
 * 三处状态，各管一件事，别搞混：
 * 1. `<html data-theme/data-mode/data-fs>` —— 唯一真正生效的地方，CSS 变量靠它切
 * 2. `localStorage` —— 首屏防白闪的快速缓存，由 `public/theme-boot.js` 在挂载前读
 * 3. 后端 `settings.json` 的 `appearance` —— 长期真源（换机器/重装还在）
 *
 * 顺序是「localStorage 先上，后端到了再对齐」，不是反过来：
 * 等后端返回再上主题，用户会先看到一帧默认色。
 */
import { computed, ref } from 'vue'

import { useSettings } from './useSettings'

export const THEMES = [
  { id: 'paper', name: '纸石绿', hint: '默认 · 阅读不刺眼' },
  { id: 'notes', name: '暖墨', hint: '灰褐配琥珀' },
  { id: 'chestnut', name: '栗墨', hint: '深栗棕配靛紫' },
  { id: 'docs', name: '石板蓝', hint: '石板灰配蓝' },
  { id: 'study', name: '学习紫', hint: '紫配绿 · 卡片感' },
  { id: 'teal', name: '效率青', hint: '青配橙 · 利落' },
]

export const MODES = [
  { id: 'light', name: '浅色' },
  { id: 'dark', name: '深色' },
  { id: 'system', name: '跟随系统' },
]

export const FONT_SIZES = [
  { id: 'sm', name: '小', hint: '11–18px' },
  { id: 'md', name: '标准', hint: '12–20px' },
  { id: 'lg', name: '大', hint: '14–23px' },
]

const THEME_IDS = THEMES.map((item) => item.id)
const MODE_IDS = MODES.map((item) => item.id)
const FS_IDS = FONT_SIZES.map((item) => item.id)

const KEYS = { theme: 'cairn.theme', mode: 'cairn.mode', font: 'cairn.fs' }

function read(key, allowed, fallback) {
  try {
    const value = localStorage.getItem(key)
    return allowed.includes(value) ? value : fallback
  } catch {
    return fallback
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 存储被禁只影响「下次打开还是不是这个主题」，不该让切换报错
  }
}

const media = typeof window !== 'undefined' && window.matchMedia
  ? window.matchMedia('(prefers-color-scheme: dark)')
  : null

const theme = ref(read(KEYS.theme, THEME_IDS, 'paper'))
const mode = ref(read(KEYS.mode, MODE_IDS, 'system'))
const fontSize = ref(read(KEYS.font, FS_IDS, 'md'))
const systemDark = ref(Boolean(media?.matches))

const resolvedMode = computed(() =>
  mode.value === 'system' ? (systemDark.value ? 'dark' : 'light') : mode.value,
)

/** 把当前状态写到 `<html>`，并让 `theme-color` 跟着底色走（S-10）。 */
function apply() {
  const root = document.documentElement
  root.dataset.theme = theme.value
  root.dataset.mode = resolvedMode.value
  root.dataset.fs = fontSize.value
  // 从计算样式读，避免在这份 JS 里再抄一遍十六进制色表
  const bg = getComputedStyle(root).getPropertyValue('--c-bg-0').trim()
  if (bg) document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bg)
}

let started = false

/** 挂载前调一次：注册系统明暗监听 + 把 localStorage 的值落到 DOM。 */
export function initTheme() {
  if (started) return
  started = true
  apply()
  media?.addEventListener?.('change', (event) => {
    systemDark.value = event.matches
    if (mode.value === 'system') apply()
  })
}

/** 后端配置到了以后对齐一次；**只在值不同时才动**，避免把用户刚点的选择打回去。 */
function adopt(appearance) {
  if (!appearance) return
  const nextTheme = THEME_IDS.includes(appearance.theme) ? appearance.theme : theme.value
  const nextMode = MODE_IDS.includes(appearance.mode) ? appearance.mode : mode.value
  const nextFont = FS_IDS.includes(appearance.font_size) ? appearance.font_size : fontSize.value
  if (nextTheme === theme.value && nextMode === mode.value && nextFont === fontSize.value) return
  theme.value = nextTheme
  mode.value = nextMode
  fontSize.value = nextFont
  write(KEYS.theme, nextTheme)
  write(KEYS.mode, nextMode)
  write(KEYS.font, nextFont)
  apply()
}

export function useTheme() {
  const { settings, update } = useSettings()

  /** 三项改动都走同一条路：本地立即生效 → 防抖 PATCH 到后端。 */
  function persist() {
    update({ appearance: {
      theme: theme.value,
      mode: mode.value,
      font_size: fontSize.value,
    } })
  }

  function setTheme(id) {
    if (!THEME_IDS.includes(id) || id === theme.value) return
    theme.value = id
    write(KEYS.theme, id)
    apply()
    persist()
  }

  function setMode(id) {
    if (!MODE_IDS.includes(id) || id === mode.value) return
    mode.value = id
    write(KEYS.mode, id)
    apply()
    persist()
  }

  function setFontSize(id) {
    if (!FS_IDS.includes(id) || id === fontSize.value) return
    fontSize.value = id
    write(KEYS.font, id)
    apply()
    persist()
  }

  return {
    theme,
    mode,
    fontSize,
    resolvedMode,
    setTheme,
    setMode,
    setFontSize,
    /** 设置里的 appearance 到了就对齐（App 启动时调一次） */
    adopt: () => adopt(settings.value?.appearance),
  }
}
