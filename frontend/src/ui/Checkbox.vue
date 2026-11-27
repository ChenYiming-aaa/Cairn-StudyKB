<script setup>
/**
 * 勾选框。
 *
 * 列表行里的勾选与「批量选择」必须可发现——藏到悬停才出现会让这个能力没人知道，
 * 所以默认就有 0.45 的常驻透明度，悬停与勾选时变实。
 *
 * 原生 input 保留：它的键盘行为、读屏语义、与 <label> 的关联都不该重写。
 * 视觉用 accent-color 对齐主题主色，不做自绘方块（自绘要重写 ~40 行状态样式，收益不抵风险）。
 */
import { useId, computed } from 'vue'

defineProps({
  label: { type: String, default: '' },
  // 只给读屏用的勾选框（列表行内），标签在别处已有
  labelHidden: { type: Boolean, default: true },
  disabled: { type: Boolean, default: false },
  // 追加到原生 input 上的类名。列表行传 `pick`，让 verify_m7 与 e2e 里
  // `.list-body .pick` 这类旧钩子仍然落在真正的 checkbox 上，而不是外层 span
  inputClass: { type: String, default: '' },
})

const model = defineModel({ type: Boolean, default: false })
const uid = useId()
const inputId = computed(() => `cb-${uid}`)
</script>

<template>
  <span class="u-checkbox">
    <input
      :id="inputId"
      v-model="model"
      type="checkbox"
      :class="['u-checkbox-input', inputClass]"
      :disabled="disabled"
      :aria-label="labelHidden && label ? label : undefined"
    />
    <!-- labelHidden 时不再渲染 <label>：input 上已有 aria-label 作可访问名称，
         多一个 sr-only 的 label 会让「选中 XX」这段文字重复出现在 DOM 里
         （按文字定位的脚本会一次匹配到两处） -->
    <label v-if="label && !labelHidden" :for="inputId" class="u-checkbox-label"> {{ label }} </label>
  </span>
</template>

<style scoped>
.u-checkbox {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}

.u-checkbox-input {
  flex: none;
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--c-primary);
  cursor: pointer;
  opacity: 0.45;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.u-checkbox:hover .u-checkbox-input,
.u-checkbox-input:checked,
.u-checkbox-input:focus-visible {
  opacity: 1;
}

.u-checkbox-input:disabled {
  cursor: not-allowed;
  opacity: 0.3;
}

.u-checkbox-label {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  cursor: pointer;
}
</style>
