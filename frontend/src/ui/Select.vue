<script setup>
/**
 * 下拉选择。
 *
 * 为什么不用自建浮层：原生 <select> 在 Windows / macOS / 触屏上的行为都最稳，
 * 键盘、读屏、输入法全都免费。项目红线也不允许引整包 UI 库去拿一个改版下拉。
 * 需要搜索的下拉（如选工作区）另行实现，不要在这里加 searchable。
 */
defineProps({
  // [{ value, label }] 或 ['a', 'b']
  options: { type: Array, default: () => [] },
  placeholder: { type: String, default: '请选择' },
  disabled: { type: Boolean, default: false },
})

const model = defineModel({ type: [String, Number], default: '' })

function valueOf(opt) {
  return typeof opt === 'object' && opt !== null ? opt.value : opt
}

function labelOf(opt) {
  return typeof opt === 'object' && opt !== null ? opt.label : opt
}
</script>

<template>
  <select v-model="model" class="u-control u-select" :disabled="disabled">
    <option v-if="placeholder" value="" disabled>{{ placeholder }}</option>
    <option v-for="opt in options" :key="valueOf(opt)" :value="valueOf(opt)">
      {{ labelOf(opt) }}
    </option>
  </select>
</template>

<style scoped>
/* 原生箭头在深色主题下发灰，补一枚自己的下箭头 */
.u-select {
  appearance: none;
  padding-right: var(--space-8);
  background-image: linear-gradient(45deg, transparent 50%, currentColor 50%),
    linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position:
    right 18px center,
    right 12px center;
  background-size:
    6px 6px,
    6px 6px;
  background-repeat: no-repeat;
  cursor: pointer;
}
</style>
