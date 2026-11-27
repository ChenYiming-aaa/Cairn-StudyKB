<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage, pollTask } from '../api/client'
import MindmapPane from './MindmapPane.vue'
import NoteEditor from './NoteEditor.vue'
import RawPane from './RawPane.vue'
import SummaryPane from './SummaryPane.vue'
import CompletenessList from './detail/CompletenessList.vue'
import DetailHeader from './detail/DetailHeader.vue'
import DocMinimap from './detail/DocMinimap.vue'
import InsightPanel from './detail/InsightPanel.vue'
import ProgressRing from './detail/ProgressRing.vue'
import StatTile from './detail/StatTile.vue'
import Button from '../ui/Button.vue'
import EmptyState from '../ui/EmptyState.vue'
import Skeleton from '../ui/Skeleton.vue'
import Tabs from '../ui/Tabs.vue'
import { useTheme } from '../composables/useTheme'
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

/**
 * 掌握度（按题算，后端 `/api/stats/mastery/{id}`）。
 *
 * 取不到时**整块不渲染**，不用 0% 冒充「一题都不会」——「还没出题」「没练过」
 * 「取不到」是三件不同的事，界面上不能长成同一个样子。
 * 换内容、重新整理后都重取；作答发生在练习/复习页，回到详情页时会重新挂载。
 */
const mastery = ref(null)
let masterySeq = 0

async function loadMastery() {
  const id = props.item?.id
  mastery.value = null
  if (!id) return
  const seq = ++masterySeq
  try {
    const data = await api.itemMastery(id)
    if (seq === masterySeq) mastery.value = data
  } catch {
    if (seq === masterySeq) mastery.value = null
  }
}

watch(
  () => [props.item?.id, props.item?.updated_at],
  loadMastery,
  { immediate: true }
)

const masteryPercent = computed(() => mastery.value?.mastery ?? 0)
const masteryCenter = computed(() => {
  const value = mastery.value?.mastery
  return value === null || value === undefined ? '—' : `${value}%`
})
/** 80 以上算稳，40 以下提醒还没成型；颜色只做补充，数字本身已经说清 */
const masteryTone = computed(() => {
  const value = mastery.value?.mastery
  if (value === null || value === undefined) return 'primary'
  if (value >= 80) return 'success'
  if (value >= 40) return 'primary'
  return 'warning'
})
const masteryHint = computed(() => {
  const data = mastery.value
  if (!data) return ''
  if (!data.questions) return '还没有题'
  return `${data.correct}/${data.questions} 题`
})
const masteryNote = computed(() => {
  const data = mastery.value
  if (!data) return ''
  if (!data.questions) return '去练习页出几道题，这里才有可算的掌握度。'
  if (!data.practiced) return `共 ${data.questions} 题，还没练过。`
  if (data.due) return `${data.due} 题到了该复习的时间。`
  if (data.pending) return `${data.pending} 题待人工判断，暂时不算对也不算错。`
  return '按每道题最近一次判定计入，不是按作答次数。'
})

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
function onWorkspaceChange(payload) {
  emit('move', payload)
}

