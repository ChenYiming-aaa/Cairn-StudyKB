<script setup>
/**
 * 批量移入条（T9.9）：勾选若干条之后出现在列表顶部。
 *
 * 目标默认是「未归类」—— 移出去（从工作区撤回）比移进某个工作区更常用，
 * 而且它是唯一一个永远存在的目标。选完点「移到」才发请求，不做「一选就移」：
 * 误触一次就改一批内容的位置，代价太大。
 */
import { computed, ref } from 'vue'

const props = defineProps({
  count: { type: Number, default: 0 },
  // [{ id, name }]
  workspaces: { type: Array, default: () => [] },
  // 请求在飞：按钮禁用，避免重复提交（同一批移两次 = 移两格）
  busy: { type: Boolean, default: false },
  // { done, total }：逐条 PATCH 的进度，只给数字，不做进度条（条数本来就少）
  progress: { type: Object, default: null },
})
const emit = defineEmits(['move', 'cancel'])

const target = ref('')      // '' = 未归类 | 工作区 id（select 的值是字符串）

const label = computed(() => {
  if (!props.busy) return '移到'
  const done = props.progress?.done
  const total = props.progress?.total
  return done === undefined || !total ? '移到中…' : `移到中 ${done}/${total}`
})

function submit() {
  if (!props.count || props.busy) return
  emit('move', target.value === '' ? null : Number(target.value))
}
</script>

<template>
  <div class="bulk">
    <span class="bulk-count">已选 {{ count }} 条</span>
    <select v-model="target" class="input bulk-select" aria-label="移到哪个工作区" :disabled="busy">
      <option value="">未归类</option>
      <option v-for="ws in workspaces" :key="ws.id" :value="String(ws.id)">{{ ws.name }}</option>
    </select>
    <button class="btn btn-sm" type="button" :disabled="busy" @click="submit">{{ label }}</button>
    <button class="btn btn-ghost btn-sm" type="button" :disabled="busy" @click="emit('cancel')">取消</button>
  </div>
</template>

<style scoped>
.bulk {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--c-border);
  background: var(--c-bg-1);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

.bulk-count {
  flex: none;
  font-variant-numeric: tabular-nums;
}

.bulk-select {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-xs);
  padding: var(--space-1) var(--space-2);
}
</style>
