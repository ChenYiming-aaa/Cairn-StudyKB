<script setup>
import { ref, watch } from 'vue'

import FileForm from './ingest/FileForm.vue'
import LinkForm from './ingest/LinkForm.vue'
import PasteForm from './ingest/PasteForm.vue'

/**
 * 采集面板（T2.8 建 → T9.8 收成两个入口）。
 *
 * 这一层只剩壳：切 tab、接拖放、把三个表单的结果往外递。
 * 「粘贴文本」是同步的（返回即入库），「文件与链接」是异步的（排队 + 轮询），
 * 两种节奏各自留在自己的组件里 —— 混在一个 878 行的文件里时，
 * 任何一处改动都要把三套状态机重新读一遍。
 *
 * 拖放挂在 dialog 上而不是虚线框里：拖到面板任何地方都该算数，
 * 只认虚线框的话，用户差 20 像素就白拖一次。
 */
const props = defineProps({
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'created', 'existing', 'ingested', 'open', 'uploaded'])

const MODES = [
  { key: 'paste', label: '粘贴文本' },
  { key: 'more', label: '文件与链接' },
]

const mode = ref('paste')
const dragging = ref(false)
const uploading = ref(0)
const fileForm = ref(null)

function onDrop(event) {
  dragging.value = false
  const files = event.dataTransfer?.files
  if (!files?.length) return
  mode.value = 'more'          // 拖进来就切到看得见进度的那一页
  fileForm.value?.addFiles(files)
}

watch(() => props.open, (open) => {
  if (!open) return
  // 每次打开都回到第一页：上一次停在文件页、这次只想贴一段文字，不该多点一下
  mode.value = 'paste'
  dragging.value = false
  uploading.value = 0
})
</script>

<template>
  <div v-if="open" class="mask" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-label="采集内容"
      :class="{ drag: dragging }"
      @dragover.prevent="dragging = true"
      @dragleave.self="dragging = false"
      @drop.prevent="onDrop"
    >
      <header class="dialog-head">
        <h2>采集内容</h2>
        <nav class="tabs" aria-label="采集方式">
          <button
            v-for="m in MODES"
            :key="m.key"
            class="tab"
            :class="{ on: mode === m.key }"
            type="button"
            :aria-label="m.label"
            @click="mode = m.key"
          >
            {{ m.label }}
          </button>
        </nav>
        <div class="grow" />
        <button class="btn btn-ghost btn-sm" type="button" aria-label="关闭采集面板" @click="emit('close')">
          关闭
        </button>
      </header>

      <div class="dialog-body">
        <PasteForm v-show="mode === 'paste'" @created="emit('created', $event)" />

        <template v-if="mode === 'more'">
          <FileForm
            ref="fileForm"
            @busy="uploading = $event"
            @saved="emit('uploaded', $event)"
            @open="emit('open', $event)"
          />
          <p v-if="uploading" class="foot-hint">
            正在上传的文件，面板关掉就会中断。等它传完再关。
          </p>
          <p class="split"><span>或者贴一个链接</span></p>
          <LinkForm
            @existing="emit('existing', $event)"
            @ingested="emit('ingested', $event)"
            @open="emit('open', $event)"
          />
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mask {
  position: fixed;
  inset: 0;
  background: rgba(35, 33, 28, 0.32);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  z-index: 50;
}

.dialog {
  width: min(720px, 100%);
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  background: var(--c-bg-1);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  overflow: hidden;
  transition: outline-color 0.15s;
  outline: 2px dashed transparent;
  outline-offset: -8px;
}

.dialog.drag {
  outline-color: var(--c-primary);
}

.dialog-head {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-6);
  border-bottom: 1px solid var(--c-border);
}

.dialog-head h2 {
  font-size: var(--fs-lg);
}

.tabs {
  display: flex;
  gap: var(--space-1);
  background: var(--c-bg-2);
  padding: 3px;
  border-radius: var(--radius-sm);
}

.tab {
  padding: var(--space-1) var(--space-3);
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.tab.on {
  background: var(--c-bg-1);
  color: var(--c-text-1);
  box-shadow: var(--shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.08));
}

.dialog-body {
  padding: var(--space-4) var(--space-6) var(--space-6);
  overflow: auto;
}

.grow {
  flex: 1;
}

.split {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-6) 0 var(--space-4);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.split::before,
.split::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--c-border);
}

.foot-hint {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-warning-ink);
}
</style>
