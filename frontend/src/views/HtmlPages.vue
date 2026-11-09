<script setup>
import { computed, onMounted, ref } from 'vue'

import { api, friendlyMessage } from '../api/client'
import RailToggle from '../components/RailToggle.vue'
import SidePanel from '../components/SidePanel.vue'
import { useToast } from '../composables/useToast'
import { shortTime } from '../utils/format'

/**
 * T3.10 学习页：左侧多选条目 → 填标题 → 生成 → 右侧 iframe 预览 → 下载。
 *
 * 生成是同步接口（几十毫秒），所以不用轮询任务，点完直接出图。
 * 预览走 iframe 指向 `GET /api/html/{id}`，而不是把 HTML 塞进 v-html：
 * 学习页自带 <style> 与整页结构，塞进当前文档会污染全局样式。
 * sandbox 只给 allow-same-origin（M3 §7 排障表）：不给 allow-scripts，产物里就算混进脚本也跑不起来。
 */
const PAGE_SIZE = 100
const toast = useToast()

const items = ref([])
const total = ref(0)
const loading = ref(false)
const listError = ref('')
const keyword = ref('')
const picked = ref([])          // 选中的条目 id，保持点击顺序
const title = ref('')
const generating = ref(false)

const current = ref(null)       // { id, title, size_bytes }
const previewKey = ref(0)

const historyOpen = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const historyItems = ref([])
const historyTotal = ref(0)

const pickedCount = computed(() => picked.value.length)
const canGenerate = computed(() => pickedCount.value > 0 && !generating.value)
const previewSrc = computed(() =>
  current.value ? `${api.htmlUrl(current.value.id)}?v=${previewKey.value}` : ''
)

/** 选中顺序决定章节顺序，所以这里按 picked 的顺序还原条目 */
const pickedItems = computed(() =>
  picked.value.map((id) => items.value.find((it) => it.id === id)).filter(Boolean)
)

