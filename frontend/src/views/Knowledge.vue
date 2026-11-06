<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import CategoryTree from '../components/CategoryTree.vue'
import ItemDetail from '../components/ItemDetail.vue'
import ItemList from '../components/ItemList.vue'
import { api, friendlyMessage } from '../api/client'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'

const toast = useToast()
const { refreshTick, editorDirty } = useUi()

const PAGE_SIZE = 50

// 分类树与状态计数一律来自后端聚合（GET /api/knowledge/categories），
// 不再拿最近 N 条自己数——那样条目破百后计数就偏低（M1 已知限制已消）。
const tree = ref({ categories: [], counts: { total: 0, pending: 0, organizing: 0 } })
const items = ref([])
const total = ref(0)

const treeLoading = ref(false)
const listLoading = ref(false)
const listError = ref('')

const selectedId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const organizingAll = ref(false)
const filter = reactive({ category: '', tag: '', q: '' })

let busyTimer = null
let busyTicks = 0

const categories = computed(() => tree.value.categories || [])
const totalItems = computed(() => tree.value.counts?.total || 0)
const pendingCount = computed(() => tree.value.counts?.pending || 0)
const isFiltered = computed(() => Boolean(filter.category || filter.tag || filter.q))

async function loadTree() {
  treeLoading.value = true
  try {
    tree.value = await api.categories()
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    treeLoading.value = false
  }
}

async function loadList() {
  listLoading.value = true
  listError.value = ''
  try {
    const data = await api.listItems({
      page_size: PAGE_SIZE,
      category: filter.category || undefined,
      tag: filter.tag || undefined,
      q: filter.q || undefined,
    })
    items.value = data.items || []
    total.value = data.total || 0
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

async function refreshAll() {
  await Promise.all([loadTree(), loadList()])
  if (selectedId.value) await loadDetail(selectedId.value)
  scheduleIfBusy()
}

function selectItem(itemId) {
  if (itemId === selectedId.value) return
  if (editorDirty.value && !window.confirm('结构化笔记有未保存的修改，切换条目会丢失，继续？')) {
    return
  }
  selectedId.value = itemId
  loadDetail(itemId)
}

function onFilterSelect(payload) {
  filter.category = payload.category
  filter.tag = payload.tag
  loadList()
}

function onSearch(keyword) {
  filter.q = keyword
  loadList()
}

async function organizePending() {
  organizingAll.value = true
  try {
    const result = await api.organizePending()
    if (result.total) {
      toast.ok(`已派发 ${result.total} 个整理任务`)
      await refreshAll()
    } else {
      toast.info('没有待处理的条目')
    }
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    organizingAll.value = false
  }
}

async function onDetailRefresh(itemId) {
  await refreshAll()
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

onMounted(refreshAll)

onBeforeUnmount(() => {
  if (busyTimer) clearTimeout(busyTimer)
  busyTimer = null
})
</script>

<template>
  <div class="workspace">
    <CategoryTree
      :categories="categories"
      :total="totalItems"
      :active="{ category: filter.category, tag: filter.tag }"
      :loading="treeLoading"
      @select="onFilterSelect"
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
      @select="selectItem"
      @search="onSearch"
      @retry="loadList"
      @organize-pending="organizePending"
    />

    <ItemDetail
      :item="detail"
      :loading="detailLoading"
      :error="detailError"
      @refresh="onDetailRefresh"
      @deleted="onDeleted"
    />
  </div>
</template>
