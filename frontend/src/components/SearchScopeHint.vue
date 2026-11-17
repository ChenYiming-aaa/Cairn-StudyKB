<script setup>
/**
 * 「这几个框只搜标题」提示（2026-11-17）。
 *
 * 项目里有三个「搜标题」框（内容列表 / 练习配置栏 / 学习页选择器），长得和检索页
 * 的全文搜索几乎一样，但能力差一档：它们落的是 `title LIKE`，搜不到正文里的词。
 * 用户在这些框里搜一个正文词、得到空结果，会判断「我库里没有这条」——
 * 而其实检索页能搜到。这个组件就是那句话 + 一条出路。
 *
 * 只在**输了词却一条都没有**时出现：有结果时说这句话是噪音，
 * 没输词时说这句话没有对象。
 */
defineProps({
  // 由调用方判断「现在该不该说」——三处的空态条件不一样（见各自调用点）
  show: { type: Boolean, default: false },
})

const emit = defineEmits(['open-search'])
</script>

<template>
  <p v-if="show" class="scope-hint">
    只搜标题。正文里的词，去「检索」里搜。
    <button class="scope-btn" type="button" @click="emit('open-search')">去检索</button>
  </p>
</template>

<style scoped>
.scope-hint {
  margin: var(--space-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  line-height: 1.6;
}

.scope-btn {
  margin-left: var(--space-1);
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  color: var(--c-primary-ink);
  cursor: pointer;
  text-decoration: underline;
}

.scope-btn:hover {
  text-decoration: none;
}
</style>
