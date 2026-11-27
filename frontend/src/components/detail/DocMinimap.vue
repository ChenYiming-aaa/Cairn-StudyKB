<script setup>
/**
 * 原文概览条（Document minimap）。
 *
 * 把整篇原文按段落折成一排竖条，条高=该段字数。长文里一眼就能看出：
 * 哪里是大段论述、哪里是零散要点、前后篇幅是否失衡。
 *
 * 为什么用开方而不用线性高度：一篇长文里常有一两段特别长，线性缩放会把其余
 * 几十段压成贴地的一条线，什么也看不出来。开方后短段仍可见、长段仍突出。
 *
 * 数据来源：只用 item.raw_content，不依赖任何新接口。原文为空就整块不渲染。
 */
import { computed } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  // 最多画多少根条。超了就按段落数等分归并，保证宽度稳定不抖动
  maxBars: { type: Number, default: 48 },
  height: { type: Number, default: 34 },
})

const paragraphs = computed(() =>
  String(props.text || '')
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
)

/** 归并到 maxBars 以内：每桶取该桶的字数总和 */
const bars = computed(() => {
  const list = paragraphs.value
  if (!list.length) return []

  const sizes = list.map((p) => p.length)
  const limit = Math.max(1, props.maxBars)
  if (sizes.length <= limit) return sizes

  const bucket = Math.ceil(sizes.length / limit)
  const out = []
  for (let i = 0; i < sizes.length; i += bucket) {
    out.push(sizes.slice(i, i + bucket).reduce((sum, n) => sum + n, 0))
  }
  return out
})

const peak = computed(() => bars.value.reduce((max, n) => Math.max(max, n), 0))
const totalChars = computed(() => paragraphs.value.reduce((sum, p) => sum + p.length, 0))
const longest = computed(() => bars.value.reduce((max, n) => Math.max(max, n), 0))

function barHeight(value) {
  if (!peak.value) return 8
  // 开方压缩：最低也留 8%，否则短段落会彻底消失
  const ratio = Math.sqrt(value) / Math.sqrt(peak.value)
  return Math.max(8, Math.round(ratio * 100))
}

const summary = computed(() =>
  paragraphs.value.length
    ? `原文概览：共 ${paragraphs.value.length} 段、${totalChars.value} 字，最长一段 ${longest.value} 字`
    : '原文概览：原文为空'
)
</script>

<template>
  <!-- 只有一段时不画：一根占满宽度的条读起来像进度条，而且「1 段」与上面的指标块重复 -->
  <div v-if="paragraphs.length > 1" class="minimap">
    <div class="minimap-head">
      <span class="minimap-label">原文概览</span>
      <span class="minimap-meta">{{ paragraphs.length }} 段 · {{ totalChars.toLocaleString() }} 字</span>
    </div>

    <div class="minimap-bars" :style="{ height: `${height}px` }" role="img" :aria-label="summary">
      <span
        v-for="(value, index) in bars"
        :key="index"
        class="minimap-bar"
        :style="{ height: `${barHeight(value)}%` }"
        :title="`第 ${index + 1} 段 · ${value} 字`"
      />
    </div>
  </div>
</template>

<style scoped>
.minimap {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-width: 0;
}

.minimap-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
}

.minimap-label {
  font-size: var(--fs-xs);
  font-weight: 500;
  color: var(--c-text-2);
  white-space: nowrap;
}

.minimap-meta {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.minimap-bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  width: 100%;
  padding-bottom: 1px;
  border-bottom: 1px solid var(--c-border);
}

.minimap-bar {
  flex: 1 1 0;
  min-width: 2px;
  border-radius: 2px 2px 0 0;
  background: var(--c-primary);
  opacity: 0.35;
  transition: opacity var(--dur-fast) var(--ease-out);
}

.minimap-bars:hover .minimap-bar {
  opacity: 0.55;
}

.minimap-bar:hover {
  opacity: 1;
}

@media (prefers-reduced-motion: reduce) {
  .minimap-bar {
    transition: none;
  }
}
</style>
