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
  // 主题 id（paper / notes / chestnut / docs / study / teal）：导图配色跟着主题走
  theme: { type: String, default: 'paper' },
  mode: { type: String, default: 'light' },
})

const state = ref('loading') // loading | ok | error
// 失败时给一个能直接点的「开始整理」：那句话原来只提按钮名，按钮却在别的页签
const emit = defineEmits(['organize'])
// 「再试一次」靠换一下缓存戳让浏览器重新取图（后端不认这个参数，只当版本号）
const nonce = ref(0)
const src = computed(() =>
  api.mindmapUrl(
    props.itemId,
    props.theme,
    props.mode,
    `${props.updatedAt || ''}${nonce.value ? `-r${nonce.value}` : ''}`
  )
)

function retry() {
  nonce.value += 1
  state.value = 'loading'
}

watch(src, () => {
  state.value = 'loading'
})
</script>

<template>
  <div class="mindmap-pane">
    <p class="mindmap-hint">按笔记里的标题层级生成。改完笔记保存，导图会跟着更新。</p>
    <div class="mindmap-box" :class="{ loading: state === 'loading' }">
      <img
        :src="src"
        :alt="`内容 ${itemId} 的思维导图`"
        class="mindmap-img"
        @load="state = 'ok'"
        @error="state = 'error'"
      />
      <div v-if="state === 'error'" class="mindmap-error">
        <p>导图没生成出来。多半是这条还没整理（导图按笔记的标题层级画）。</p>
        <button class="btn btn-sm" type="button" @click="emit('organize')">开始整理</button>
        <button class="btn btn-sm btn-ghost" type="button" @click="retry">再试一次</button>
      </div>
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
  color: var(--c-danger-ink);
}

.mindmap-error p {
  margin-bottom: var(--space-2);
}

.mindmap-error .btn {
  margin-right: var(--space-2);
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
