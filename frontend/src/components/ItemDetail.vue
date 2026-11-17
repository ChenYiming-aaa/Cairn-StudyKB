<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage, pollTask } from '../api/client'
import StatusBadge from './StatusBadge.vue'
import MindmapPane from './MindmapPane.vue'
import NoteEditor from './NoteEditor.vue'
import RawPane from './RawPane.vue'
import SessionLog from './SessionLog.vue'
import SummaryPane from './SummaryPane.vue'
import TitleEditor from './TitleEditor.vue'
import { useTheme } from '../composables/useTheme'
import { useTimer } from '../composables/useTimer'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'
import { usable } from '../utils/components'
import { fullTime } from '../utils/format'

const props = defineProps({
  item: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  // 同上：同一条内容的后台刷新（不是换内容），只走顶部一条细线，不换骨架屏
  refreshing: { type: Boolean, default: false },
  error: { type: String, default: '' },
  // D-01：空态要分两种——"库里有内容但没选中" vs "库里一条都没有"，
  // 后者说"从左侧选一条"是死路。默认 true，避免首次加载瞬间误报"还没有内容"。
  hasItems: { type: Boolean, default: true },
  // [{ id, name }]：详情里那个「移到哪个工作区」的下拉（T9.9）
  workspaces: { type: Array, default: () => [] },
})
const emit = defineEmits(['refresh', 'deleted', 'create', 'move'])

const toast = useToast()
const router = useRouter()
const { focusChunk, openSettings, componentsTick } = useUi()
// 导图是后端现场出的 SVG，明暗得前端告诉它（T6.7）；让它自己判断会和界面脱节
const { theme, resolvedMode } = useTheme()

const tab = ref('summary')
const organizing = ref(false)
// 笔记页签里的导图折叠块是否展开（2026-11-17 从一级页签降下来）
const mindmapOpen = ref(false)
function onMindmapToggle(event) {
  mindmapOpen.value = Boolean(event?.target?.open)
}
// 问答点 [n] 跳过来时定位的那一段：{text, key}。key 每次跳转都变，
// 目的是让 RawPane 即使跳的是同一段也能重新滚动一次。
const focus = ref(null)
let stopPolling = null

// T9.11：试卷不出笔记（整理只出卷面概览），所以「整理笔记」页签对它不给
// —— 留着一个空编辑器，等于暗示「这里本该有笔记」
//
// 2026-11-17：导图从一级页签降为「整理笔记」里的折叠块。理由是同源——
// 导图按 `structured_note` 的标题层级画，和笔记是**同一份内容的两种排版**，
// 不产生新信息；给它一个和「原文」并列的页签，等于把「换一种画法」说成「另一种内容」。
// 例外是试卷：试卷没有笔记页签，导图是它唯一的结构视图，留在页签上（见 `tabs`）。
const TABS_ALL = [
  { key: 'summary', label: '摘要与要点' },
  { key: 'note', label: '整理笔记' },
  { key: 'raw', label: '原文' },
  { key: 'sessions', label: '学习记录' },
]
const MINDMAP_TAB = { key: 'mindmap', label: '思维导图' }
const tabs = computed(() => {
  if (props.item?.kind !== 'exam') return TABS_ALL
  // 试卷：去掉 note，把 mindmap 放在「原文」后面（与改动前的顺序一致）
  return TABS_ALL.flatMap((entry) => {
    if (entry.key === 'note') return []
    if (entry.key === 'raw') return [entry, MINDMAP_TAB]
    return [entry]
  })
})

// T5.3：从条目点「开始专注」，把这条件为目标带进计时（target_type=item）
const { start: startSession } = useTimer()

async function startFocus() {
  if (!props.item) return
  const created = await startSession({
    target_type: 'item',
    target_id: props.item.id,
    planned_seconds: 1500,
  })
  if (created) toast.info(`开始专注：${props.item.title}`)
}

const isPending = computed(() => props.item?.status !== 'ready')
const busy = computed(() => organizing.value || props.item?.status === 'organizing')

