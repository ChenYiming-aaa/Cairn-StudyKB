<script setup>
/**
 * 学习记录（贡献热力图）。
 *
 * 借鉴 GitHub 个人页那张贡献图：横轴是周、纵轴是星期、颜色深浅是当天强度。
 * 这里只负责**排版**：日期、强度、总量全部由 `/api/stats/heatmap` 给，
 * 前端不补日期、不重算强度 —— 否则「图上一格」和「仪表盘说今天学过」会各说各的。
 *
 * 三条取舍：
 * 1. **一定有格子**。没有记录时也画出来，配一句「答一次题就会亮一格」；
 *    空图比一句「暂无数据」更能说明这里本来该有什么。
 * 2. **不做 hover 卡片**。原生 `title` 足够，颜色是主题色系深浅，
 *    悬浮层会把这张静态图变成又一个要维护的浮层。
 * 3. **读屏只读一句总结**。三百多个格子逐个可聚焦是灾难，
 *    格子给 `aria-hidden`，容器用 `role="img"` + 一句总量。
 */
import { computed } from 'vue'

const props = defineProps({
  // `/api/stats/heatmap` 的响应；null = 没取到（不等于没有记录）
  data: { type: Object, default: null },
})

// 列宽 = 格子 12px + 间距 4px；CSS 里的 12/4 必须与这里一起改
const COL = 16

function parts(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  // 用本地 Date 只为算星期，不参与任何时间比较
  return { m, d, weekday: (new Date(y, m - 1, d).getDay() + 6) % 7 }
}

const cells = computed(() => props.data?.cells || [])
const empty = computed(() => !props.data || props.data.total === 0)

/** 补头补尾成整周：第一列从周一开始，最后一列补齐 7 格（空格不可见） */
const weeks = computed(() => {
  if (!cells.value.length) return []
  const flat = [...Array(parts(cells.value[0].date).weekday).fill(null), ...cells.value]
  while (flat.length % 7) flat.push(null)
  const out = []
  for (let i = 0; i < flat.length; i += 7) out.push(flat.slice(i, i + 7))
  return out
})

const flatCells = computed(() => weeks.value.flat())

/** 月份标签放在「这个月第一次出现」的那一列，和 GitHub 一样 */
const months = computed(() => {
  const out = []
  let last = -1
  weeks.value.forEach((week, index) => {
    const cell = week.find(Boolean)
    if (!cell) return
    const { m } = parts(cell.date)
    if (m !== last) {
      out.push({ index, label: `${m} 月` })
      last = m
    }
  })
  return out
})

const rangeLabel = computed(() =>
  (props.data?.days || 0) >= 360 ? '一年' : `${props.data?.days || 0} 天`
)

const summary = computed(() => {
  if (!props.data) return '学习记录没加载出来'
  if (!props.data.total) return `过去${rangeLabel.value}还没有记录`
  return `过去${rangeLabel.value}共 ${props.data.total} 次作答或整理，${props.data.active_days} 天有记录`
})

/**
 * 强度分四档，按**绝对次数**分，不按窗口内的最大值归一化。
 *
 * 归一化听着聪明，实际会把「一天 29 次、另一天 1 次」里的 1 次压成看不见，
 * 而那一天同样是真的学了。1 次就亮，6 次以上最深，和 GitHub 一样是固定尺子。
 */
function levelOf(count) {
  if (!count) return 0
  if (count === 1) return 1
  if (count <= 3) return 2
  if (count <= 5) return 3
  return 4
}

function tooltip(cell) {
  const { m, d } = parts(cell.date)
  const bits = []
  if (cell.attempts) bits.push(`${cell.attempts} 次作答`)
  if (cell.organized) bits.push(`整理 ${cell.organized} 篇`)
  return `${m} 月 ${d} 日 · ${bits.length ? bits.join('，') : '没有记录'}`
}
</script>

