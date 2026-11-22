<script setup>
defineProps({
  item: { type: Object, required: true },
})
</script>

<template>
  <div class="pane">
    <div v-if="item.status === 'pending'" class="state">
      <p class="state-title">还没有整理</p>
      <p>整理后会生成分类、摘要和笔记</p>
    </div>

    <template v-else>
      <!-- 整理中显示的是**上一版**摘要：不说一句，页面一边挂着「整理中」徽标、
           一边展示旧摘要，看起来像这次整理什么都没产出（L 组）。
           但「上一版」这句话只有在**确实有上一版**时才成立：第一次整理就是没有旧摘要的，
           那时候说「下面是上一版」等于指着一片空白说「这就是上一版」。 -->
      <p v-if="item.status === 'organizing'" class="stale">
        <template v-if="item.summary">正在重写，下面是上一版</template>
        <template v-else>正在生成摘要…</template>
      </p>
      <div class="block">
        <h2 class="block-title">摘要</h2>
        <p v-if="item.summary" class="summary">{{ item.summary }}</p>
        <!-- 整理中且还没产出：下面那句「模型这次没给摘要」会把「正在生成」说成「没给」，
             所以这里留空，交给上面那行状态话 -->
        <!-- 不要写成「（模型这次没给摘要，可以重新整理试试）」：建议就在页头的
             「重新整理」按钮上，这里只交代事实 -->
        <p v-else-if="item.status !== 'organizing'" class="summary muted">这次没给摘要</p>
      </div>
      <div class="block">
        <!-- 页签名是「摘要与要点」，这里原来叫「关键点」：同一个东西两个词。
             「要点」是文案规范术语表里的既有词（整理 = 分类/摘要/要点/笔记），以它为准 -->
        <h2 class="block-title">要点</h2>
        <ol v-if="item.key_points?.length" class="points">
          <li v-for="(point, index) in item.key_points" :key="index">{{ point }}</li>
        </ol>
        <p v-else class="muted">这次没给要点</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.block {
  margin-bottom: var(--space-6);
}

/* 区块标题与 Ask 的 .section-title 是同一档：13px / 600 / text-1。
   原先这里 12px/400/text-3 且带 0.08em 字距 —— 比它下面的 15px 宋体正文更小更淡，
   「摘要」读起来是正文的一条脚注，而不是它的名字。
   （阅读面的正文是 15px 宋体，所以这一行的角色只能是「标签」，不能是「第二级标题」） */
.block-title {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--c-text-1);
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
