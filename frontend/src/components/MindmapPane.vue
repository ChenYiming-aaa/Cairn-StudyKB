<script setup>
import { computed, ref, watch } from 'vue'

import { api } from '../api/client'

/**
 * T3.7 思维导图 Tab。
 *
 * 图由后端现场生成（ADR-017/019），前端只负责把它显示出来：
 * 用 `<img src>` 而不是注入 innerHTML——SVG 是后端产出，没必要为它开一条 HTML 注入通道。
 * `updatedAt` 只用来做缓存戳：笔记保存后条目 updated_at 会变，src 一变浏览器就重新取图，
 * 「改完标题切回导图立刻变」这条 DoD 就靠它，不需要额外的刷新逻辑。
 */
const props = defineProps({
  itemId: { type: Number, required: true },
  updatedAt: { type: String, default: '' },
  theme: { type: String, default: 'light' },
})

const state = ref('loading') // loading | ok | error
const src = computed(() => api.mindmapUrl(props.itemId, props.theme, props.updatedAt))

watch(src, () => {
  state.value = 'loading'
})
</script>

<template>
  <div class="mindmap-pane">
    <p class="mindmap-hint">由「结构化笔记」的标题层级生成，改完笔记保存后自动更新（不缓存）</p>
    <div class="mindmap-box" :class="{ loading: state === 'loading' }">
      <img
        :src="src"
        :alt="`条目 ${itemId} 的思维导图`"
        class="mindmap-img"
        @load="state = 'ok'"
        @error="state = 'error'"
      />
      <p v-if="state === 'error'" class="mindmap-error">导图生成失败，请确认后端在运行后重试</p>
    </div>
  </div>
</template>

<style scoped>
.mindmap-pane {
  height: 100%;
  overflow: auto;
  padding-top: var(--space-3);
}

.mindmap-hint {
  margin: 0 0 var(--space-3);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.mindmap-box {
  display: inline-block;
  min-width: 160px;
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
}

.mindmap-box.loading {
  min-height: 120px;
  background: linear-gradient(90deg, var(--c-bg-1), var(--c-bg-2), var(--c-bg-1));
  background-size: 200% 100%;
  animation: shimmer 1.2s ease-in-out infinite;
}

.mindmap-img {
  display: block;
  max-width: 100%;
  height: auto;
}

.mindmap-error {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--c-danger);
}

@keyframes shimmer {
  from {
    background-position: 0 0;
  }
  to {
    background-position: -200% 0;
  }
}
</style>
