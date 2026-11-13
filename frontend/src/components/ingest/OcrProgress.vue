<script setup>
import { computed } from 'vue'

/**
 * 读字进度（T9.8）：`正在识别 12/30 页` + 一条进度条。
 *
 * 为什么值得单独一个组件：版面密的 PDF 实测 15 秒/页（1500 字那种），30 页就是一局
 * 8 分钟的等待。既然不承诺秒数（见 HANDOFF 性能口径），用户能确认「还在动」的就只有这个数字，
 * 所以它不能是装饰 —— 数字必须来自后端的 `done_pages / total_pages`，不许按时间估算。
 *
 * `total === 0` 是**还不知道几页**（docx / xlsx 要读完才知道），这时不编数字，
 * 只给一条会动的条 + 「正在读取文字」。
 */
const props = defineProps({
  done: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
  /** 识别（PDF / 图片）| 读取（Word / PPT / Excel / 文本）—— 两种读法，不是一个词 */
  label: { type: String, default: '识别' },
})

const pct = computed(() => {
  if (!props.total) return 0
  return Math.min(100, Math.round((props.done / props.total) * 100))
})

const text = computed(() => (
  props.total ? `正在${props.label} ${props.done}/${props.total} 页` : `正在${props.label}文字`
))
</script>

<template>
  <div class="ocr">
    <div class="ocr-head">
      <span class="ocr-text">{{ text }}</span>
      <span v-if="total" class="ocr-pct">{{ pct }}%</span>
    </div>
    <div class="bar" :class="{ waiting: !total }">
      <i v-if="total" :style="{ width: pct + '%' }" />
      <i v-else />
    </div>
  </div>
</template>

<style scoped>
.ocr {
  margin-top: var(--space-2);
}

.ocr-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: var(--space-1);
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

.ocr-pct {
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.bar {
  height: 4px;
  border-radius: 2px;
  background: var(--c-bg-2);
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--c-primary);
  transition: width 0.3s ease;
}

/* 页数未知：条形来回滑动，表示"在动但算不出百分比" */
.bar.waiting i {
  width: 35%;
  animation: slide 1.4s ease-in-out infinite;
}

@keyframes slide {
  from {
    transform: translateX(-100%);
  }

  to {
    transform: translateX(320%);
  }
}
</style>
