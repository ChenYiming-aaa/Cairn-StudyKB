<script setup>
/**
 * 列表里的一行（T9.9 从 ItemList 拆出来）。
 *
 * 为什么是「勾选框 + 按钮」两个元素而不是一个整行按钮：`<input>` 不能嵌在 `<button>` 里，
 * 浏览器会把它甩到按钮外面。所以勾选框做兄弟节点，行主体仍是按钮（键盘可聚焦、可回车打开）。
 */
import StatusBadge from '../StatusBadge.vue'
import { shortTime } from '../../utils/format'

defineProps({
  item: { type: Object, required: true },
  active: { type: Boolean, default: false },
  picked: { type: Boolean, default: false },
  // 所属工作区名字；空串 = 未归类，不显示
  wsName: { type: String, default: '' },
})
const emit = defineEmits(['select', 'toggle'])
</script>

<template>
  <li class="row-line">
    <input
      class="pick"
      type="checkbox"
      :checked="picked"
      :aria-label="`选中 ${item.title}`"
      @change="emit('toggle', item.id)"
    />
    <button
      type="button"
      class="row"
      :class="{ on: active }"
      @click="emit('select', item.id)"
    >
      <span class="row-title">{{ item.title }}</span>
      <span class="row-meta">
        <StatusBadge :status="item.status" />
        <span v-if="item.category" class="row-cat">{{ item.category }}</span>
        <span v-if="wsName" class="row-ws">{{ wsName }}</span>
        <span class="row-time">{{ shortTime(item.created_at) }}</span>
      </span>
    </button>
  </li>
</template>

<style scoped>
.row-line {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

/* 勾选框常驻但很淡：藏到悬停才出会让「批量移动」这个能力没人发现 */
.pick {
  flex: none;
  margin: 0 0 0 var(--space-2);
  opacity: 0.45;
}

.pick:checked,
.row-line:hover .pick {
  opacity: 1;
}

.row {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
}

.row:hover {
  background: var(--c-bg-0);
}

.row.on {
  background: var(--c-primary-soft);
  border-color: var(--c-primary-border);
}

.row-title {
  font-size: var(--fs-sm);
  line-height: var(--lh-title);
  color: var(--c-text-1);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.row-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.row-cat {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 80px;
}

.row-time {
  margin-left: auto;
  font-variant-numeric: tabular-nums;
}

.row-ws {
  padding: 0 var(--space-1);
  border-radius: var(--radius-sm);
  background: var(--c-bg-2);
  color: var(--c-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 72px;
}
</style>