/**
 * 能不能「导入试卷」（T10.3）：得有一份读完的原件，且是能出题的类型。
 * 只认 PDF 与图片 —— Word 试卷也常见，但版式还原出来的题号不可靠，
 * 先用最稳的两类，别在没验证过的格式上给入口。
 */
const EXAM_EXTS = ['pdf', 'png', 'jpg', 'jpeg', 'webp']
const isOcrFile = computed(() =>
  EXAM_EXTS.includes(String(props.item?.file?.ext || '').toLowerCase())
)
const canImportExam = computed(() => {
  const file = props.item?.file
  if (!file) return false
  return EXAM_EXTS.includes(String(file.ext || '').toLowerCase())
    && file.ocr_status === 'done' && Number(file.page_count || 0) > 0
})

/**
 * 是 PDF/图片但还没读完（5-3）：按钮要**出现但禁用**，旁边说清差在哪 ——
 * 整个不渲染时，用户只会认为这个版本不支持试卷导入。
 */
const examBlockedByRead = computed(() =>
  isOcrFile.value && Boolean(props.item?.file) && !canImportExam.value
)

/**
 * 原件读字状态（6-3）。关掉采集面板后，这份 PDF 在界面上「失踪」过：
 * 详情只写「待整理」，点整理得到「还在读字」的 409（而实际什么都没在跑），
 * 采集面板里那张卡早没了，也没有任何「重读」入口。
 */
const ocrProgress = ref(null)      // `/knowledge/{id}/ocr` 的最近一次结果
const ocrReady = ref(null)         // 识别组件能不能用：null 还没查到
const reocrBusy = ref(false)
let ocrTimer = null

const fileWord = computed(() => (isOcrFile.value ? '识别' : '读取'))
const fileState = computed(() => {
  const file = props.item?.file
  if (!file) return null
  const status = String(file.ocr_status || '')
  const total = Number(file.page_count || 0)
  const done = Number(ocrProgress.value?.done_pages ?? 0)
  if (status === 'done') return { text: total ? `已${fileWord.value} ${total} 页` : `已${fileWord.value}`, tone: 'ok' }
  if (status === 'partial') return { text: `已${fileWord.value} ${done}/${total} 页`, tone: 'warn' }
  if (status === 'running') return { text: `正在${fileWord.value}${total ? ` ${done}/${total} 页` : ''}`, tone: 'busy' }
  if (status === 'failed') return { text: `${fileWord.value}没成功`, tone: 'bad' }
  if (status === 'pending') return { text: ocrReady.value === false ? '缺「本地识别」组件' : '还没开始读字', tone: 'warn' }
  if (status === 'none') return { text: '这类文件读不出文字', tone: 'bad' }
  return null
})
/** 没读完、但还有救（能重读）；`none` 是格式本身读不出字，给重读也没用 */
const needsRead = computed(() => {
  const status = String(props.item?.file?.ocr_status || '')
  return Boolean(props.item?.file) && status !== 'done' && status !== 'none'
})

async function probeOcr() {
  try {
    const data = await api.components()
    ocrReady.value = usable((data.items || []).find((item) => item.id === 'ocr'))
  } catch {
    ocrReady.value = null
  }
}

// 装好/卸载组件后重探（6-1）：详情页那个「去装识别组件 / 重读」按钮要跟着换
watch(componentsTick, probeOcr)

async function loadOcrProgress() {
  if (!props.item?.id || !isOcrFile.value) return
  try {
    const data = await api.ocrProgress(props.item.id)
    ocrProgress.value = data
    if (data.status === 'running') scheduleOcr()
  } catch {
    // 进度拿不到就不显示页数，别把「查不到」说成「0 页」
  }
}

function scheduleOcr() {
  if (ocrTimer) return
  ocrTimer = setTimeout(async () => {
    ocrTimer = null
    await loadOcrProgress()
  }, 2500)
}