<template>
  <section class="heat-card">
    <header class="heat-head">
      <div class="heat-head-text">
        <span class="heat-title">学习记录</span>
        <span class="heat-sum">{{ summary }}</span>
      </div>
      <!-- 图例贴右上，和 GitHub 一样；放页脚会孤零零地漂在卡片右侧 -->
      <span v-if="data" class="heat-legend" aria-hidden="true">
        <span>少</span>
        <i class="heat-cell l0" /><i class="heat-cell l1" /><i class="heat-cell l2" />
        <i class="heat-cell l3" /><i class="heat-cell l4" />
        <span>多</span>
      </span>
    </header>

    <p v-if="!data" class="heat-note">学习记录没加载出来，点右上角「刷新」再试。</p>

    <template v-else>
      <div class="heat-scroll">
        <div class="heat-months" :style="{ width: `${Math.max(0, weeks.length * COL - 4)}px` }">
          <span
            v-for="month in months"
            :key="month.index"
            class="heat-month"
            :style="{ left: `${month.index * COL}px` }"
          >
            {{ month.label }}
          </span>
        </div>

        <div class="heat-body">
          <div class="heat-weekdays" aria-hidden="true">
            <span>一</span><span /><span>三</span><span /><span>五</span><span /><span />
          </div>
          <div class="heat-grid" role="img" :aria-label="summary">
            <span
              v-for="(cell, index) in flatCells"
              :key="index"
              class="heat-cell"
              :class="cell ? `l${levelOf(cell.count)}` : 'is-pad'"
              :title="cell ? tooltip(cell) : ''"
              aria-hidden="true"
            />
          </div>
        </div>
      </div>

      <footer class="heat-foot">
        <span v-if="empty" class="heat-note">还没有记录。答一次题，或把一篇整理好，这里就会亮一格。</span>
        <span v-else class="heat-note">颜色越深，那天作答或整理得越多</span>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.heat-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  grid-column: 1 / -1;
  padding: var(--space-4);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
}

.heat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.heat-head-text {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  flex-wrap: wrap;
  min-width: 0;
}

.heat-title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-1);
}

.heat-sum {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

/* 窄窗只横向滚动这一块，不把整个仪表盘撑出滚动条 */
.heat-scroll {
  overflow-x: auto;
  padding-bottom: 2px;
}

.heat-months {
  position: relative;
  height: 15px;
  margin-left: 22px;
}

.heat-month {
  position: absolute;
  top: 0;
  font-size: 10px;
  line-height: 1;
  color: var(--c-text-3);
  white-space: nowrap;
}

.heat-body {
  display: flex;
  gap: 4px;
}

.heat-weekdays {
  display: grid;
  grid-template-rows: repeat(7, 12px);
  gap: 4px;
  width: 18px;
  font-size: 10px;
  line-height: 12px;
  color: var(--c-text-3);
}

.heat-grid {
  display: grid;
  grid-auto-flow: column;
  grid-template-rows: repeat(7, 12px);
  gap: 4px;
}

.heat-cell {
  display: block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  background: var(--c-bg-2);
}

/* 强度用「主题色混进卡片底色」而不是 opacity：opacity 会把悬停描边一起变淡 */
.heat-cell.l1 {
  background: color-mix(in srgb, var(--c-primary) 30%, var(--c-bg-1));
}

.heat-cell.l2 {
  background: color-mix(in srgb, var(--c-primary) 52%, var(--c-bg-1));
}

.heat-cell.l3 {
  background: color-mix(in srgb, var(--c-primary) 74%, var(--c-bg-1));
}

.heat-cell.l4 {
  background: var(--c-primary);
}

.heat-cell.is-pad {
  visibility: hidden;
}

.heat-grid .heat-cell:hover {
  outline: 1px solid var(--c-text-3);
  outline-offset: 1px;
}

.heat-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.heat-note {
  margin: 0;
  font-size: var(--fs-xs);
  line-height: var(--lh-body);
  color: var(--c-text-3);
}

.heat-legend {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--c-text-3);
}

.heat-legend span:first-child {
  margin-right: 2px;
}

.heat-legend span:last-child {
  margin-left: 2px;
}
</style>
