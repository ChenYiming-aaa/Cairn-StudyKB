<script setup>
/**
 * 表单行：标签 + 控件 + 帮助文案 + 错误文案。
 *
 * 三条硬规则（来自项目文案规范与可访问性验收）：
 * 1. 标签**常驻**，不拿占位符当标签——占位符一输入就消失，用户回头看不见自己在填什么。
 * 2. 错误贴在字段下方，不用弹窗；错误文案写「为什么 + 怎么办」，不只写「格式错误」。
 * 3. 帮助文案与错误文案共用同一条 `aria-describedby` 槽位，两者不同时出现。
 *
 * 用法：
 *   <Field label="标题" required :error="err" hint="不超过 80 字" v-slot="{ id, describedBy, invalid }">
 *     <Input :id="id" :aria-describedby="describedBy" :aria-invalid="invalid" v-model="title" />
 *   </Field>
 */
import { computed, useId } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  hint: { type: String, default: '' },
  error: { type: String, default: '' },
  required: { type: Boolean, default: false },
  // 极少数场景（如搜索框）标签只给屏幕阅读器看
  labelHidden: { type: Boolean, default: false },
})

const uid = useId()
const controlId = computed(() => `field-${uid}`)
const hintId = computed(() => `field-${uid}-hint`)
const errorId = computed(() => `field-${uid}-error`)

const invalid = computed(() => (props.error ? 'true' : undefined))
const describedBy = computed(() => {
  if (props.error) return errorId.value
  if (props.hint) return hintId.value
  return undefined
})
</script>

<template>
  <div class="u-field" :class="{ 'has-error': Boolean(error), 'is-required': required }">
    <label class="u-field-label" :class="{ 'sr-only': labelHidden }" :for="controlId">
      {{ label }}
      <span v-if="required" class="u-field-req" aria-hidden="true">*</span>
      <span v-if="required" class="sr-only">（必填）</span>
    </label>

    <slot :id="controlId" :describedBy="describedBy" :invalid="invalid" />

    <p v-if="error" :id="errorId" class="u-field-error" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="hintId" class="u-field-hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.u-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  min-width: 0;
}

.u-field-label {
  display: block;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--c-text-2);
  line-height: var(--lh-body);
}

.u-field-req {
  margin-left: 2px;
  color: var(--c-danger);
}

.u-field-hint {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--c-text-3);
}

.u-field-error {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--c-danger-ink);
  font-weight: 500;
}
</style>
