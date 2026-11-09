<script setup>
/**
 * 常用标签云（T7.1）。
 *
 * 标签按**全库计数**降序（计数由容器把 categories[].tags[] 按名字求和 —— 一条条目只属于
 * 一个分类，所以求和就是准确的全库条数，不需要改接口）。
 * 默认只露 8 个、两列 chip：一个标签占一整行是截图里「40 多行」的直接原因。
 */
import { computed, ref } from 'vue'

const props = defineProps({
  // [{ name, count }]，已按计数降序排好
  tags: { type: Array, default: () => [] },
  active: { type: Object, default: () => ({ category: '', tag: '' }) },
  keyword: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const TOP = 8

const open = ref(true)
const showAll = ref(false)
const searching = computed(() => Boolean(props.keyword))

const visible = computed(() => {
  if (searching.value || showAll.value) return props.tags
  return props.tags.slice(0, TOP)
})

function pick(name) {
  // 再点一次已选中的标签 = 取消，省掉「怎么去掉筛选」这一步
  emit('select', { category: '', tag: props.active.tag === name ? '' : name })
}
</script>

<template>
  <section class="section">
    <button type="button" class="section-head" :aria-expanded="open" @click="open = !open">
      <span class="caret" aria-hidden="true">{{ open ? '▾' : '▸' }}</span>
      <span class="section-title">常用标签</span>
    </button>

    <div v-show="open" class="section-body">
      <p v-if="!tags.length" class="empty">{{ searching ? '没有匹配的标签' : '还没有标签' }}</p>

      <template v-else>
        <div class="chips">
          <button
            v-for="tag in visible"
            :key="tag.name"
            type="button"
            class="chip"
            :class="{ on: active.tag === tag.name }"
            :title="`#${tag.name} · ${tag.count} 条`"
            @click="pick(tag.name)"
          >
            <span class="name">#{{ tag.name }}</span>
            <span class="count">{{ tag.count }}</span>
          </button>
        </div>

        <button
          v-if="!searching && tags.length > TOP"
          type="button"
          class="more"
          @click="showAll = !showAll"
        >
          {{ showAll ? '收起' : `显示全部 ${tags.length} 个标签` }}
        </button>
      </template>
    </div>
  </section>
</template>

<style scoped>
.section {
  padding: var(--space-2) 0;
  border-top: 1px solid var(--c-border);
  margin-top: var(--space-2);
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

.chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-1);
  padding: var(--space-1);
}

.chip {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: 999px;
  background: var(--c-bg-0);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
  text-align: left;
}

.chip:hover {
  border-color: var(--c-primary-border);
  color: var(--c-text-1);
}

.chip.on {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-weight: 600;
}

.name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  flex: 0 0 auto;
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.chip.on .count {
  color: var(--c-primary-ink);
}

.more {
  width: 100%;
  padding: var(--space-1) var(--space-2);
  border: none;
  background: transparent;
  color: var(--c-primary-ink);
  font-size: var(--fs-xs);
  text-align: left;
}

.more:hover {
  text-decoration: underline;
}

.empty {
  margin: var(--space-1) var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
