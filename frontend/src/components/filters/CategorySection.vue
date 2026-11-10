<script setup>
/**
 * 分类区块（T7.1）。
 *
 * 三条规则来自 M7 §2：
 * - 一级分类**默认收起**，只露计数（40 个标签平铺就是截图里最难看的那个）
 * - 展开后最多露出 6 个标签，其余折成「更多 N 个」
 * - 分类数 > 10 时先显示 10 个，其余折成「显示全部 N 个分类」
 * 搜索时不受上面三条限制：命中就要全看见，否则等于没搜。
 *
 * **手风琴**（2026-11-10）：同时只展开一个分类，点开另一个自动收起上一个。
 * 这样「显示全部 13 个分类」之后高度也有界（13 行 + 6 个标签），
 * 下面的「常用标签」不会被挤出首屏，也避免了给左栏再加一层滚动。
 */
import { computed, reactive, ref } from 'vue'

const props = defineProps({
  // [{ name, count, tags: [{ name, count }] }]，搜索时已由容器过滤好
  categories: { type: Array, default: () => [] },
  active: { type: Object, default: () => ({ category: '', tag: '' }) },
  // 已 trim + 小写的搜索词；非空即「搜索态」
  keyword: { type: String, default: '' },
  // 过滤前的分类总数（决定「显示全部 N 个分类」里的 N）
  totalCategories: { type: Number, default: 0 },
})
const emit = defineEmits(['select'])

const CAT_LIMIT = 10
const TAG_LIMIT = 6

const open = ref(true)
const showAllCats = ref(false)
const openCats = reactive({})
const showAllTags = reactive({})

const searching = computed(() => Boolean(props.keyword))

const visibleCats = computed(() => {
  if (searching.value || showAllCats.value) return props.categories
  return props.categories.slice(0, CAT_LIMIT)
})

const hiddenCats = computed(() => Math.max(0, props.totalCategories - CAT_LIMIT))

function isOpen(name) {
  return searching.value || openCats[name] === true
}

/** 只留一个展开的分类（手风琴）：清掉别的再开这个 */
function openOnly(name) {
  for (const key of Object.keys(openCats)) openCats[key] = false
  openCats[name] = true
}

function toggleCat(name) {
  if (isOpen(name)) {
    openCats[name] = false
    return
  }
  openOnly(name)
}

function pick(name) {
  // 点分类名 = 筛选，同时也展开它（用户下一步大概率要选里面的标签）
  openOnly(name)
  emit('select', { category: name, tag: '' })
}

function pickTag(category, tag) {
  emit('select', { category, tag })
}

function visibleTags(cat) {
  if (searching.value || showAllTags[cat.name]) return cat.tags
  return cat.tags.slice(0, TAG_LIMIT)
}

function hiddenTags(cat) {
  if (searching.value || showAllTags[cat.name]) return 0
  return Math.max(0, cat.tags.length - TAG_LIMIT)
}
</script>

<template>
  <section class="section">
    <button
      type="button"
      class="section-head"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="caret" aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
      <span class="section-title">分类</span>
    </button>

    <div v-show="open" class="section-body">
      <div v-for="cat in visibleCats" :key="cat.name" class="cat">
        <div class="cat-row">
          <button
            type="button"
            class="caret-btn"
            :aria-label="isOpen(cat.name) ? `收起 ${cat.name} 的标签` : `展开 ${cat.name} 的标签`"
            :aria-expanded="isOpen(cat.name)"
            @click="toggleCat(cat.name)"
          >
            {{ isOpen(cat.name) ? '▾' : '▸' }}
          </button>
          <button
            type="button"
            class="node"
            :class="{ on: active.category === cat.name && !active.tag }"
            @click="pick(cat.name)"
          >
            <span class="label">{{ cat.name }}</span>
            <span class="count">{{ cat.count }}</span>
          </button>
        </div>

        <div v-if="isOpen(cat.name) && cat.tags.length" class="tags">
          <button
            v-for="tag in visibleTags(cat)"
            :key="tag.name"
            type="button"
            class="node tag"
            :class="{ on: active.category === cat.name && active.tag === tag.name }"
            @click="pickTag(cat.name, tag.name)"
          >
            <span class="label">#{{ tag.name }}</span>
            <span class="count">{{ tag.count }}</span>
          </button>
          <button
            v-if="hiddenTags(cat) > 0"
            type="button"
            class="more"
            @click="showAllTags[cat.name] = true"
          >
            更多 {{ hiddenTags(cat) }} 个
          </button>
        </div>
      </div>

      <button
        v-if="!searching && hiddenCats > 0 && !showAllCats"
        type="button"
        class="more-cats"
        @click="showAllCats = true"
      >
        显示全部 {{ totalCategories }} 个分类
      </button>
    </div>
  </section>
</template>

<style scoped>
.section {
  padding: var(--space-2) 0;
}

.section-head {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-1) var(--space-2);
  border: none;
  background: transparent;
  color: var(--c-text-3);
  font-size: var(--fs-xs);
  letter-spacing: 0.06em;
  text-align: left;
}

.section-head:hover {
  color: var(--c-text-2);
}

.caret {
  width: 12px;
  font-size: 10px;
}

.cat-row {
  display: flex;
  align-items: center;
}

.caret-btn {
  width: 18px;
  flex: 0 0 auto;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--c-text-3);
  font-size: 10px;
  line-height: 1;
}

.caret-btn:hover {
  color: var(--c-text-1);
}

.node {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.node:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.node.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-weight: 600;
}

.label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  color: var(--c-text-3);
}

.node.on .count {
  color: var(--c-primary-ink);
}

.tags {
  padding-left: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.node.tag {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.more,
.more-cats {
  padding: var(--space-1) var(--space-2);
  border: none;
  background: transparent;
  color: var(--c-primary-ink);
  font-size: var(--fs-xs);
  text-align: left;
}

.more {
  padding-left: var(--space-2);
}

.more:hover,
.more-cats:hover {
  text-decoration: underline;
}

.more-cats {
  width: 100%;
  margin-top: var(--space-1);
}
</style>
