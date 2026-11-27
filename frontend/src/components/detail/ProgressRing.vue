<script setup>
/**
 * 环形进度。
 *
 * 用在「这条内容整理到哪一步了」：0/4 到 4/4。
 * 刻意不做仪表盘式的多环叠加——一个环只回答一个问题。
 *
 * 可访问性：SVG 本身给 role="img" + aria-label，环内文字对读屏隐藏，
 * 否则读屏会把「7 5 %」逐字念出来。
 */
import { computed } from 'vue'

const props = defineProps({
  percent: { type: Number, default: 0 },
  size: { type: Number, default: 64 },
  // 环中间显示什么：默认是百分比，也可给「3/4」这种
  centerLabel: { type: String, default: '' },
  caption: { type: String, default: '' },
})

const clamped = computed(() => Math.max(0, Math.min(100, Math.round(props.percent))))
const stroke = computed(() => (props.size >= 56 ? 6 : 5))
const radius = computed(() => (props.size - stroke.value) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const dash = computed(() => (circumference.value * clamped.value) / 100)
</script>

<template>
  <div class="ring-wrap">
    <svg
      class="ring"
      :width="size"
      :height="size"
      :viewBox="`0 0 ${size} ${size}`"
      role="img"
      :aria-label="`已完成 ${clamped}%${caption ? '，' + caption : ''}`"
    >
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        stroke="var(--c-bg-2)"
        :stroke-width="stroke"
      />
      <circle
        class="ring-arc"
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        stroke="var(--c-primary)"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="`${dash} ${circumference}`"
        :transform="`rotate(-90 ${size / 2} ${size / 2})`"
      />
    </svg>

    <span class="ring-center" aria-hidden="true">
      <span class="ring-value">{{ centerLabel || `${clamped}%` }}</span>
    </span>
  </div>
</template>

<style scoped>
.ring-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}

.ring-arc {
  transition: stroke-dasharray var(--dur-progress) var(--ease-out);
}

/* 中心文字绝对定位在环里：环是装饰性容器，两者尺寸互不牵连 */
.ring-center {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.ring-value {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-1);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

@media (prefers-reduced-motion: reduce) {
  .ring-arc {
    transition: none;
  }
}
</style>
