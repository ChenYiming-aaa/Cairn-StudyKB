<script setup>
import { computed, ref } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { fileSize } from '../../utils/format'
import { useToast } from '../../composables/useToast'

/**
 * 文件夹批量导入（T10.6）：先看清单，再挑着导。
 *
 * 两件事决定了它长这样：
 * - **只列不导**：一个文件夹扔进来就全导，用户连「哪几个重复、哪几个格式不支持」
 *   都看不到，导完才发现盘里多了 80 条杂物。所以第一步只出清单。
 * - **只在桌面壳里出现**：网页版拿不到文件的绝对路径（浏览器不给），
 *   后端就没法按路径读盘。所以这个入口没有 `window.cairn.importer` 时整个不显示 ——
 *   与其给一个点了报错的按钮，不如不出现。
 */
const emit = defineEmits(['open', 'saved'])
const toast = useToast()

const canPick = Boolean(window.cairn?.importer?.pickDirectory)

const phase = ref('idle')        // idle | scanning | picking | running | done
const folder = ref('')
const files = ref([])            // [{path, name, ext, size, supported, reason, picked}]
const truncated = ref(false)
const limit = ref(100)
const result = ref(null)

const picked = computed(() => files.value.filter((f) => f.picked && f.supported))
const supported = computed(() => files.value.filter((f) => f.supported).length)
const unsupported = computed(() => files.value.filter((f) => !f.supported).length)

async function choose() {
  if (phase.value === 'scanning' || phase.value === 'running') return
  phase.value = 'scanning'
  result.value = null
  try {
    const pickedDir = await window.cairn.importer.pickDirectory()
    if (!pickedDir?.ok) {
      phase.value = 'idle'
      if (pickedDir?.code !== 'CANCELED') toast.error(pickedDir?.message || '打不开选择框')
      return
    }
    folder.value = pickedDir.path
    const data = await api.importScan({ paths: [pickedDir.path] })
    files.value = (data.files || []).map((f) => ({ ...f, picked: Boolean(f.supported) }))
    truncated.value = Boolean(data.truncated)
    limit.value = data.limit || 100
    phase.value = 'done'
    if (!files.value.length) toast.info('这个文件夹里没有能导的文件')
  } catch (err) {
    toast.error(friendlyMessage(err))
    phase.value = 'idle'
  }
}

function toggleAll(flag) {
  files.value = files.value.map((f) => (f.supported ? { ...f, picked: flag } : f))
}

async function run() {
  if (phase.value === 'running' || !picked.value.length) return
  phase.value = 'running'
  try {
    const data = await api.importRun({ paths: picked.value.map((f) => f.path) })
    result.value = data
    phase.value = 'done'
    // 处理过的不再留在清单里（成功、重复、失败都算处理过）：留着会让用户以为还没导，
    // 再点一次也只是又跳一遍重复 —— 失败原因在下面写着，比留在列表里更清楚
    const handled = new Set([
      ...data.added.map((x) => x.path),
      ...data.skipped.map((x) => x.path),
      ...data.failed.map((x) => x.path),
    ])
    files.value = files.value.filter((f) => !handled.has(f.path))
    for (const added of data.added) emit('saved', added.item_id)
    if (data.added_count) toast.ok(`新导入 ${data.added_count} 个文件`)
    if (data.skipped_count) toast.info(`${data.skipped_count} 个已经在库里，没重复导`)
    if (data.failed_count) toast.error(`${data.failed_count} 个没导进来，下面写了原因`)
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    if (phase.value === 'running') phase.value = 'done'
  }
}

function reset() {
  phase.value = 'idle'
  folder.value = ''
  files.value = []
  result.value = null
  truncated.value = false
}
</script>

<template>
  <section v-if="canPick" class="folder">
    <div class="folder-head">
      <div>
        <h3 class="folder-title">整个文件夹一起导</h3>
        <p class="folder-sub">
          先看清单再决定导哪些。只扫这一层，子文件夹不跟进来
        </p>
      </div>
      <button
        class="btn btn-sm"
        type="button"
        :disabled="phase === 'scanning' || phase === 'running'"
        @click="choose"
      >{{ phase === 'scanning' ? '正在看…' : '选文件夹' }}</button>
    </div>

    <p v-if="folder" class="folder-path">{{ folder }}</p>

    <template v-if="files.length">
      <div v-if="supported" class="folder-bar">
        <span class="hint">
          共 {{ files.length }} 个，可导 {{ supported }} 个<template v-if="unsupported">，{{ unsupported }} 个导不了</template>
        </span>
        <button class="btn btn-sm btn-ghost" type="button" @click="toggleAll(picked.length !== supported)">
          {{ picked.length === supported ? '全不选' : '全选' }}
        </button>
      </div>

      <ul class="file-list">
        <li v-for="file in files" :key="file.path" class="file" :class="{ off: !file.supported }">
          <label class="file-pick">
            <input v-model="file.picked" type="checkbox" :disabled="!file.supported" />
          </label>
          <div class="file-body">
            <p class="file-name">{{ file.name }}</p>
            <p class="file-meta">
              {{ file.ext ? `.${file.ext}` : '未知格式' }}
              <template v-if="file.size"> · {{ fileSize(file.size) }}</template>
              <template v-if="!file.supported"> · {{ file.reason }}</template>
            </p>
          </div>
        </li>
      </ul>
    </template>

    <p v-if="truncated && files.length" class="notice">
      只列了前 {{ limit }} 个，剩下的分几批导
    </p>

    <div v-if="result" class="result">
      <p class="result-line">
        新导入 {{ result.added_count }} 个<template v-if="result.skipped_count">，{{ result.skipped_count }} 个已经在库里</template><template v-if="result.failed_count">，{{ result.failed_count }} 个没导进来</template>
      </p>
      <ul v-if="result.failed.length" class="fail-list">
        <li v-for="item in result.failed" :key="item.path">
          {{ item.name }}：{{ item.reason }}
        </li>
      </ul>
    </div>

    <div class="folder-foot">
      <button v-if="files.length || result" class="btn btn-sm btn-ghost" type="button" @click="reset">
        清空
      </button>
      <button
        v-if="picked.length"
        class="btn btn-primary"
        type="button"
        :disabled="phase === 'running'"
        @click="run"
      >{{ phase === 'running' ? '正在导入…' : `导入选中的 ${picked.length} 个` }}</button>
    </div>
  </section>
</template>

<style scoped>
.folder {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-0);
}

.folder-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}

.folder-title {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.folder-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.folder-head .btn {
  margin-left: auto;
  flex: none;
}

.folder-path {
  margin: 0;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-bg-2);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  overflow-wrap: anywhere;
}

.folder-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.folder-bar .btn {
  margin-left: auto;
}

.hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.file-list {
  max-height: 220px;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.file {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
}

.file.off {
  opacity: 0.6;
}

.file-body {
  flex: 1;
  min-width: 0;
}

.file-name {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-meta {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.notice {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-warning-border);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
}

.result {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--c-bg-2);
}

.result-line {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.fail-list {
  margin: var(--space-1) 0 0;
  padding-left: var(--space-4);
  font-size: var(--fs-xs);
  color: var(--c-danger-ink);
}

.folder-foot {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.folder-foot .btn:last-child {
  margin-left: auto;
}
</style>
