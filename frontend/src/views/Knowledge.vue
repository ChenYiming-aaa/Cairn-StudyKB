<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import CategoryTree from '../components/CategoryTree.vue'
import ItemDetail from '../components/ItemDetail.vue'
import ItemList from '../components/ItemList.vue'
import TodayBar from '../components/TodayBar.vue'
import { api, friendlyMessage } from '../api/client'
import { useLayout } from '../composables/useLayout'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'

const toast = useToast()
const { refreshTick, editorDirty, focusItemId, openPaste } = useUi()
// T7.2：列表收起后顶栏按钮负责叫回来；窗口 < 1000 时选完条目自动收（浮层会让出屏占）
const { collapse } = useLayout()

const PAGE_SIZE = 50

// 分类树与状态计数一律来自后端聚合（GET /api/knowledge/categories），
// 不再拿最近 N 条自己数——那样条目破百后计数就偏低（M1 已知限制已消）。
const tree = ref({ categories: [], counts: { total: 0, pending: 0, organizing: 0 } })
// T9.9：工作区是左栏最上面那段；计数用后端给的 item_count / none_count，前端不自己数
const workspaces = ref([])
const noneCount = ref(0)
const items = ref([])
const total = ref(0)

const treeLoading = ref(false)
const listLoading = ref(false)
const listError = ref('')

const selectedId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

// T7.2 空状态用：最近采集的 3 条。只在「没加筛选」的那次请求里更新，
// 这样筛到空的时候还能给出「点一条直接跳回去」的出口。
const recent = ref([])

const organizingAll = ref(false)
// T7.1：状态快筛与分类/标签是叠加关系（三个条件一起进 WHERE）
// T9.9：工作区也是叠加的一维（'' = 全部 | 'none' = 未归类 | number = 某个工作区）
const filter = reactive({ category: '', tag: '', q: '', status: '', workspace_id: '' })

let busyTimer = null
let busyTicks = 0

const categories = computed(() => tree.value.categories || [])
const counts = computed(
  () => tree.value.counts || { total: 0, pending: 0, organizing: 0 }
)
const totalItems = computed(() => tree.value.counts?.total || 0)
// D-01：详情空态要区分"没选中"与"库里没内容"。只由**无筛选**的那次请求更新，
// 否则筛到空的时候 totalItems 收窄为 0，会把"筛不到"误判成"库是空的"。
const hasAnyItem = ref(true)
const pendingCount = computed(() => tree.value.counts?.pending || 0)
const isFiltered = computed(() =>
  Boolean(filter.category || filter.tag || filter.q || filter.status || filter.workspace_id !== '')
)

async function loadTree() {
  treeLoading.value = true
  try {
    // 带上当前筛选：分类树仍是全库，但状态计数收窄到当前范围（2026-11-10）
    tree.value = await api.categories({
      category: filter.category || undefined,
      tag: filter.tag || undefined,
      workspace_id: filter.workspace_id === '' ? undefined : filter.workspace_id,
    })
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    treeLoading.value = false
  }
}

async function loadList() {
  listLoading.value = true
  listError.value = ''
  const unrefined = !(
    filter.category || filter.tag || filter.q || filter.status || filter.workspace_id !== ''
  )
  try {
    const data = await api.listItems({
      page_size: PAGE_SIZE,
      category: filter.category || undefined,
      tag: filter.tag || undefined,
      status: filter.status || undefined,
      q: filter.q || undefined,
      workspace_id: filter.workspace_id === '' ? undefined : filter.workspace_id,
    })
    items.value = data.items || []
    total.value = data.total || 0
    if (unrefined) {
      recent.value = items.value.slice(0, 3)
      hasAnyItem.value = total.value > 0
    }
  } catch (err) {
    listError.value = friendlyMessage(err)
    items.value = []
    total.value = 0
  } finally {
    listLoading.value = false
  }
}