/** 重读：原件已在库，重新排队一次识别（6-3 的出口） */
async function reocr() {
  const item = props.item
  if (!item || reocrBusy.value) return
  reocrBusy.value = true
  try {
    await api.reocr(item.id)
    toast.info(`已重新排队${fileWord.value}，读完就能整理`)
    emit('refresh', item.id)
    await loadOcrProgress()
    scheduleOcr()
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    reocrBusy.value = false
  }
}

function openExamReview() {
  const fileId = props.item?.file?.id
  if (fileId) router.push(`/exam/${fileId}`)
}

watch(
  () => props.item?.id,
  () => {
    tab.value = 'summary'
    focus.value = null
    ocrProgress.value = null
    if (ocrTimer) {
      clearTimeout(ocrTimer)
      ocrTimer = null
    }
    loadOcrProgress()
    probeOcr()
  },
  { immediate: true }
)

// 试卷的「整理笔记」页签不存在，但 tab 可能还停在那儿（刚从普通资料切过来）
watch(tabs, (list) => {
  if (!list.some((entry) => entry.key === tab.value)) tab.value = 'summary'
})

/** 来源卡片跳转：条目换了也要生效，所以同时监听 item.id 与 focusChunk */
watch(
  () => [props.item?.id, focusChunk.value],
  () => {
    const target = focusChunk.value
    if (!target || !props.item || target.itemId !== props.item.id) return
    // 笔记片段在 textarea 里定位不到，只能切到对应 Tab 让用户自己看
    tab.value = target.source === 'note' ? 'note' : 'raw'
    focus.value = target.source === 'note'
      ? null
      : { text: target.text, chunkId: target.chunkId || null, hint: target.hint || '', key: Date.now() }
    focusChunk.value = null
  },
  { immediate: true }
)

function stop() {
  if (stopPolling) {
    stopPolling()
    stopPolling = null
  }
}

function organize() {
  const item = props.item
  if (!item || busy.value) return
  // 数据契约 §3：note_edited=1 时重新整理会覆盖手改内容，必须先确认
  if (item.note_edited && !window.confirm('重新整理会覆盖你手改过的笔记，并按正文重新生成标题。继续？')) return

  organizing.value = true
  api
    .organize(item.id)
    .then((res) => {
      stopPolling = pollTask(res.task_id, {
        onUpdate: (task) => {
          if (task.status === 'done') {
            stop()
            organizing.value = false
            toast.ok('整理完成')
            emit('refresh', item.id)
          } else if (task.status === 'failed') {
            stop()
            organizing.value = false
            toast.error(`这次没整理成功：${task.error_msg || task.error_code || '原因没记下来'}。点「重新整理」再试一次；还不行去任务中心看原因。`)
            emit('refresh', item.id)
          }
        },
      })
    })
    .catch((err) => {
      organizing.value = false
      toast.error(friendlyMessage(err))
      emit('refresh', item.id)
    })
}

/** 详情里的下拉：改这一条的位置。空串 = 未归类（PATCH 里 null 就是「移出工作区」） */
function onWorkspaceChange(event) {
  const value = event.target.value
  emit('move', {
    id: props.item.id,
    workspaceId: value === '' ? null : Number(value),
  })
}

function remove() {
  const item = props.item
  if (!item) return
  if (!window.confirm(`删除「${item.title}」？它的笔记片段、题目、作答记录和专注记录会一起删掉，不能恢复。`)) return
  api
    .deleteItem(item.id)
    .then(() => {
      toast.ok('已删除这条')
      emit('deleted', item.id)
    })
    .catch((err) => toast.error(friendlyMessage(err)))
}

function onNoteSaved() {
  emit('refresh', props.item.id)
}

/** 「练这条」：只接一根线 —— 练习页本来就有「从哪条材料出题」，缺的只是把当前这条带过去 */
function practiceThis() {
  router.push({ path: '/practice', query: { item: String(props.item.id) } })
}

onBeforeUnmount(() => {
  stop()
  if (ocrTimer) clearTimeout(ocrTimer)
  ocrTimer = null
})
</script>

