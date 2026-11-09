<script setup>
import { reactive } from 'vue'

defineProps({
  // [{ name, count, tags: [{ name, count }] }]
  categories: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  active: { type: Object, default: () => ({ category: '', tag: '' }) },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['select'])

const openMap = reactive({})

function isOpen(name) {
  return openMap[name] !== false
}

function toggle(name) {
  openMap[name] = openMap[name] === false
}

function pick(category, tag) {
  if (category) openMap[category] = true
  emit('select', { category, tag })
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-head">主题分类</div>

    <nav class="tree">
      <button
        type="button"
        class="node root"
        :class="{ on: !active.category }"
        @click="pick('', '')"
      >
        <span class="label">全部条目</span>
        <span class="count">{{ total }}</span>
      </button>

      <div v-if="loading" class="tree-loading">
        <div class="skeleton" style="width: 80%" />
        <div class="skeleton" style="width: 60%" />
        <div class="skeleton" style="width: 70%" />
      </div>

      <p v-else-if="!categories.length" class="tree-empty">还没有分类<br />整理条目后自动出现</p>

      <template v-else>
        <div v-for="cat in categories" :key="cat.name" class="group">
          <button
            type="button"
            class="node"
            :class="{ on: active.category === cat.name && !active.tag }"
            @click="pick(cat.name, '')"
          >
            <span class="caret" @click.stop="toggle(cat.name)">{{ isOpen(cat.name) ? '▾' : '▸' }}</span>
            <span class="label">{{ cat.name }}</span>
            <span class="count">{{ cat.count }}</span>
          </button>

          <div v-show="isOpen(cat.name) && cat.tags.length" class="tags">
            <button
              v-for="tag in cat.tags"
              :key="tag.name"
              type="button"
              class="node tag"
              :class="{ on: active.category === cat.name && active.tag === tag.name }"
              @click="pick(cat.name, tag.name)"
            >
              <span class="label">#{{ tag.name }}</span>
              <span class="count">{{ tag.count }}</span>
            </button>
          </div>
        </div>
      </template>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  background: var(--c-bg-1);
  border-right: 1px solid var(--c-border);
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
}

.sidebar-head {
  padding: var(--space-4) var(--space-4) var(--space-2);
  font-size: var(--fs-xs);
  letter-spacing: 0.08em;
  color: var(--c-text-3);
}

.tree {
  padding: 0 var(--space-2) var(--space-6);
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.node {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  transition: background 0.12s, color 0.12s;
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

.node.root {
  margin-bottom: var(--space-2);
}

.label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.node.on .count {
  color: var(--c-primary-ink);
}

.caret {
  width: 14px;
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--c-text-3);
  user-select: none;
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

.tree-loading {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-2);
}

.tree-empty {
  margin: var(--space-4) var(--space-2);
  font-size: var(--fs-xs);
  line-height: 1.8;
  color: var(--c-text-3);
}
</style>
