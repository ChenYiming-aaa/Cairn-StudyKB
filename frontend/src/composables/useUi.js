/**
 * 跨组件的极轻量共享状态（总纲 §3：不引 Pinia，组合式函数足够）。
 * 只有三件全局事：新建弹窗开关、刷新信号、笔记编辑器的脏标记。
 */
import { ref } from 'vue'

const pasteOpen = ref(false)
const refreshTick = ref(0)
const editorDirty = ref(false)

export function useUi() {
  return {
    pasteOpen,
    refreshTick,
    editorDirty,
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
  }
}