<template>
  <section class="detail">
    <div v-if="refreshing" class="detail-refreshing" role="status" aria-label="正在更新这条内容" />
    <div v-if="loading" class="detail-loading">
      <div v-for="w in ['45%', '80%', '70%', '60%']" :key="w" class="skeleton" :style="{ width: w }" />
    </div>

    <div v-else-if="error" class="detail-state">
      <p class="state-title">详情加载失败</p>
      <p class="state-error">{{ error }}</p>
      <button class="btn btn-sm" type="button" @click="emit('refresh', item?.id)">重试</button>
    </div>

    <div v-else-if="!item" class="detail-state state">
      <template v-if="hasItems">
        <p class="state-title">这里放你的摘要、笔记和原文</p>
        <p>从左侧选一条开始读。</p>
      </template>
      <template v-else>
        <p class="state-title">这里放你的内容</p>
        <p>还没有采集过内容。</p>
        <button class="btn btn-sm" type="button" @click="emit('create')">＋ 采集内容</button>
      </template>
    </div>

    <template v-else>
      <header class="detail-head">
        <TitleEditor :item-id="item.id" :title="item.title" :disabled="busy" @saved="emit('refresh', item.id)" />
        <div class="head-actions">
          <button class="btn btn-sm" type="button" @click="startFocus">开始专注</button>
          <!-- 详情页五个页签里没有「题目」：想知道这条练过什么，此前只能自己记住标题去练习页翻。
               这根线把当前这条直接带过去，到了练习页就是它已选中。 -->
          <button
            v-if="item.status === 'ready'"
            class="btn btn-sm"
            type="button"
            @click="practiceThis"
          >练这条</button>
          <!-- 原件没读完时的出口（6-3）：缺组件给「去装」，装了给「重读」。
               原来这两条都没有，用户只能对着「整理中/待整理」干等一个不存在的进度 -->
          <button
            v-if="needsRead && item.status !== 'ready' && ocrReady === false"
            class="btn btn-sm"
            type="button"
            @click="openSettings('downloads')"
          >去装识别组件</button>
          <button
            v-else-if="needsRead && item.status !== 'ready'"
            class="btn btn-sm"
            type="button"
            :disabled="reocrBusy"
            @click="reocr"
          >{{ reocrBusy ? '正在排队…' : '重读' }}</button>
          <!-- 试卷入口（T10.3）：原件读完才有；已经是试卷的写「重新导入」，别让人以为没导过 -->
          <button v-if="canImportExam" class="btn btn-sm" type="button" @click="openExamReview">
            {{ item.kind === 'exam' ? '重新导入' : '导入试卷' }}
          </button>
          <!-- 5-3：是 PDF/图片但没读完时，按钮**出现但禁用**并说明差在哪。
               整个不渲染时，用户只会认为这个版本不支持试卷导入 -->
          <template v-else-if="examBlockedByRead">
            <button class="btn btn-sm" type="button" disabled>导入试卷</button>
            <span class="head-hint">还没读完，读完才能导入</span>
          </template>
          <!-- 试卷不整理正文（正文就是原件的占位），改题目走「重新导入」，所以这里不出现 -->
          <button
            v-if="item.kind !== 'exam'"
            class="btn btn-sm"
            type="button"
            :disabled="busy"
            :aria-busy="busy"
            @click="organize"
          >
            <progress v-if="busy" class="spin" aria-hidden="true" />
            {{ busy ? '整理中…' : isPending ? '开始整理' : '重新整理' }}
          </button>
          <!-- 删除降成幽灵按钮并隔开：原来与「整理」同权重紧挨着，点整理时手一抖就点了它 -->
          <button class="btn btn-sm btn-ghost btn-danger head-del" type="button" @click="remove">删除</button>
        </div>
      </header>

      <div class="meta">
        <StatusBadge :status="item.status" />
        <!-- 原件读字状态（6-3）：关掉采集面板后，这份 PDF 在界面上曾经「失踪」 -->
        <span
          v-if="fileState"
          class="chip chip-file"
          :class="`file-${fileState.tone}`"
        >{{ fileState.text }}</span>
        <span v-if="item.category" class="chip">{{ item.category }}</span>
        <span v-for="tag in item.tags" :key="tag" class="chip chip-tag">#{{ tag }}</span>
        <span v-if="item.note_edited" class="chip chip-edit" title="整理会覆盖手改内容">笔记已手改</span>
        <!-- 这一排都是只读标签，中间夹一个能改归属的下拉，用户会当成又一个标签。
             加一个字把它和标签区分开：「归到 未归类」读出来就知道这里能改。 -->
        <label class="ws-pick-wrap">
          <span class="ws-pick-label">归到</span>
          <select
            class="ws-pick"
            aria-label="把这条移到哪个工作区"
            :value="item.workspace_id ? String(item.workspace_id) : ''"
            @change="onWorkspaceChange"
          >
            <option value="">未归类</option>
            <option v-for="ws in workspaces" :key="ws.id" :value="String(ws.id)">{{ ws.name }}</option>
          </select>
        </label>
        <span class="time">{{ fullTime(item.created_at) }}</span>
      </div>

      <p v-if="item.truncated" class="truncated-note">原文超过 5 万字，整理时只读开头 4 万字和结尾 1 万字；原文完整保留，不受影响。</p>

      <nav class="tabs">
        <button
          v-for="entry in tabs"
          :key="entry.key"
          type="button"
          class="tab"
          :class="{ on: tab === entry.key }"
          @click="tab = entry.key"
        >
          {{ entry.label }}
        </button>
      </nav>

      <div class="detail-body">
        <SummaryPane v-show="tab === 'summary'" :item="item" />

        <div v-show="tab === 'note'" class="pane pane-note">
          <NoteEditor :key="item.id" :item-id="item.id" :note="item.structured_note || ''" @saved="onNoteSaved" />
          <!-- 导图按笔记的标题层级画，是同一份内容的另一种排版。
               折叠起来但留在同一屏：想「看结构」时不用换页签，找笔记时也不会被它抢走版面。
               v-if 挂在 details 的开关上：没展开就不发导图请求（它是现场生成的 SVG）。 -->
          <details class="mindmap-fold" @toggle="onMindmapToggle">
            <summary class="mindmap-summary">看结构（思维导图）</summary>
            <div v-if="mindmapOpen" class="mindmap-fold-body">
              <MindmapPane
                :item-id="item.id"
                :updated-at="item.updated_at || ''"
                :theme="theme"
                :mode="resolvedMode"
                @organize="organize"
              />
            </div>
          </details>
        </div>

        <!-- T9.10：原文按原件格式分派（PDF 页图、Word 版式、PPT 大纲、图片对照）；
             active 传下去，页签没打开时不发任何取页请求 -->
        <RawPane v-show="tab === 'raw'" :item="item" :focus="focus" :active="tab === 'raw'" />

        <MindmapPane
          v-if="tab === 'mindmap'"
          :item-id="item.id"
          :updated-at="item.updated_at || ''"
          :theme="theme"
          :mode="resolvedMode"
          @organize="organize"
        />

        <!-- v-if 而非 v-show：每次切进来都重新拉一次，刚结束的一轮立刻能看到 -->
        <SessionLog v-if="tab === 'sessions'" :item-id="item.id" />
      </div>
    </template>
  </section>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  padding: var(--space-4) var(--space-6) 0;
  background: var(--c-bg-0);
}

