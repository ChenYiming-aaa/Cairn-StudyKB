<script setup>
/**
 * 单行输入框。外观继承 ui.css 的 .u-control，本组件只负责把 Vue 的 v-model
 * 与「可访问性属性透传」接好。
 *
 * 注意：这里**不做**任何校验。校验时机由表单决定（失焦校验、提交全量校验），
 * 输入框自己弹红框只会让用户打到第三个字就被骂。
 */
defineProps({
  type: { type: String, default: 'text' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  readonly: { type: Boolean, default: false },
  autocomplete: { type: String, default: undefined },
})

const model = defineModel({ type: [String, Number], default: '' })
</script>

<template>
  <input
    v-model="model"
    class="u-control"
    :type="type"
    :placeholder="placeholder"
    :disabled="disabled"
    :readonly="readonly"
    :autocomplete="autocomplete"
  />
</template>
