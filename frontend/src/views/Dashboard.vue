<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage } from '../api/client'
import { humanDuration } from '../utils/format'

/**
 * 仪表盘（T5.4）。6 个区块，数字全部来自 `/api/stats/today` 与 `/api/stats/week`，
 * **前端不做任何二次统计**——口径只写在后端一处（M5 §6.6），否则页面与 SQL 迟早对不上。
 *
 * 本周专注用原生 CSS 条形图（总纲 §2 红线 5：不引图表库）。
 */
const router = useRouter()

const loading = ref(true)
const error = ref('')
const today = ref(null)
const week = ref(null)

const weekMax = computed(() =>
  Math.max(60, ...(week.value?.days || []).map((d) => d.focus_seconds))
)

const accuracyText = computed(() => {
  const value = today.value?.accuracy_today
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
})

const accuracyAllText = computed(() => {
  const value = today.value?.accuracy_all
  if (value === null || value === undefined) return '还没有作答记录'
  return `累计 ${Math.round(value * 100)}%（${today.value.attempts_all} 次作答）`
})

const categoryMax = computed(() =>
  Math.max(1, ...(today.value?.categories || []).map((c) => c.count))
)

const barHeight = (seconds) => `${Math.round((seconds / weekMax.value) * 100)}%`

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [t, w] = await Promise.all([api.statsToday(), api.statsWeek()])
    today.value = t
    week.value = w
  } catch (err) {
    error.value = friendlyMessage(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="dashboard">
    <header class="head">
      <div>
        <h1 class="page-title">仪表盘</h1>
        <p class="page-sub">今天学了多久、还剩多少没整理，一屏看完</p>
      </div>
      <button class="btn btn-sm" type="button" :disabled="loading" @click="load">刷新</button>
    </header>

    <p v-if="loading" class="note">加载中…</p>
    <p v-else-if="error" class="note error">{{ error }}</p>

    <div v-else-if="today" class="grid">
      <!-- 1 今日待整理 -->
      <button class="card link" type="button" @click="router.push('/')">
        <span class="card-label">今日待整理</span>
        <span class="card-value">{{ today.pending_items }}</span>
        <span class="card-sub">全库还有 {{ today.pending_total }} 条待整理</span>
      </button>

      <!-- 2 今日待复习 -->
      <button class="card link" type="button" @click="router.push('/review')">
        <span class="card-label">今日待复习</span>
        <span class="card-value" :class="{ hot: today.due_reviews > 0 }">{{ today.due_reviews }}</span>
        <span class="card-sub">错题本 {{ today.wrong_questions }} 题</span>
      </button>

      <!-- 3 连续学习天数 -->
      <div class="card">
        <span class="card-label">连续学习</span>
        <span class="card-value">{{ today.streak_days }}<small> 天</small></span>
        <span class="card-sub">今天还没学，不算中断</span>
      </div>

      <!-- 4 正确率 -->
      <div class="card">
        <span class="card-label">正确率（今日）</span>
        <span class="card-value">{{ accuracyText }}</span>
        <span class="card-sub">
          今日 {{ today.attempts_today }} 次作答 · {{ accuracyAllText }}
        </span>
      </div>

      <!-- 5 本周专注（条形图，跨两列） -->
      <section class="card chart-card">
        <div class="chart-head">
          <div>
            <span class="card-label">本周专注</span>
            <span class="card-value">{{ humanDuration(today.week_focus_seconds) }}</span>
          </div>
          <p class="chart-meta">
            今日 {{ humanDuration(today.focus_seconds) }} · {{ today.sessions }} 轮
            <br />
            {{ week?.start }} → {{ week?.end }}
          </p>
        </div>

        <div v-if="week" class="chart">
          <div v-for="day in week.days" :key="day.date" class="col" :class="{ today: day.is_today }">
            <span class="col-val">{{ day.focus_seconds ? Math.round(day.focus_seconds / 60) : '' }}</span>
            <div class="col-track">
              <i :style="{ height: barHeight(day.focus_seconds) }" />
            </div>
            <span class="col-label">{{ day.label }}</span>
          </div>
        </div>
        <p v-if="week && !week.sessions" class="note pad">这周还没有完成的专注，开一轮试试</p>
      </section>

      <!-- 6 分类分布 -->
      <section class="card cat-card">
        <span class="card-label">分类分布</span>
        <ul v-if="today.categories.length" class="cats">
          <li v-for="cat in today.categories" :key="cat.name" class="cat">
            <span class="cat-name" :title="cat.name">{{ cat.name }}</span>
            <span class="cat-track">
              <i :style="{ width: `${Math.round((cat.count / categoryMax) * 100)}%` }" />
            </span>
            <span class="cat-count">{{ cat.count }}</span>
          </li>
        </ul>
        <p v-else class="note">还没有分类过的内容</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-6) var(--space-8);
  background: var(--c-bg-0);
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.page-title {
  margin: 0;
  font-size: var(--fs-xl);
  color: var(--c-text-1);
}

.page-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.note {
  margin: var(--space-4) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.note.pad {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
}

.note.error {
  color: var(--c-danger-ink);
}

.grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  text-align: left;
  font: inherit;
}

.card.link {
  cursor: pointer;
}

.card.link:hover {
  border-color: var(--c-primary);
}

.card-label {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.card-value {
  font-size: 30px;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  color: var(--c-text-1);
}

.card-value.small,
.card-value small {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.card-value.hot {
  color: var(--c-primary-ink);
}

.card-sub {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.chart-card {
  grid-column: span 3;
}

.chart-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.chart-head > div {
  display: flex;
  flex-direction: column;
}

.chart-meta {
  margin: 0;
  text-align: right;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.5;
}

.chart {
  display: flex;
  align-items: flex-end;
  gap: var(--space-3);
  height: 132px;
  padding-top: var(--space-3);
}

.col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1);
  height: 100%;
}

.col-val {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.col-track {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: flex-end;
  border-radius: var(--radius-sm);
  background: var(--c-bg-2);
}

.col-track i {
  display: block;
  width: 100%;
  min-height: 2px;
  border-radius: var(--radius-sm);
  background: var(--c-primary-soft);
}

.col.today .col-track i {
  background: var(--c-primary);
}

.col.today .col-label {
  color: var(--c-primary-ink);
}

.col-label {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.cat-card {
  grid-column: span 4;
}

.cats {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: var(--space-2) 0 0;
  padding: 0;
  list-style: none;
}

.cat {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr) 36px;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
}

.cat-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--c-text-2);
}

.cat-track {
  height: 8px;
  border-radius: 4px;
  background: var(--c-bg-2);
}

.cat-track i {
  display: block;
  height: 100%;
  border-radius: 4px;
  background: var(--c-primary);
  opacity: 0.65;
}

.cat-count {
  text-align: right;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

@media (max-width: 1080px) {
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chart-card,
  .cat-card {
    grid-column: span 2;
  }
}
</style>
