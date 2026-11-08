/**
 * 跨组件的极轻量共享状态（总纲 §3：不引 Pinia，组合式函数足够）。
 * 只有这几件全局事：新建弹窗开关、刷新信号、笔记编辑器的脏标记、
 * 「切到知识库并选中某条」的跳转请求（采集完成后「去看看」用），
 * 以及环境自检结果（T5.7：顶栏的状态点与引导页要共享同一份，不能各查一套）。
 */
import { computed, ref } from 'vue'

import { api } from '../api/client'

const pasteOpen = ref(false)
const refreshTick = ref(0)
const editorDirty = ref(false)
const focusItemId = ref(null)
// 问答来源卡片跳转：除了条目 id 还要知道落在哪一段（M3 T3.6）
const focusChunk = ref(null)

// ── 环境自检（T5.7）──────────────────────────────────────
const SETUP_KEY = 'cairn.setup.dismissed'
const envState = ref(null)          // 最近一次 /api/env/check 的结果，null = 还没查过
const envLoaded = ref(false)
// 用户点过「稍后再说」就不再自动跳引导页；但顶栏那个黄点照常留着，
// 否则"我没填 Key"这件事会彻底消失，等到出题失败时才莫名报错
const setupDismissed = ref(
  typeof localStorage !== 'undefined' && localStorage.getItem(SETUP_KEY) === '1'
)

/** 硬需求只有两条：没有 Key 什么都问不了，没有 ffmpeg 视频采不了 */
const envBlocking = computed(() => {
  const env = envState.value
  if (!env) return []
  const missing = []
  if (!env.llm?.ok) missing.push('llm')
  if (!env.ffmpeg?.ok) missing.push('ffmpeg')
  return missing
})

async function loadEnv() {
  try {
    envState.value = await api.envCheck()
  } catch {
    // 后端没起来时这里必然会失败，App 顶栏已经有「未连接」提示，不重复弹
    envState.value = null
  } finally {
    envLoaded.value = true
  }
  return envState.value
}

export function useUi() {
  return {
    pasteOpen,
    refreshTick,
    editorDirty,
    focusItemId,
    focusChunk,
    openPaste: () => {
      pasteOpen.value = true
    },
    closePaste: () => {
      pasteOpen.value = false
    },
    requestRefresh: () => {
      refreshTick.value += 1
    },
    setEditorDirty: (value) => {
      editorDirty.value = Boolean(value)
    },
    /** 请求跳到知识库并选中该条目；由 Knowledge.vue 消费后置回 null */
    openItem: (itemId) => {
      focusItemId.value = itemId
    },
    /** 跳转并定位到某段原文（问答点 [n] 用；ItemDetail 消费后置回 null） */
    openItemAt: (itemId, chunk) => {
      focusChunk.value = chunk
        ? { itemId, text: chunk.text || '', source: chunk.source || 'raw' }
        : null
      focusItemId.value = itemId
    },
    // 环境自检相关
    envState,
    envLoaded,
    envBlocking,
    setupDismissed,
    loadEnv,
    /** 引导页保存成功后直接塞新结果，省一次往返（接口本来就返回整套 check） */
    setEnvState: (next) => {
      envState.value = next
      envLoaded.value = true
    },
    dismissSetup: () => {
      setupDismissed.value = true
      try {
        localStorage.setItem(SETUP_KEY, '1')
      } catch {
        // 隐私模式/存储被禁：只影响"下次不再自动弹"，不该让页面报错
      }
    },
  }
}

