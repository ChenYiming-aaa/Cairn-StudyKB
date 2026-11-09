<script setup>
defineProps({
  item: { type: Object, required: true },
})
</script>

<template>
  <div class="pane">
    <div v-if="item.status === 'pending'" class="state">
      <p class="state-title">还没有整理</p>
      <p>点右上角「开始整理」，模型会补上分类、摘要和笔记。</p>
    </div>

    <template v-else>
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
</style>