async function loadDetail(itemId) {
  if (!itemId) {
    detail.value = null
    return
  }
  detailLoading.value = true
  detailError.value = ''
  try {
    detail.value = await api.getItem(itemId)
  } catch (err) {
    detailError.value = friendlyMessage(err)
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function scheduleIfBusy() {
  const busy =
    tree.value.counts?.organizing > 0 ||
    items.value.some((item) => item.status === 'organizing')
  if (!busy) {
    busyTicks = 0
    return
  }
  if (busyTimer || busyTicks >= 60) return
  busyTicks += 1
  busyTimer = setTimeout(() => {
    busyTimer = null
    refreshAll()
  }, 2500)
}

async function loadWorkspaces() {
  try {
    const data = await api.workspaces()
    workspaces.value = data.items || []
    noneCount.value = data.none_count || 0
  } catch (err) {
    toast.error(friendlyMessage(err))
  }
}

async function refreshAll() {
  await Promise.all([loadTree(), loadList(), loadWorkspaces()])
  if (selectedId.value) await loadDetail(selectedId.value)
  scheduleIfBusy()
}

function selectItem(itemId) {
  if (itemId === selectedId.value) return
  if (editorDirty.value && !window.confirm('当前笔记还没保存，切换后会丢失。确定要切换吗？')) {
    return
  }
  selectedId.value = itemId
  loadDetail(itemId)
  // < 1000px 时列表是浮层，选完就该让出屏占把详情露出来（M7 §3.3 第三档）
  if (window.innerWidth < 1000) collapse('list')
}

// 左栏一次操作可能连发两个事件（点「全部条目」= 清分类 + 清状态），
// 合并成一次请求，避免同一个动作打两遍列表接口
let loadQueued = false
function queueLoadList() {
  if (loadQueued) return
  loadQueued = true
  Promise.resolve().then(() => {
    loadQueued = false
    loadList()
  })
}

function onFilterSelect(payload) {
  filter.category = payload.category
  filter.tag = payload.tag
  queueLoadList()
}

function onStatus(next) {
  filter.status = next || ''
  queueLoadList()
}

function onWorkspace(key) {
  // WorkspaceBar 的「全部」只清工作区这一维；要清全部用状态区的「全部内容」
  filter.workspace_id = key
  queueLoadList()
}

function onSearch(keyword) {
  filter.q = keyword
  loadList()
}

// 分类 / 标签 / 工作区变了才需要重取计数（状态快筛不影响那三个数字）；分类树本身还是全库
watch(
  [() => filter.category, () => filter.tag, () => filter.workspace_id],
  () => loadTree()
)

async function organizePending() {
  organizingAll.value = true
  try {
    const result = await api.organizePending({
      category: filter.category || undefined,
      tag: filter.tag || undefined,
      workspace_id: filter.workspace_id === '' ? undefined : filter.workspace_id,
    })
    if (result.total) {
      toast.ok(`开始整理了，${result.total} 条排队中`)
      await refreshAll()
    } else {
      toast.info('没有待整理的内容')
    }
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    organizingAll.value = false
  }
}

/** 批量移入：列表勾选后点「移到」。逐条 PATCH —— 没有批量端点，几十条的规模不值得加一个 */
async function onMoveItems(payload) {
  const ids = payload.ids || []
  const target = payload.workspaceId === '' ? null : payload.workspaceId
  if (!ids.length) return
  try {
    await Promise.all(ids.map((id) => api.patchItem(id, { workspace_id: target })))
    toast.ok(target === null ? `已把 ${ids.length} 条移到「未归类」` : `已移入 ${ids.length} 条`)
    await refreshAll()
  } catch (err) {
    toast.error(friendlyMessage(err))
    await refreshAll()
  }
}

/** 详情里的下拉：只改这一条，不刷新整个列表（列表那条的工区标签要跟着变，所以还是刷） */
async function onMoveOne(payload) {
  try {
    await api.patchItem(payload.id, { workspace_id: payload.workspaceId })
    await refreshAll()
  } catch (err) {
    toast.error(friendlyMessage(err))
  }
}

async function onDetailRefresh(itemId) {  await refreshAll()
  if (itemId) await loadDetail(itemId)
}

function onDeleted(itemId) {
  if (selectedId.value === itemId) {
    selectedId.value = null
    detail.value = null
  }
  refreshAll()
}

watch(refreshTick, () => {
  refreshAll()
})

/** 采集完成点「去看看」：跳过来时可能还带着筛选条件，条目不在当前列表里就看不到它，
 *  所以先清筛选再选中（清完列表必然包含最新入库的那条）。 */
async function focusOnItem(itemId) {
  if (filter.category || filter.tag || filter.q || filter.status || filter.workspace_id !== '') {
    filter.category = ''
    filter.tag = ''
    filter.q = ''
    filter.status = ''
    filter.workspace_id = ''
    // 计数由上面的 watch 重取（清空筛选后回到全库口径），这里只等列表
    await loadList()
  }
  selectItem(itemId)
}

watch(focusItemId, (itemId) => {
  if (!itemId) return
  focusItemId.value = null          // 消费掉，避免重复触发
  focusOnItem(itemId)
})

onMounted(async () => {
  await refreshAll()
  // 从「任务」页跳过来时组件刚挂载，watch 注册前值就已写入，这里补一次
  if (focusItemId.value) {
    const itemId = focusItemId.value
    focusItemId.value = null
    await focusOnItem(itemId)
  }
})

onBeforeUnmount(() => {
  if (busyTimer) clearTimeout(busyTimer)
  busyTimer = null
})
</script>

<template>
  <div class="knowledge-page">
    <!-- T7.4：「仪表盘」不再占一个导航位，改成这里的一行卡片，点进完整仪表盘 -->
    <TodayBar />

    <div class="workspace">
      <CategoryTree
        :categories="categories"
        :workspaces="workspaces"
        :active-workspace="filter.workspace_id"
        :none-count="noneCount"
        :total="totalItems"
        :counts="counts"
        :active="{ category: filter.category, tag: filter.tag }"
        :status="filter.status"
        :loading="treeLoading"
        @select="onFilterSelect"
        @status="onStatus"
        @workspace="onWorkspace"
        @workspaces-changed="refreshAll"
        @ingest="openPaste"
      />

      <ItemList
        :items="items"
        :total="total"
        :loading="listLoading"
        :error="listError"
        :active-id="selectedId"
        :q="filter.q"
        :pending-count="pendingCount"
        :organizing="organizingAll"
        :filtered="isFiltered"
        :recent="recent"
        :workspaces="workspaces"
        @select="selectItem"
        @move="onMoveItems"
        @search="onSearch"
        @retry="loadList"
        @organize-pending="organizePending"
        @select-recent="focusOnItem"
        @create="openPaste"
      />

      <ItemDetail
        :item="detail"
        :loading="detailLoading"
        :error="detailError"
        :has-items="hasAnyItem"
        :workspaces="workspaces"
        @refresh="onDetailRefresh"
        @move="onMoveOne"
        @deleted="onDeleted"
        @create="openPaste"
      />
    </div>
  </div>
</template>

<style scoped>
/* 页面从「一个 .workspace」变成「今日条 + .workspace」，外壳只负责把剩余高度给 workspace */
.knowledge-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
</style>
