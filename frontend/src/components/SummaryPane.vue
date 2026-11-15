<script setup>
defineProps({
  item: { type: Object, required: true },
})
</script>

<template>
  <div class="pane">
    <div v-if="item.status === 'pending'" class="state">
      <p class="state-title">还没有整理</p>
      <p>点「开始整理」，自动生成分类、摘要和笔记。</p>
    </div>

    <template v-else>
      <!-- 整理中显示的是**上一版**摘要：不说一句，页面一边挂着「整理中」徽标、
           一边展示旧摘要，看起来像这次整理什么都没产出（L 组） -->
      <p v-if="item.status === 'organizing'" class="stale">
        正在重写，下面是上一版；整理完会自己刷新。
      </p>
      <div class="block">
        <h2 class="block-title">摘要</h2>
        <p class="summary">{{ item.summary || '（模型这次没给摘要，可以重新整理试试）' }}</p>
      </div>
      <div class="block">
        <h2 class="block-title">关键点</h2>
        <ol v-if="item.key_points?.length" class="points">
          <li v-for="(point, index) in item.key_points" :key="index">{{ point }}</li>
        </ol>
        <p v-else class="muted">（模型这次没给关键点）</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.block {
  margin-bottom: var(--space-6);
}

.block-title {
  font-size: var(--fs-xs);
  letter-spacing: 0.08em;
  color: var(--c-text-3);
  margin-bottom: var(--space-2);
}

.summary {
  margin: 0;
  max-width: 72ch;
  font-family: var(--font-reading);
  font-size: 15px;
  line-height: 1.8;
}

.points {
  margin: 0;
  max-width: 72ch;
  padding-left: var(--space-6);
  font-family: var(--font-reading);
  font-size: 15px;
  line-height: 1.8;
}

.points li {
  margin-bottom: var(--space-1);
}

.muted {
  color: var(--c-text-3);
  font-size: var(--fs-sm);
}

.stale {
  margin: 0 0 var(--space-3);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
</style>
