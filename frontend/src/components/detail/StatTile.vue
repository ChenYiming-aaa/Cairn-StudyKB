<script setup>
/**
 * 指标块：一个数字 + 一句话说明。
 *
 * 设计约束（避免变成「KPI 大屏」）：
 * - 数字只呈现**真实存在**的数据，算不出来就给「—」并说明为什么，不编。
 * - 单位与数字必须同排不换行（`white-space: nowrap`），否则「1,240 字」会在窄容器里断成两行。
 * - 不放箭头、不放增减百分比——这类产品里没有「环比」这个概念，加了就是噪音。
 */
import Icon from '../../ui/Icon.vue'

defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  unit: { type: String, default: '' },
  hint: { type: String, default: '' },
  icon: { type: String, default: '' },
  // 只有「需要注意」时给 tone，正常态一律用中性色，避免整排彩色
  tone: { type: String, default: 'neutral' }, // neutral | warning | danger
})
</script>

<template>
  <div class="stat" :class="`is-${tone}`">
    <div class="stat-head">
      <Icon v-if="icon" :name="icon" :size="14" />
      <span class="stat-label">{{ label }}</span>
    </div>

    <p class="stat-value">
      <span class="stat-num">{{ value }}</span>
      <span v-if="unit" class="stat-unit">{{ unit }}</span>
    </p>

    <p v-if="hint" class="stat-hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-surface-1);
}

.stat-head {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--c-text-3);
}

.stat-label {
  display: block;
  font-size: var(--fs-xs);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 数字与单位固定同排：窄容器里宁可整块换行，也不能把单位单独甩到下一行 */
.stat-value {
  display: flex;
  align-items: baseline;
  gap: 3px;
  margin: 2px 0 0;
  white-space: nowrap;
}

.stat-num {
  font-size: var(--fs-xl);
  font-weight: 600;
  line-height: 1.1;
  letter-spacing: var(--ls-title);
  color: var(--c-text-1);
  font-variant-numeric: tabular-nums;
}

.stat-unit {
  font-size: var(--fs-xs);
  font-weight: 400;
  color: var(--c-text-3);
}

.stat-hint {
  margin: 2px 0 0;
  font-size: var(--fs-xs);
  line-height: 1.5;
  color: var(--c-text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat.is-warning .stat-num {
  color: var(--c-warning-ink);
}

.stat.is-danger .stat-num {
  color: var(--c-danger-ink);
}
</style>
