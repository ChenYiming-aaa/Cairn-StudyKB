/**
 * 跨组件的极轻量共享状态（总纲 §3：不引 Pinia，组合式函数足够）。
 * 只有四件全局事：新建弹窗开关、刷新信号、笔记编辑器的脏标记、
 * 以及「切到知识库并选中某条」的跳转请求（采集完成后「去看看」用）。
 */
import { ref } from 'vue'

const pasteOpen = ref(false)
const refreshTick = ref(0)
const editorDirty = ref(false)
const focusItemId = ref(null)
// 问答来源卡片跳转：除了条目 id 还要知道落在哪一段（M3 T3.6）
const focusChunk = ref(null)

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
  }
}