.detail-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-height: 0;
  padding-bottom: var(--space-8);
}

.detail-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-6) 0;
}

/* 后台刷新：2px 细线从左往右扫一眼，不动内容。不是进度条（拿不到真实进度），
   只说「这条正在更新」，所以不给百分比也不给文字 */
.detail-refreshing {
  flex: 0 0 auto;
  height: 2px;
  margin: 0 0 var(--space-2);
  border-radius: 1px;
  background: linear-gradient(90deg, transparent, var(--c-primary), transparent);
  background-size: 40% 100%;
  background-repeat: no-repeat;
  animation: detail-refreshing 1.1s linear infinite;
}

@keyframes detail-refreshing {
  from {
    background-position: -40% 0;
  }
  to {
    background-position: 140% 0;
  }
}

/* 减少动效时停扫，但不能让它变成一道卡在左边的脏边：
   扫光靠的是 40% 宽的渐变色块在动，停住后只会在左端留一小截。
   改成铺满整行后它是一条两端渐隐的细线，仍然读作「这里在更新」。
   非视觉用户由模板上的 role="status" 兜着，不依赖这条线。 */
@media (prefers-reduced-motion: reduce) {
  .detail-refreshing {
    animation: none;
    background-size: 100% 100%;
  }
}

.detail-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
}