function humanSize(bytes) {
  const n = Number(bytes) || 0
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB`
    : n >= 1024 ? `${(n / 1024).toFixed(0)} KB` : `${n} B`
}

async function loadItems() {
  loading.value = true
  listError.value = ''
  try {
    const data = await api.listItems({ page_size: PAGE_SIZE, q: keyword.value || undefined })
    items.value = data.items || []
    total.value = data.total || 0
    // 选过但已不在当前列表里的（换了关键词）留着没意义，清掉
    picked.value = picked.value.filter((id) => items.value.some((it) => it.id === id))
  } catch (err) {
    listError.value = friendlyMessage(err)
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function toggle(id) {
  const at = picked.value.indexOf(id)
  if (at >= 0) picked.value.splice(at, 1)
  else picked.value.push(id)
}

function clearPicked() {
  picked.value = []
}

async function generate() {
  if (!canGenerate.value) return
  generating.value = true
  try {
    const result = await api.htmlGenerate({
      item_ids: picked.value,
      title: title.value.trim() || undefined,
    })
    current.value = result
    previewKey.value += 1
    if (!title.value.trim()) title.value = result.title
    toast.ok(`已生成「${result.title}」，${humanSize(result.size_bytes)}`)
    loadHistory()
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    generating.value = false
  }
}

async function loadHistory() {
  historyLoading.value = true
  historyError.value = ''
  try {
    const data = await api.htmlPages({ limit: 30, offset: 0 })
    historyItems.value = data.items || []
    historyTotal.value = data.total || 0
  } catch (err) {
    historyError.value = friendlyMessage(err)
    historyItems.value = []
  } finally {
    historyLoading.value = false
  }
}

function toggleHistory() {
  historyOpen.value = !historyOpen.value
  if (historyOpen.value) loadHistory()
}

function openArtifact(entry) {
  current.value = { id: entry.id, title: entry.title, size_bytes: entry.size_bytes }
  previewKey.value += 1
  historyOpen.value = false
}

async function removeArtifact(entry) {
  try {
    await api.deleteHtml(entry.id)
    historyItems.value = historyItems.value.filter((h) => h.id !== entry.id)
    historyTotal.value = Math.max(0, historyTotal.value - 1)
    if (current.value?.id === entry.id) current.value = null
    toast.ok('已删除这份学习页')
  } catch (err) {
    toast.error(friendlyMessage(err))
  }
}

function download() {
  if (!current.value) return
  window.open(api.htmlDownloadUrl(current.value.id), '_blank')
}

function onSearch() {
  loadItems()
}

onMounted(() => {
  loadItems()
  loadHistory()
})
</script>

<template>
  <div class="html-page">
    <header class="html-head">
      <div>
        <h1 class="page-title">学习页</h1>
        <p class="page-sub">挑几个条目生成一份学习页：单个文件，断网也能打开，可以拿去分享或存档</p>
      </div>
      <div class="head-right">
        <button
          class="btn btn-sm hist-btn"
          type="button"
          :class="{ on: historyOpen }"
          @click="toggleHistory"
        >
          历史
          <span v-if="historyTotal" class="hist-count">{{ historyTotal }}</span>
        </button>
      </div>
    </header>

    <div class="html-body">
      <SidePanel target="picker" class="picker" rail title="条目选择">
        <div class="picker-body">
          <div class="picker-head">
            <div class="panel-bar">
              <span class="panel-name">条目选择</span>
              <RailToggle target="picker" />
            </div>
            <input
              v-model="keyword"
              class="input picker-search"
              type="search"
              placeholder="搜条目标题…"
              @keydown.enter="onSearch"
            />
            <div class="picker-meta">
              <span>已选 {{ pickedCount }} 条</span>
              <button v-if="pickedCount" class="link-btn" type="button" @click="clearPicked">
                清空
              </button>
            </div>
          </div>

          <ul v-if="!listError" class="picker-list">
            <li v-if="loading" class="picker-empty">加载中…</li>
            <li v-else-if="!items.length" class="picker-empty">
              还没有条目。先去知识库采集一条。
            </li>
            <template v-else>
              <li v-for="item in items" :key="item.id">
                <label class="pick-row" :class="{ on: picked.includes(item.id) }">
                  <input
                    type="checkbox"
                    :checked="picked.includes(item.id)"
                    @change="toggle(item.id)"
                  />
                  <span class="pick-title">{{ item.title }}</span>
                  <span class="pick-tag">{{ item.category || '未分类' }}</span>
                </label>
              </li>
            </template>
          </ul>
          <p v-else class="picker-empty">{{ listError }}</p>
          <p v-if="!loading && !listError && total > items.length" class="picker-more">
            仅显示前 {{ items.length }} / {{ total }} 条
          </p>
        </div>

        <template #rail>
          <RailToggle target="picker" />
          <span v-if="pickedCount" class="rail-count" :title="`已选 ${pickedCount} 条`">
            {{ pickedCount }}
          </span>
          <span class="rail-label">条目选择</span>
        </template>
      </SidePanel>

      <section class="stage">
        <div class="stage-bar">
          <input
            v-model="title"
            class="input stage-title"
            type="text"
            maxlength="40"
            placeholder="学习页标题（留空则用首个条目标题）"
          />
          <div class="stage-actions">
            <button
              v-if="current"
              class="btn btn-sm"
              type="button"
              @click="download"
            >
              下载 HTML
            </button>
            <button
              class="btn btn-primary btn-sm"
              type="button"
              :disabled="!canGenerate"
              @click="generate"
            >
              {{ generating ? '生成中…' : `生成学习页${pickedCount ? `（${pickedCount}）` : ''}` }}
            </button>
          </div>
        </div>

        <p v-if="pickedItems.length" class="picked-line">
          将按此顺序成页：{{ pickedItems.map((i) => i.title).join(' · ') }}
        </p>

        <div v-if="current" class="stage-frame-wrap">
          <div class="frame-head">
            <span class="frame-title">{{ current.title }}</span>
            <span class="frame-meta">{{ humanSize(current.size_bytes) }} · 单文件离线</span>
          </div>
          <iframe
            :key="previewKey"
            class="stage-frame"
            :src="previewSrc"
            sandbox="allow-same-origin"
            title="学习页预览"
          />
        </div>
        <div v-else class="stage-empty state">
          <p class="state-title">还没有生成</p>
          <p>在左侧勾选至少 1 个条目，填个标题，再点「生成学习页」。</p>
        </div>
      </section>
    </div>

    <!-- 历史抽屉 -->
    <aside v-if="historyOpen" class="drawer">
      <header class="drawer-head">
        <span>已生成的学习页</span>
        <button class="btn btn-sm" type="button" @click="historyOpen = false">关闭</button>
      </header>
      <p v-if="historyLoading" class="drawer-note">加载中…</p>
      <p v-else-if="historyError" class="drawer-note error">{{ historyError }}</p>
      <p v-else-if="!historyItems.length" class="drawer-note">还没有生成过学习页</p>
      <ul v-else class="drawer-list">
        <li v-for="entry in historyItems" :key="entry.id" class="drawer-item">
          <button class="drawer-main" type="button" @click="openArtifact(entry)">
            <span class="drawer-title">{{ entry.title }}</span>
            <span class="drawer-sub">
              {{ shortTime(entry.created_at) }} · {{ entry.item_count }} 条 ·
              {{ humanSize(entry.size_bytes) }}
            </span>
          </button>
          <button
            class="drawer-del"
            type="button"
            title="删除这份学习页"
            @click="removeArtifact(entry)"
          >
            ×
          </button>
        </li>
      </ul>
    </aside>
  </div>
</template>

<style scoped>
.html-page {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--space-4) var(--space-6) var(--space-4);
  background: var(--c-bg-0);
}

.html-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.page-title {
  margin: 0;
  font-size: var(--fs-xl);
  color: var(--c-text-1);
}

.page-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.head-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: none;
}

.hist-btn {
  white-space: nowrap;
}

.hist-btn.on {
  border-color: var(--c-primary);
  color: var(--c-primary-ink);
}

.hist-count {
  margin-left: var(--space-1);
  padding: 0 6px;
  border-radius: 999px;
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.html-body {
  flex: 1;
  min-height: 0;
  display: grid;
  /* T7.3：选择器接入 SidePanel，宽度归 useLayout（可拖可记），收起留 44px 窄条 */
  grid-template-columns: var(--w-picker) minmax(0, 1fr);
  gap: var(--space-4);
  margin-top: var(--space-4);
}

/* 边框与底色由 SidePanel 给，这里只管内部排列 */
.picker-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.rail-count {
  margin-top: var(--space-2);
  min-width: 20px;
  padding: 0 4px;
  border-radius: 10px;
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-size: 11px;
  line-height: 18px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}

.picker-head {
  padding: var(--space-3);
  border-bottom: 1px solid var(--c-border);
}

.picker-search {
  width: 100%;
}

.picker-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.link-btn {
  border: none;
  background: none;
  padding: 0;
  color: var(--c-primary-ink);
  font-size: var(--fs-xs);
  cursor: pointer;
}

.picker-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0;
  padding: var(--space-2);
  list-style: none;
}

.pick-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  cursor: pointer;
}

.pick-row:hover {
  background: var(--c-bg-2);
}

.pick-row.on {
  background: var(--c-primary-soft);
}

.pick-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--c-text-1);
}

.pick-tag {
  flex: none;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.picker-empty,
.picker-more {
  margin: 0;
  padding: var(--space-3);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.picker-more {
  border-top: 1px solid var(--c-border);
}

.stage {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.stage-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.stage-title {
  flex: 1;
}

.stage-actions {
  display: flex;
  gap: var(--space-2);
  flex: none;
}

.picked-line {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-frame-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  margin-top: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  overflow: hidden;
}

.frame-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--c-border);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.frame-title {
  color: var(--c-text-2);
  font-size: var(--fs-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.frame-meta {
  flex: none;
}

.stage-frame {
  flex: 1;
  min-height: 0;
  width: 100%;
  border: none;
  background: var(--c-bg-0);
}

.stage-empty {
  flex: 1;
  margin-top: var(--space-3);
  border: 1px dashed var(--c-border);
  border-radius: var(--radius-md);
}

.drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: 340px;
  display: flex;
  flex-direction: column;
  background: var(--c-bg-1);
  border-left: 1px solid var(--c-border);
  box-shadow: var(--shadow-md);
  z-index: 20;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--c-border);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.drawer-note {
  margin: 0;
  padding: var(--space-4);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.drawer-note.error {
  color: var(--c-danger);
}

.drawer-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0;
  padding: var(--space-2);
  list-style: none;
}

.drawer-item {
  display: flex;
  align-items: stretch;
  gap: var(--space-1);
  border-radius: var(--radius-sm);
}

.drawer-item:hover {
  background: var(--c-bg-2);
}

.drawer-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-2);
  border: none;
  background: none;
  text-align: left;
  cursor: pointer;
}

.drawer-title {
  font-size: var(--fs-sm);
  color: var(--c-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-sub {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.drawer-del {
  flex: none;
  width: 28px;
  border: none;
  background: none;
  color: var(--c-text-3);
  font-size: var(--fs-lg);
  cursor: pointer;
}

.drawer-del:hover {
  color: var(--c-danger);
}
</style>
