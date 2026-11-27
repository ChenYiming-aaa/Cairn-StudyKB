<script setup>
/**
 * 列表里的一行（T9.9 从 ItemList 拆出来；v0.5 重做视觉）。
 *
 * 为什么是「勾选框 + 按钮」两个元素而不是一个整行按钮：`<input>` 不能嵌在 `<button>` 里，
 * 浏览器会把它甩到按钮外面。所以勾选框做兄弟节点，行主体仍是按钮（键盘可聚焦、可回车打开）。
 *
 * v0.5 的三处改动：
 * 1. 状态徽标从纯色块换成「图标 + 文字 + 色」三重表达，黑白打印也读得出状态。
 * 2. 补一行摘要（有 summary 才显示）：只有标题的列表无法判断哪条值得点进去。
 * 3. 分类与工作区加图标前缀，让「这是分类」/「这是工作区」不必靠位置猜。
 */
import { computed } from 'vue'

import Badge from '../../ui/Badge.vue'
import Checkbox from '../../ui/Checkbox.vue'
import Icon from '../../ui/Icon.vue'
import { shortTime } from '../../utils/format'
import { statusOf } from '../../utils/status'

const props = defineProps({
  item: { type: Object, required: true },
  active: { type: Boolean, default: false },
  picked: { type: Boolean, default: false },
  // 所属工作区名字；空串 = 未归类，不显示
  wsName: { type: String, default: '' },
})
const emit = defineEmits(['select', 'toggle'])

/** 摘要只取一行，超过由 CSS 裁；没有 summary 就不占位，避免留下一行空高。
    用 computed 而不是算一次：整理完成后 summary 会回来，这一行要跟着更新。 */
const excerpt = computed(() => (props.item.summary || '').trim())
</script>

<template>
  <li class="row-line" :class="{ 'is-picked': picked }">
    <Checkbox
      class="row-pick"
      input-class="pick"
      :model-value="picked"
      :label="`选中 ${item.title}`"
      @update:model-value="emit('toggle', item.id)"
    />

    <button type="button" class="row" :class="{ on: active }" @click="emit('select', item.id)">
      <span class="row-title">{{ item.title }}</span>

      <span v-if="excerpt" class="row-excerpt">{{ excerpt }}</span>

      <span class="row-meta">
        <Badge
          :tone="statusOf(item.status)[1]"
          :dot="item.status !== 'organizing'"
          :pulse="item.status === 'organizing'"
        >
          {{ statusOf(item.status)[0] }}
        </Badge>

        <span v-if="item.category" class="row-chip">
          <Icon name="tag" :size="12" />
          <span class="row-chip-text">{{ item.category }}</span>
        </span>

        <span v-if="wsName" class="row-chip">
          <Icon name="folder" :size="12" />
          <span class="row-chip-text">{{ wsName }}</span>
        </span>

        <span class="row-time">{{ shortTime(item.created_at) }}</span>
      </span>
    </button>
  </li>
</template>

<style scoped>
.row-line {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  border-radius: var(--radius-sm);
  transition: background var(--dur-fast) var(--ease-out);
}

/* 勾选区与行主体等高对齐：只在第一行文字处，不跟着多行标题往下掉 */
.row-pick {
  flex: none;
  margin: var(--space-3) 0 0 var(--space-2);
}

.row {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: var(--space-2) var(--space-3) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.row:hover {
  background: var(--c-bg-0);
}

.row:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

/* 选中态：底色 + 左侧一道 2px 主色，位置指示在任何主题下都明确 */
.row.on {
  background: var(--c-primary-soft);
  border-color: var(--c-primary-border);
}

.row-title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: var(--fs-md);
  font-weight: 500;
  line-height: var(--lh-title);
  color: var(--c-text-1);
}

.row-excerpt {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--c-text-3);
}

.row-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  min-width: 0;
}

/* 分类与工作区常是长名字：给独立的截断预算，不挤掉时间 */
.row-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-width: 0;
  max-width: 96px;
  color: var(--c-text-3);
}

.row-chip-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-time {
  margin-left: auto;
  flex: none;
  font-variant-numeric: tabular-nums;
  color: var(--c-text-3);
}

/* 勾选中的整行轻微提亮，方便批量操作时一眼看出选了哪些 */
.row-line.is-picked .row {
  background: var(--c-bg-2);
}
</style>
