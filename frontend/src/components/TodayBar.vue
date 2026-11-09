<script setup>
/**
 * 知识库页顶部的「今日」条（T7.4）。
 *
 * 原来「仪表盘」占一个导航位，1280 宽下七项挤得很紧。收成 5 项后，
 * 这里用一行四格把最常看的数字留在首屏：待整理 / 待复习 / 连续天数 / 今日专注。
 * 点整条进完整仪表盘（`/dashboard`，路由还在，只是不再出现在导航里）。
 *
 * 数字全部来自 `/api/stats/today`，前端不做二次统计（口径只写在后端一处）。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import { humanDuration } from '../utils/format'

const router = useRouter()
const today = ref(null)

onMounted(async () => {
  try {
    today.value = await api.statsToday()
  } catch {
    // 拿不到就不显示数字：顶栏已有「未连接」，这里不再叠一条错误
    today.value = null
  }
})

const num = (value) => (value === null || value === undefined ? '—' : value)
</script>

<!-- aria-label 故意短：整条内容拼起来会把「待整理 / 待复习」写进可访问名，
     那样按名字找按钮的工具（读屏、Playwright）会先撞上这一条而不是左栏的状态筛选 -->
<template>
  <button
    class="today-bar"
    type="button"
    title="打开完整仪表盘：本周专注、正确率、分类分布"
    aria-label="今日概览，打开完整仪表盘"
    @click="router.push('/dashboard')"
  >
    <span class="today-tag">今日</span>
    <span class="cell">
      待整理 <b>{{ num(today?.pending_total) }}</b>
    </span>
    <span class="cell">
      待复习 <b :class="{ hot: (today?.due_reviews || 0) > 0 }">{{ num(today?.due_reviews) }}</b>
    </span>
    <span class="cell">
      连续 <b>{{ num(today?.streak_days) }}</b> 天
    </span>
    <span class="cell">
      专注 <b>{{ today ? humanDuration(today.focus_seconds) : '—' }}</b>
    </span>
    <span class="more">详情 →</span>
  </button>
</template>

<style scoped>
.today-bar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-6);
  width: 100%;
  height: 38px;
  padding: 0 var(--space-6);
  border: 0;
  border-bottom: 1px solid var(--c-border);
  background: var(--c-bg-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  text-align: left;
}

.today-bar:hover {
  background: var(--c-bg-2);
}

.today-bar:focus-visible {
  outline: 2px solid var(--c-primary);
  outline-offset: -2px;
}

.today-tag {
  flex: none;
  padding: 1px var(--space-2);
  border-radius: 999px;
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-size: var(--fs-xs);
}

.cell {
  flex: none;
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  color: var(--c-text-3);
}

.cell b {
  font-size: var(--fs-md);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--c-text-1);
}

.cell b.hot {
  color: var(--c-primary-ink);
}

.more {
  margin-left: auto;
  color: var(--c-text-3);
}

.today-bar:hover .more {
  color: var(--c-primary-ink);
}
</style>
