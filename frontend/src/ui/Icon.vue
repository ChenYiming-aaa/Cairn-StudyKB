<script setup>
/**
 * 图标组件（Cairn UI v0.5）。
 *
 * 几何契约：尺寸只由 --icon-* 决定，绝不在父级用 `.menu svg` 这类选择器去量。
 * 描边属性统一在 <svg> 上声明，symbol 内部不再重复，改一处全站生效。
 *
 * 可访问性：有 label 才是「有意义的图标」（role=img + aria-label）；
 * 没给 label 一律按装饰处理（aria-hidden），旁边若已有文字就不该再被读一遍。
 */
import { computed } from 'vue'

const props = defineProps({
  name: { type: String, required: true },
  // 16 | 20 | 24，或任意数字（仅当确有必要，比如面板里的空态大图标）
  size: { type: [Number, String], default: 20 },
  // 有值 = 该图标承载语义；留空 = 纯装饰
  label: { type: String, default: '' },
})

const decorative = computed(() => !props.label)
const px = computed(() => {
  const n = Number(props.size)
  return Number.isFinite(n) ? n : 20
})
</script>

<template>
  <svg
    class="icon"
    :width="px"
    :height="px"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    :aria-hidden="decorative ? 'true' : undefined"
    :role="decorative ? undefined : 'img'"
    :aria-label="decorative ? undefined : label"
    focusable="false"
  >
    <use :href="`#i-${name}`" />
  </svg>
</template>

<style scoped>
.icon {
  display: inline-block;
  flex: none;
  vertical-align: -0.15em;
}
</style>
