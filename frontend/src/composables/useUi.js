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

export function useUi() {
  return {
    pasteOpen,
    refreshTick,
    editorDirty,
    focusItemId,
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
  }
}
