<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  // {text, key}：问答来源卡片跳转时要定位的那一段（M3 T3.6），默认无
  focus: { type: Object, default: null },
})

const hitEl = ref(null)

/**
 * 在原文里找这一段的锚点。
 *
 * chunk 是 chunker 拼回来的，不是原文的**连续切片**（分段/换行会被规整），
 * 所以整段 indexOf 常常落空。按长度递减退到「够长且确实存在的前缀」为止：
 * 命中位置仍然准确，只是高亮的是前 100 多字而不是整段。
 */
function findAnchor(body, chunk) {
  const needle = (chunk || '').trim()
  if (!needle || !body) return ''
  if (body.includes(needle)) return needle
  for (const size of [240, 160, 120, 80, 48, 24, 12]) {
    const cut = needle.slice(0, size).trim()
    if (cut.length >= 8 && body.includes(cut)) return cut
  }
  return ''
}

/** 切成 前段 / 命中段 / 后段。只做纯文本切分，不拼 HTML（XSS 无入口） */
const parts = computed(() => {
  const body = props.text || ''
  const needle = findAnchor(body, props.focus?.text)
  if (!needle) return [{ text: body }]
  const at = body.indexOf(needle)
  return [
    { text: body.slice(0, at) },
    { text: needle, hit: true },
    { text: body.slice(at + needle.length) },
  ]
})

function bindHit(el) {
  hitEl.value = el || null
}

watch(
  () => props.focus,
  async () => {
    if (!props.focus) return
    await nextTick()
    hitEl.value?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }
)
</script>

<template>
  <div class="pane">
    <pre class="raw"><template v-for="(part, index) in parts" :key="index"><mark v-if="part.hit" :ref="bindHit" class="hit">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></pre>
  </div>
</template>

<style scoped>
.raw {
  margin: 0;
  max-width: 74ch;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-reading);
  font-size: 14px;
  line-height: 1.9;
  color: var(--c-text-2);
}

.hit {
  background: #fbeaa8;
  color: var(--c-text-1);
  scroll-margin: 120px;
}
</style>
