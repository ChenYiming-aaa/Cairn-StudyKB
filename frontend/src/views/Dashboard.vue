<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, friendlyMessage } from '../api/client'
import ContributionGraph from '../components/dashboard/ContributionGraph.vue'

/**
 * 仪表盘（T5.4）。数字全部来自 `/api/stats/today`，热力图来自
 * `/api/stats/heatmap`，**前端不做任何二次统计**——口径只写在后端一处
 * （M5 §6.6），否则页面与 SQL 迟早对不上。
 *
 * 2026-11-17：番茄钟下线，原「本周专注」条形图与服务它的 `/api/stats/week` 一并移除
 * （见 docs/dev/功能价值审计-2026-11-17.md）。剩下的每一块都还能落到能干活的地方。
 * 2026-11-27：补学习记录热力图 —— 数据本来就在 `quiz_attempt` 与 `knowledge_item`
 * 里，缺的只是聚合端点，不是「编一张图」。
 */
const router = useRouter()

const loading = ref(true)
const error = ref('')
const today = ref(null)
// null = 没取到（不等于没有记录）；热力图是补充信息，取不到不该把整页打成错误态
const heatmap = ref(null)

const accuracyText = computed(() => {
  const value = today.value?.accuracy_today
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
})

/** 今日之外的样本量：与今日次数相同时不重复报（「今日 3 次 · 累计 33%（3 次）」读着像 bug） */
const accuracyAllText = computed(() => {
  const data = today.value
  const value = data?.accuracy_all
  if (value === null || value === undefined) return '还没有作答记录'
  const at = Math.round(value * 100)
  return data.attempts_all > data.attempts_today ? `累计 ${at}%（共 ${data.attempts_all} 次）` : `累计 ${at}%`
})

const categoryMax = computed(() =>
  Math.max(1, ...(today.value?.categories || []).map((c) => c.count))
)

/** 连续天数下面那句：靠后端的 `studied_today`，不拿 `attempts_today` 猜
 *  —— 今天只整理没答题时，连续天数已把今天算进去，猜法会说「今天还没学」，两个数字当场打脸 */
const streakNote = computed(() => {
  const data = today.value
  if (!data) return ''
  if (data.studied_today) return '今天已学'
  return (data.streak_days || 0) > 0 ? '今天还没动' : '今天整理或答题就记 1 天'
})

function openCategory(name) {
  router.push({ path: '/', query: { category: name } })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    // 两块各自成败：热力图挂了只影响自己那张卡，KPI 仍然照常显示
    const [main, heat] = await Promise.allSettled([api.statsToday(), api.statsHeatmap()])
    if (main.status === 'fulfilled') today.value = main.value
    else error.value = friendlyMessage(main.reason)
    heatmap.value = heat.status === 'fulfilled' ? heat.value : null
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
        <p class="page-sub">还剩多少没整理、今天练得怎么样，一屏看完</p>
      </div>
      <button class="btn btn-sm" type="button" :disabled="loading" @click="load">刷新</button>
    </header>

    <p v-if="loading" class="note">加载中…</p>
    <p v-else-if="error" class="note error">{{ error }}</p>

    <div v-else-if="today" class="grid">
      <!-- 1 待整理·全库。主数必须与落点同口径（4-5 / 2-2）：原来写「今天新增」，
           点进去却是全库列表（卡上 3、列表 47），用户第一反应是筛选没生效。
           带筛选过去：落到未筛选的首页等于把用户又支使一遍（M1） -->
      <button class="card link" type="button" @click="router.push({ path: '/', query: { status: 'pending' } })">
        <span class="card-label">待整理·全库</span>
        <span class="card-value">{{ today.pending_total }}</span>
        <span class="card-sub">今天新增 {{ today.pending_items }} 条</span>
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
        <!-- 原来这句写死「今天还没学，不算中断」：今天已经学过也照说，用户会以为数据不对。
             按今天有没有作答分两句 -->
        <span class="card-sub">{{ streakNote }}</span>
      </div>

      <!-- 4 正确率 -->
      <div class="card">
        <span class="card-label">正确率（今日）</span>
        <span class="card-value">{{ accuracyText }}</span>
        <span class="card-sub">今日 {{ today.attempts_today }} 次作答 · {{ accuracyAllText }}</span>
      </div>

      <!-- 5 学习记录（贡献热力图）：一格一天，颜色是当天作答 + 整理的强度 -->
      <ContributionGraph :data="heatmap" />

      <!-- 6 分类分布 -->
      <section class="card cat-card">
        <span class="card-label">分类分布</span>
        <ul v-if="today.categories.length" class="cats">
          <li v-for="cat in today.categories" :key="cat.name">
            <!-- 看过分布自然会问「是哪几条」：做成按钮直接带 category 回知识库筛（沿用 M1 的老问题） -->
            <button
              class="cat"
              type="button"
              :title="`去知识库看「${cat.name}」`"
              :aria-label="`去知识库看分类 ${cat.name}，${cat.count} 条`"
              @click="openCategory(cat.name)"
            >
              <span class="cat-name">{{ cat.name }}</span>
              <span class="cat-track">
                <i :style="{ width: `${Math.round((cat.count / categoryMax) * 100)}%` }" />
              </span>
              <span class="cat-count">{{ cat.count }}</span>
            </button>
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

/* 卡的「名字」：12px 但加粗一档。原先它和卡内说明（card-sub）同为 12/400/text-3，
   一张卡里三行字只有数字在区分 —— 标签读起来像第一行说明。 */
.card-label {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--c-text-3);
}

/* 数字是这张卡唯一的内容，也是全页唯一的结论。30px/400 的汉字笔画粗细
   与上面 12px 的标签相当，卡片读起来是「标签 + 一段留白」；
   加粗到 600 才让数字成为视线落点。 */
.card-value {
  font-size: 30px;
  font-weight: 600;
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
  width: 100%;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  font: inherit;
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
}

.cat:hover,
.cat:focus-visible {
  background: var(--c-bg-2);
}

.cat:hover .cat-name {
  color: var(--c-primary-ink);
  text-decoration: underline;
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

  .cat-card {
    grid-column: span 2;
  }
}
</style>