/** 删除：确认框移到 DetailHeader 里（那里能写清后果），这里只负责真的删 */
function remove() {
  const item = props.item
  if (!item) return
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

/* ── 概览面板的数据 ──
 * 全部从已有字段推导，不新增接口、不编造数字：
 * key_points 可能是数组也可能是 JSON 字符串（老数据），两种都要吃得下。 */
function asList(value) {
  if (Array.isArray(value)) return value
  if (typeof value === 'string' && value.trim()) {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

const points = computed(() => asList(props.item?.key_points))
/** 字数去掉空白再算：中文原文里的换行与缩进不是内容 */
const textLength = computed(() => String(props.item?.raw_content || '').replace(/\s/g, '').length)
const noteLength = computed(() => String(props.item?.structured_note || '').replace(/\s/g, '').length)
const paragraphCount = computed(
  () => String(props.item?.raw_content || '').split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean).length
)

/** 完善度清单：判断条件全部是本地就能算出来的事实 */
const steps = computed(() => {
  const list = [
    {
      key: 'raw',
      label: '有原文',
      done: textLength.value > 0,
      hint: textLength.value ? `${textLength.value.toLocaleString()} 字 · ${paragraphCount.value} 段` : '还没有正文',
    },
    {
      key: 'organized',
      label: '已整理',
      done: props.item?.status === 'ready',
      hint: props.item?.status === 'ready' ? '摘要、要点与笔记已生成' : '整理后会生成摘要、要点和笔记',
      action: '开始整理',
    },
    {
      key: 'points',
      label: '有要点',
      done: points.value.length > 0,
      hint: points.value.length ? `${points.value.length} 条要点` : '整理时一并生成',
    },
  ]

  // 试卷没有笔记页签，清单里也不该出现「有笔记」这一步
  if (props.item?.kind !== 'exam') {
    list.push({
      key: 'note',
      label: '有笔记',
      done: noteLength.value > 0,
      hint: noteLength.value ? `${noteLength.value.toLocaleString()} 字${props.item?.note_edited ? '（已手改）' : ''}` : '写一份自己的整理，复习时更有用',
      action: noteLength.value ? '' : '去写笔记',
    })
  }

  return list
})

const doneCount = computed(() => steps.value.filter((step) => step.done).length)
const percent = computed(() =>
  steps.value.length ? Math.round((doneCount.value / steps.value.length) * 100) : 0
)

/** 清单里的动作：只做当前页面能完成的事，不跳来跳去 */
function onStepAction(key) {
  if (key === 'organized') organize()
  else if (key === 'note') tab.value = 'note'
}

/** 页签上的计数：只在真有意义的地方给，不给的地方不显示，避免一排零 */
const tabsMeta = computed(() =>
  tabs.value.map((entry) => {
    const icon = { summary: 'summary', note: 'note', raw: 'doc', mindmap: 'mindmap' }[entry.key]
    let count = 0
    if (entry.key === 'summary') count = points.value.length
    if (entry.key === 'raw') count = paragraphCount.value
    return { id: entry.key, label: entry.label, icon, count }
  })
)

onBeforeUnmount(() => {
  stop()
  if (ocrTimer) clearTimeout(ocrTimer)
  ocrTimer = null
})
</script>

<template>
  <section class="detail">
    <div v-if="refreshing" class="detail-refreshing" role="status" aria-label="正在更新这条内容" />

    <!-- 加载：骨架与真实结构同构（页头 + 面板 + 页签 + 正文），内容到达时不整块跳动 -->
    <div v-if="loading" class="detail-loading">
      <Skeleton variant="text" width="40%" height="14px" />
      <Skeleton variant="text" width="70%" height="26px" />
      <Skeleton variant="block" height="120px" />
      <div class="detail-loading-body">
        <Skeleton variant="text" width="88%" :index="1" />
        <Skeleton variant="text" width="76%" :index="2" />
        <Skeleton variant="text" width="82%" :index="3" />
        <Skeleton variant="text" width="54%" :index="4" />
      </div>
    </div>

    <div v-else-if="error" class="detail-state">
      <EmptyState icon="alert" title="详情加载失败" :description="`${error}。内容还在，重试一次通常就好。`">
        <Button icon="refresh" @click="emit('refresh', item?.id)">重试</Button>
      </EmptyState>
    </div>

    <div v-else-if="!item" class="detail-state">
      <!-- D-01：两种空态分开说，否则「库里有内容但没选中」会被说成「还没有内容」 -->
      <EmptyState
        v-if="hasItems"
        icon="inbox"
        title="这里放你的摘要、笔记和原文"
        description="从左侧选一条开始读。整理完成后，摘要、要点与思维导图都会出现在这里。"
      />
      <EmptyState
        v-else
        icon="inbox"
        title="这里放你的内容"
        description="还没有采集过内容。粘一条链接、传一个文件，或者记一段笔记，整理之后就在这里了。"
      >
        <Button variant="primary" icon="plus" @click="emit('create')">采集内容</Button>
      </EmptyState>
    </div>

    <template v-else>
      <DetailHeader
        :item="item"
        :busy="busy"
        :organizing="organizing"
        :reocr-busy="reocrBusy"
        :file-state="fileState"
        :needs-read="needsRead"
        :ocr-ready="ocrReady"
        :can-import-exam="canImportExam"
        :exam-blocked-by-read="examBlockedByRead"
        :workspaces="workspaces"
        @organize="organize"
        @remove="remove"
        @practice="practiceThis"
        @reocr="reocr"
        @install-ocr="openSettings('downloads')"
        @import-exam="openExamReview"
        @move="onWorkspaceChange"
        @title-saved="emit('refresh', item.id)"
      />

      <InsightPanel
        class="detail-insight"
        :headline="`${doneCount} / ${steps.length} 步已完成`"
        :percent="percent"
      >
        <div class="stat-grid">
          <StatTile
            label="原文"
            :value="textLength.toLocaleString()"
            unit="字"
            :hint="paragraphCount ? `${paragraphCount} 段` : '还没有正文'"
            icon="doc"
          />
          <StatTile
            label="要点"
            :value="points.length"
            unit="条"
            :hint="points.length ? '整理产出' : '整理后生成'"
            icon="summary"
          />
          <StatTile
            label="笔记"
            :value="noteLength.toLocaleString()"
            unit="字"
            :hint="item.note_edited ? '你手改过' : noteLength ? '由整理生成' : '还没写'"
            icon="note"
            :tone="item.note_edited ? 'warning' : 'neutral'"
          />
          <StatTile
            label="状态"
            :value="isPending ? '待整理' : '已整理'"
            :hint="fullTime(item.updated_at || item.created_at)"
            icon="clock"
            :tone="item.status === 'failed' ? 'danger' : 'neutral'"
          />
        </div>

        <DocMinimap :text="item.raw_content || ''" />

        <!-- 完善度：环给一个总量，清单给下一步。清单比环更能指导行动，所以两个都要 -->
        <template #side>
          <!-- 两个环回答两个问题：整理到哪一步了 / 现在到底会不会。
               混成一个环会让「整理完了」看起来像「学会了」 -->
          <div class="side-rings">
            <div class="side-ring">
              <ProgressRing
                :percent="percent"
                :center-label="`${doneCount}/${steps.length}`"
                :size="56"
                :caption="`${doneCount} / ${steps.length} 步已完成`"
              />
              <p class="side-title">完善度</p>
              <p class="side-hint">{{ doneCount }}/{{ steps.length }} 步</p>
            </div>

            <div v-if="mastery" class="side-ring">
              <ProgressRing
                :percent="masteryPercent"
                :center-label="masteryCenter"
                :size="56"
                :tone="masteryTone"
                :caption="`掌握度 ${masteryCenter}`"
              />
              <p class="side-title">掌握度</p>
              <p class="side-hint">{{ masteryHint }}</p>
            </div>
          </div>

          <p class="side-desc">
            {{ mastery ? masteryNote : (percent === 100 ? '这一步都做完了，接下来去练习或复习。' : '按顺序补齐，整理出的笔记才真正能用。') }}
          </p>

          <CompletenessList :steps="steps" :busy="busy" @action="onStepAction" />
        </template>
      </InsightPanel>

      <p v-if="item.truncated" class="truncated-note">
        原文超过 5 万字，整理时只读开头 4 万字和结尾 1 万字；原文完整保留，不受影响。
      </p>

      <Tabs v-model="tab" :tabs="tabsMeta" class="detail-tabs" />

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
  min-height: 0;
  padding-bottom: var(--space-8);
}

.detail-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) 0;
}

.detail-loading-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-4);
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

.detail-insight {
  margin-top: var(--space-4);
}

/* 四个指标块：默认 2×2，宽屏幕（≥720 的内容区）自动排成一行。
   原来写 150px 时，默认宽度下会排成 3+1——第四块单独占一行，比两行两列更散 */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-2);
}

/* 侧栏顶部：环 + 一句结论 */
/* 两个环并排：每个都自带标题与一行数字，不再共用一段说明 */
.side-rings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.side-ring {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  min-width: 0;
  text-align: center;
}

.side-title {
  margin: 0;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--c-text-1);
}

.side-hint {
  margin: 0;
  font-size: 10px;
  line-height: 1.4;
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.side-desc {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: 1.55;
  color: var(--c-text-3);
}

.truncated-note {
  flex: none;
  margin: var(--space-3) 0 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-warning-border);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
}

.detail-tabs {
  flex: none;
  margin-top: var(--space-4);
}

.detail-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
</style>
