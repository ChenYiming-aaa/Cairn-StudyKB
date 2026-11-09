<script setup>
/**
 * 「外观」tab（M6 T6.8）。
 *
 * 主题卡自己带 `data-theme` / `data-mode`，直接把 tokens.css 里那套变量套在卡片内部，
 * 所以预览色块**不需要在 JS 里再抄一遍十六进制** —— 抄一遍就会和 tokens.css 漂移。
 * 代价是这些卡片会临时覆盖自己子树的 `--c-*`，因此卡片内不要放任何要跟随全局主题的东西。
 */
import { FONT_SIZES, MODES, THEMES, useTheme } from '../../composables/useTheme'

const { theme, mode, fontSize, resolvedMode, setTheme, setMode, setFontSize } = useTheme()
</script>

<template>
  <div class="appearance">
    <section class="block">
      <div class="block-head">
        <h4 class="block-title">配色</h4>
        <span class="block-note">{{ THEMES.length }} 套，全部按对比度硬标准算过</span>
      </div>
      <div class="theme-grid">
        <button
          v-for="item in THEMES"
          :key="item.id"
          type="button"
          class="theme-card"
          :class="{ on: theme === item.id }"
          :aria-pressed="theme === item.id"
          @click="setTheme(item.id)"
        >
          <span class="preview" :data-theme="item.id" :data-mode="resolvedMode" aria-hidden="true">
            <span class="pv-top">
              <span class="pv-dot" />
              <span class="pv-dot dim" />
            </span>
            <span class="pv-body">
              <span class="pv-line" />
              <span class="pv-line short" />
              <span class="pv-btn">Aa</span>
            </span>
          </span>
          <span class="card-meta">
            <span class="card-name">
              {{ item.name }}
              <span v-if="theme === item.id" class="tick">✓</span>
            </span>
            <span class="card-hint">{{ item.hint }}</span>
          </span>
        </button>
      </div>
    </section>

    <section class="block">
      <div class="block-head">
        <h4 class="block-title">明暗</h4>
        <span class="block-note">
          当前生效：{{ resolvedMode === 'dark' ? '深色' : '浅色' }}
        </span>
      </div>
      <div class="seg" role="radiogroup" aria-label="明暗">
        <button
          v-for="item in MODES"
          :key="item.id"
          type="button"
          role="radio"
          class="seg-btn"
          :class="{ on: mode === item.id }"
          :aria-checked="mode === item.id"
          @click="setMode(item.id)"
        >
          {{ item.name }}
        </button>
      </div>
      <p class="hint">选「跟随系统」时，系统切换深色这里会立刻跟着变，不用重开。</p>
    </section>

    <section class="block">
      <div class="block-head">
        <h4 class="block-title">字号</h4>
        <span class="block-note">只放大文字，不改版面宽度</span>
      </div>
      <div class="seg" role="radiogroup" aria-label="字号">
        <button
          v-for="item in FONT_SIZES"
          :key="item.id"
          type="button"
          role="radio"
          class="seg-btn"
          :class="{ on: fontSize === item.id }"
          :aria-checked="fontSize === item.id"
          @click="setFontSize(item.id)"
        >
          {{ item.name }}
          <span class="seg-hint">{{ item.hint }}</span>
        </button>
      </div>
      <p class="hint">
        正文与列表用同一套档位。笔记本外接大屏时调大一档，比系统缩放更不容易糊。
      </p>
    </section>
  </div>
</template>

<style scoped>
.appearance {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-2);
}

.block-title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 600;
}

.block-note {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.theme-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.theme-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
  text-align: left;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.theme-card:hover {
  border-color: var(--c-primary-border);
}

.theme-card.on {
  border-color: var(--c-primary);
  box-shadow: 0 0 0 2px var(--c-primary-soft);
}

/* 预览块用的是被点主题自己的变量 —— 它内部的 --c-* 与全局无关 */
.preview {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  height: 58px;
  padding: 6px;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-0);
}

.pv-top {
  display: flex;
  gap: 4px;
}

.pv-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--c-primary);
}

.pv-dot.dim {
  background: var(--c-bg-2);
}

.pv-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  justify-content: center;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--c-bg-1);
}

.pv-line {
  height: 3px;
  border-radius: 2px;
  background: var(--c-text-2);
  opacity: 0.55;
}

.pv-line.short {
  width: 60%;
  background: var(--c-text-3);
}

.pv-btn {
  align-self: flex-start;
  margin-top: 1px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--c-primary);
  color: var(--c-on-primary);
  font-size: 10px;
  line-height: 1.4;
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.card-name {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--fs-sm);
  color: var(--c-text-1);
}

.theme-card.on .card-name {
  font-weight: 600;
  color: var(--c-primary-ink);
}

.tick {
  color: var(--c-primary-ink);
}

.card-hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.seg {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-2);
}

.seg-btn {
  display: inline-flex;
  align-items: baseline;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3);
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--c-text-2);
  font-size: var(--fs-sm);
}

.seg-btn:hover {
  color: var(--c-text-1);
}

.seg-btn.on {
  background: var(--c-bg-1);
  color: var(--c-primary-ink);
  box-shadow: var(--shadow-sm);
  font-weight: 600;
}

.seg-hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-weight: 400;
}

.hint {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: var(--lh-body);
}
</style>
