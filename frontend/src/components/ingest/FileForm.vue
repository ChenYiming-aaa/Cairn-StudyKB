<script setup>
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '../../api/client'
import { useUi } from '../../composables/useUi'
import FileIngestCard from './FileIngestCard.vue'
import FolderImport from './FolderImport.vue'

/**
 * 「文件与链接」里的文件区（T9.8）：拖 / 点选都收，一次多个，每个文件一张卡。
 *
 * 文件列表活在**这个组件里**而不是卡片里：卡片只管自己那一次上传，
 * 谁被移除、一共还有几个在传，是列表的事。
 * 拖放的入口统一在面板那一层（`IngestPanel` 的 dialog），拖到面板任何地方都算数 ——
 * 只在虚线框里能拖是一种很容易踩空的交互。
 */
const emit = defineEmits(['open', 'busy', 'saved'])

const { openSettings } = useUi()

const fileInput = ref(null)
const items = ref([])             // [{id, file}]
const phases = ref({})            // id → 卡片上报的阶段
const ocrReady = ref(null)        // null = 还没查到，别用假状态吓人
let seq = 0

const uploading = computed(() =>
  Object.values(phases.value).filter((p) => p === 'uploading').length
)

watch(uploading, (n) => emit('busy', n))

/** PDF / 图片要识别组件（ADR-033）；装了、或本机自带，都算能读 */
async function loadOcr() {
  try {
    const data = await api.components()
    const ocr = (data.items || []).find((it) => it.id === 'ocr')
    ocrReady.value = Boolean(ocr && (ocr.state === 'installed' || ocr.mode))
  } catch {
    ocrReady.value = null
  }
}

function addFiles(files) {
  for (const file of Array.from(files || [])) {
    items.value.push({ id: ++seq, file })
  }
}

function onPick(event) {
  addFiles(event.target.files)
  event.target.value = ''          // 允许重复选同一个文件
}

function remove(id) {
  const at = items.value.findIndex((it) => it.id === id)
  if (at >= 0) items.value.splice(at, 1)
  delete phases.value[id]
}

function onPhase(id, phase) {
  phases.value[id] = phase
}

onMounted(loadOcr)

defineExpose({ addFiles })
</script>

<template>
  <div>
    <p v-if="ocrReady === false" class="warn">
      读 PDF 与图片要先装「本地识别」。Word、PPT、Excel、文本不受影响。
      <button class="warn-link" type="button" @click="openSettings('downloads')">去设置</button>
    </p>

    <div class="dropzone" @click="fileInput?.click()">
      <p class="drop-title">把文件拖到这里，或点一下选</p>
      <p class="drop-hint">Word、PDF、PPT、Excel、图片、文本都行；一次可以选多个</p>
      <input
        ref="fileInput"
        class="hidden"
        type="file"
        multiple
        accept=".docx,.pdf,.pptx,.xlsx,.txt,.md,.png,.jpg,.jpeg,.webp"
        @change="onPick"
      />
    </div>

    <div v-if="items.length" class="list">
      <FileIngestCard
        v-for="it in items"
        :key="it.id"
        :file="it.file"
        @phase="onPhase(it.id, $event)"
        @open="emit('open', $event)"
        @saved="emit('saved', $event)"
        @gone="remove(it.id)"
      />
    </div>

    <!-- 文件夹批量导入（T10.6）：只在桌面壳里出现，网页版拿不到绝对路径 -->
    <FolderImport @open="emit('open', $event)" @saved="emit('saved', $event)" />
  </div>
</template>

<style scoped>
.warn {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  margin: 0 0 var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft, var(--c-bg-2));
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--c-warning-ink);
}

.warn-link {
  flex: none;
  padding: 0;
  border: 0;
  background: none;
  font-size: var(--fs-xs);
  color: var(--c-primary-ink);
  text-decoration: underline;
  cursor: pointer;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 140px;
  padding: var(--space-6);
  border: 1px dashed var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
  cursor: pointer;
  text-align: center;
}

.dropzone:hover {
  border-color: var(--c-primary);
}

.drop-title {
  margin: 0;
  font-size: var(--fs-md);
  color: var(--c-text-1);
}

.drop-hint {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.hidden {
  display: none;
}

.list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
</style>
