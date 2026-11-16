<script setup>
/**
 * 知识库页顶部的「今日」条（T7.4）。
 *
 * 原来「仪表盘」占一个导航位，1280 宽下七项挤得很紧。收成 5 项后，
 * 这里用一行四格把最常看的数字留在首屏：待整理 / 待复习 / 连续天数 / 今日专注。
 * 点整条进完整仪表盘（`/dashboard`，路由还在，只是不再出现在导航里）。
 *
 * 数字全部来自 `/api/stats/today`，前端不做二次统计（口径只写在后端一处）。
 *
 * **数字要落到能干活的地方**（M1）：以前整条是一个按钮，点「待整理 12」只会进仪表盘，
 * 再点一次进未筛选的知识库首页 —— 数字是入口的样子，落点却不接住它。
 * 现在这两格各自是一个按钮，直接把筛选条件带过去；「详情 →」才进仪表盘。
 */
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { useToday } from '../composables/useToday'
import { humanDuration } from '../utils/format'

const router = useRouter()
// 数字是模块级单例（2-1）：采集、整理、结束专注都会叫它刷新，这里只负责渲染
const { today, loadToday } = useToday()

onMounted(loadToday)

const num = (value) => (value === null || value === undefined ? '—' : value)

function goPending() {
  router.push({ path: '/', query: { status: 'pending' } })
}

function goReview() {
  router.push('/review')
}
</script>

<!-- 可访问名一律短：按名字找按钮的工具（读屏、Playwright）不该撞上「待整理 / 待复习
     连起来一长串」这种可访问名 —— 左栏的状态筛选也叫「待整理」，两者必须能分开 -->
<template>
  <div class="today-bar">
    <span class="today-tag">今日</span>
    <button
      class="cell cell-btn"
      type="button"
      :aria-label="`待整理 ${num(today?.pending_total)} 条，全库，去筛选`"
      title="全库口径：还没整理的都在这里。点一下打开筛选"
      @click="goPending"
    >
      <!-- 这个数是**全库**。仪表盘那张卡原先写的是「今天新增」，点进去落全库列表，
           两个同名不同数；2026-11-16 起两边统一为「待整理·全库」，标签里仍写明范围 -->
      待整理·全库 <b>{{ num(today?.pending_total) }}</b>
    </button>
    <button
      class="cell cell-btn"
      type="button"
      :aria-label="`待复习 ${num(today?.due_reviews)} 题，去复习`"
      title="打开复习队列"
      @click="goReview"
    >
      待复习 <b :class="{ hot: (today?.due_reviews || 0) > 0 }">{{ num(today?.due_reviews) }}</b>
    </button>
    <span class="cell">
      连续 <b>{{ num(today?.streak_days) }}</b> 天
    </span>
    <span class="cell">
      专注 <b>{{ today ? humanDuration(today.focus_seconds) : '—' }}</b>
    </span>
    <button
      class="more"
      type="button"
      title="打开完整仪表盘：本周专注、正确率、分类分布"
      @click="router.push('/dashboard')"
    >详情 →</button>
  </div>
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
  border-bottom: 1px solid var(--c-border);
  background: var(--c-bg-1);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  text-align: left;
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

/* 两格可点：不加下划线，靠 hover 底色与文字变主色提示「这里能点」 */
.cell-btn {
  padding: 2px var(--space-2);
  margin: 0 calc(var(--space-2) * -1);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  font: inherit;
  color: var(--c-text-3);
  cursor: pointer;
}

.cell-btn:hover {
  background: var(--c-bg-2);
  color: var(--c-primary-ink);
}

.cell-btn:focus-visible,
.more:focus-visible {
  outline: 2px solid var(--c-primary);
  outline-offset: 1px;
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
  padding: 2px var(--space-2);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  font: inherit;
  color: var(--c-text-3);
  cursor: pointer;
}

.more:hover {
  background: var(--c-bg-2);
  color: var(--c-primary-ink);
}
</style>
