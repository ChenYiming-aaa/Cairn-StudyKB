<script setup>
/** 多行输入。行数由 rows 控制，超出后内部滚动，不使用自动撑高（会挤动下面的按钮）。 */
defineProps({
  rows: { type: Number, default: 4 },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})

const model = defineModel({ type: String, default: '' })
</script>

<template>
  <textarea
    v-model="model"
    class="u-control"
    :rows="rows"
    :placeholder="placeholder"
    :disabled="disabled"
  />
</template>
