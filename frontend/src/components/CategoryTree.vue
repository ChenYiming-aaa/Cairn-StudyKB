<script setup>
/**
 * 知识库左栏（T7.0 + T7.1 重组）。
 *
 * 结构按 M7 §2：筛选框 → 状态快筛 → 分类（默认收起，>10 折叠）→ 常用标签（Top 8 chip）。
 * 三件必须守住的事：
 * - **计数口径不许改**：仍用 `GET knowledge/categories` 的返回，不在前端另算一套
 * - 标签云的全库计数由 categories[].tags[] 按名字求和（一条条目只属一个分类，求和即准确）
 * - 筛选只发事件，不改数据；搜索只过滤左栏的名字，不发检索请求
 */
import { computed, nextTick, ref } from 'vue'

import CategorySection from './filters/CategorySection.vue'
import SidebarRail from './filters/SidebarRail.vue'
import StatusFilter from './filters/StatusFilter.vue'
import TagCloud from './filters/TagCloud.vue'
import RailToggle from './RailToggle.vue'
import SidePanel from './SidePanel.vue'
import { useLayout } from '../composables/useLayout'

const props = defineProps({
  // [{ name, count, tags: [{ name, count }] }]
  categories: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  counts: { type: Object, default: () => ({ total: 0, pending: 0, organizing: 0 }) },
  active: { type: Object, default: () => ({ category: '', tag: '' }) },
  // '' | 'pending' | 'organizing'
  status: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'status', 'ingest'])

const { expand } = useLayout()

const keyword = ref('')
const catRef = ref(null)
const tagRef = ref(null)
const q = computed(() => keyword.value.trim().toLowerCase())

/** 全库标签：按名字求和后降序（同计数时按名字，和后端 ORDER BY name 的口径一致） */
const allTags = computed(() => {
  const map = new Map()
  for (const cat of props.categories || []) {
    for (const tag of cat.tags || []) {
      map.set(tag.name, (map.get(tag.name) || 0) + tag.count)
    }
  }
  return [...map.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh'))
})

/** 搜索时：分类名命中 → 保留该类全部标签；只有标签命中 → 只留命中的标签 */
const shownCategories = computed(() => {
  const list = props.categories || []
  if (!q.value) return list
  return list
    .map((cat) => {
      const nameHit = String(cat.name).toLowerCase().includes(q.value)
      const tags = nameHit
        ? cat.tags || []
        : (cat.tags || []).filter((tag) => String(tag.name).toLowerCase().includes(q.value))
      return { ...cat, tags }
    })
    .filter((cat) => String(cat.name).toLowerCase().includes(q.value) || cat.tags.length > 0)
})

const shownTags = computed(() =>
  q.value ? allTags.value.filter((tag) => tag.name.toLowerCase().includes(q.value)) : allTags.value
)

const noMatch = computed(
  () => Boolean(q.value) && !shownCategories.value.length && !shownTags.value.length
)

function onAll() {
  emit('select', { category: '', tag: '' })
  emit('status', '')
}

function onStatus(next) {
  // 再点一次已选中的状态 = 取消（回到「全部」），但保留分类/标签
  emit('status', props.status === next ? '' : next)
}

function onSelect(payload) {
  emit('select', payload)
}

// ── 窄条（rail）：点图标先展开再落到对应视图 ──────────────
function railAll() {
  expand('sidebar')
  onAll()
}

function railStatus(next) {
  expand('sidebar')
  onStatus(next)
}

function focusSection(which) {
  expand('sidebar')
  nextTick(() => {
    const el = which === 'tag' ? tagRef.value : catRef.value
    el?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  })
}
</script>

<template>
  <SidePanel target="sidebar" rail title="知识库导航">
    <div class="side-search">
      <div class="field">
        <input
          v-model="keyword"
          class="input"
          type="search"
          placeholder="筛选分类或标签"
          aria-label="筛选分类或标签"
        />
        <button
          v-if="keyword"
          class="clear"
          type="button"
          title="清空筛选"
          aria-label="清空筛选"
          @click="keyword = ''"
        >
          ×
        </button>
      </div>
    </div>

    <div class="side-scroll">
      <StatusFilter :counts="counts" :active="status" @all="onAll" @pick="onStatus" />

      <div v-if="loading && !categories.length" class="side-loading">
        <div class="skeleton" style="width: 80%" />
        <div class="skeleton" style="width: 62%" />
        <div class="skeleton" style="width: 72%" />
      </div>

      <div v-else-if="!categories.length" class="side-empty">
        <p>这里放你的条目。还没有采集过内容。</p>
        <button class="btn btn-sm" type="button" @click="emit('ingest')">采集第一条</button>
      </div>

      <p v-else-if="noMatch" class="side-empty">没有匹配的分类或标签。换个词，或清空上面的筛选。</p>

      <template v-else>
        <div ref="catRef">
          <CategorySection
            :categories="shownCategories"
            :active="active"
            :keyword="q"
            :total-categories="categories.length"
            @select="onSelect"
          />
        </div>
        <div ref="tagRef">
          <TagCloud :tags="shownTags" :active="active" :keyword="q" @select="onSelect" />
        </div>
      </template>
    </div>

    <template #rail>
      <RailToggle target="sidebar" />
      <SidebarRail
        :counts="counts"
        :status="status"
        :active="active"
        @all="railAll"
        @status="railStatus"
        @section="focusSection"
      />
    </template>
  </SidePanel>
</template>

<style scoped>
.side-search {
  position: relative;
  flex: 0 0 auto;
  padding: var(--space-3) var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--c-border);
}

.field {
  position: relative;
}

.side-search .input {
  padding-right: var(--space-6);
  font-size: var(--fs-sm);
}

.clear {
  position: absolute;
  right: var(--space-1);
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: none;
  padding: 0 var(--space-1);
  color: var(--c-text-3);
  font-size: var(--fs-md);
  line-height: 1;
}

.side-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-2) var(--space-2) var(--space-6);
}

.side-loading {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-2);
}

.side-empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-3);
  margin: var(--space-4) var(--space-2);
  font-size: var(--fs-xs);
  line-height: 1.7;
  color: var(--c-text-3);
}

.side-empty p {
  margin: 0;
}

.side-total {
  margin: var(--space-4) var(--space-2) 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