.head-actions {
  display: flex;
  gap: var(--space-2);
  padding-top: 2px;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.chip {
  padding: 1px var(--space-2);
  border-radius: 999px;
  background: var(--c-bg-2);
  color: var(--c-text-2);
}

.chip-tag {
  background: transparent;
  border: 1px solid var(--c-border);
  color: var(--c-text-3);
}

.chip-edit {
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
}

/* 原件读字状态：与内容状态徽标并排，用颜色区分「还在跑 / 卡住 / 没戏」 */
.chip-file.file-ok {
  background: var(--c-success-soft);
  color: var(--c-success-ink);
}

.chip-file.file-busy {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.chip-file.file-warn {
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
}

.chip-file.file-bad {
  background: var(--c-danger-soft);
  color: var(--c-danger-ink);
}

/* 「还没读完，读完才能导入」：跟在禁用按钮后面，不抢按钮的宽 */
.head-hint {
  align-self: center;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  white-space: nowrap;
}

/* 下拉前那个「归到」：这排标签里唯一能改的东西，得让人看出来是可编辑的 */
.ws-pick-wrap {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.ws-pick {
  max-width: 140px;
  padding: 1px var(--space-1);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  color: var(--c-text-2);
  font-size: var(--fs-xs);
}

/* 删除：平时只是个淡淡的红字，与「整理」拉开一点距离，避免点整理点成删除 */
.head-del.btn-ghost {
  margin-left: var(--space-2);
  color: var(--c-danger-ink);
}

.head-del.btn-ghost:hover:not(:disabled) {
  background: var(--c-danger-soft);
}

.time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.truncated-note {
  margin: var(--space-3) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
}

.tabs {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-4);
  border-bottom: 1px solid var(--c-border);
}

.tab {
  padding: var(--space-2) 0;
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  margin-bottom: -1px;
}

.tab:hover {
  color: var(--c-text-1);
}

.tab.on {
  color: var(--c-primary-ink);
  border-bottom-color: var(--c-primary);
  font-weight: 600;
}

.pane-note {
  display: flex;
  flex-direction: column;
  /* 笔记编辑器自己滚，导图折叠块跟在它下面；整页不滚 */
  overflow: hidden;
}

/* 导图折叠块：标题行常驻，展开后在自己的框里滚，不把笔记挤出屏幕 */
.mindmap-fold {
  flex: 0 0 auto;
  border-top: 1px solid var(--c-border);
  max-height: 60%;
  overflow: auto;
}

.mindmap-summary {
  padding: var(--space-2) 0;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  cursor: pointer;
  list-style: none;
}

.mindmap-summary::-webkit-details-marker {
  display: none;
}

.mindmap-summary::before {
  content: '▸';
  margin-right: var(--space-1);
  color: var(--c-text-3);
}

.mindmap-fold[open] .mindmap-summary::before {
  content: '▾';
}

.mindmap-summary:hover {
  color: var(--c-text-1);
}

/* MindmapPane 根节点是 height:100%，在 details 里没有确定高度会塌成 0 —— 给它一个底 */
.mindmap-fold-body {
  min-height: 240px;
}

.detail-body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-bottom: var(--space-4);
}

</style>
