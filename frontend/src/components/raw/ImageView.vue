<script setup>
/**
 * 图片原文（T9.10）：**左原图、右识别文字**，同一屏对照。
 *
 * 为什么要并排：图片这条路必然带错字（手写、拍照、公式），不能对照就只能
 * 盲信识别结果。并排一眼看出哪句不对，这是"认错也看得出来"的最短路径。
 *
 * 原图地址走 `fileUrl`（原格式：png/webp 按自己的 mime 返回），
 * 不走 `pageImageUrl`（那条固定 `image/jpeg`，给 PDF 页图用的）。
 */
import { computed, nextTick, ref, watch } from 'vue'

import { api, friendlyMessage } from '../../api/client'
import { useLocate } from '../../composables/useFocus'

const props = defineProps({
  itemId: { type: Number, required: true },
  active: { type: Boolean, default: false },
  // {text, chunkId}：问答引用要落到的那一段（T11.2）—— 图片只有一页，按行标黄
  focus: { type: Object, default: null },
})

const LOW = 0.85
const data = ref(null)
const loading = ref(false)
const error = ref('')
const imgError = ref(false)
let loaded = false

const src = computed(() => api.fileUrl(props.itemId))

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.getPage(props.itemId, 1)
  } catch (err) {
    data.value = null
    error.value = friendlyMessage(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.itemId,
  () => {
    data.value = null
    imgError.value = false
    loaded = false
    if (props.active) {
      loaded = true
      load()
    }
  }
)

watch(
  () => props.active,
  (on) => {
    if (!on || loaded) return
    loaded = true
    load()
  },
  { immediate: true }
)

/** 置信度缺失（老数据）时 confs 为空，一行都不标黄 */
// 引用命中段（T11.2）：图片就一页，行号直接对上文字列表
const marks = useLocate(() => props.itemId, () => props.focus)
const box = ref(null)

const lines = computed(() => {
  const body = data.value?.text || ''
  const confs = data.value?.line_conf || []
  const hit = marks.value && marks.value.page === 1 ? marks.value : null
  return body
    ? body.split('\n').map((text, index) => ({
        text,
        low: confs[index] != null && confs[index] < LOW,
        hit: !!hit && index >= hit.from && index <= hit.to,
      }))
    : []
})

// 文字是异步来的：数据到位、命中行渲染出来之后再滚
watch(lines, async () => {
  if (!marks.value) return
  await nextTick()
  box.value?.querySelector('.line.hit')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
})

const lowCount = computed(() => lines.value.filter((line) => line.low).length)
</script>

<template>
  <div class="image-view">
    <p v-if="imgError && !lines.length && !loading" class="state">这张图打不开了，可能原件被删了。重新上传一次就能看。</p>

    <div class="spread">
      <figure class="shot">
        <img v-if="!imgError" :src="src" alt="这张图片的原图" @error="imgError = true" />
        <figcaption v-else class="shot-missing">原图没显示出来。</figcaption>
      </figure>

      <div ref="box" class="text">
        <p v-if="lowCount" class="warn">有 {{ lowCount }} 行认不准，已标黄，对照左边的原图看看</p>
        <p v-if="error" class="state">{{ error }}</p>
        <p v-else-if="loading" class="state">正在取识别结果…</p>
        <template v-else-if="lines.length">
          <p
            v-for="(line, index) in lines"
            :key="index"
            class="line"
            :class="{ low: line.low, hit: line.hit }"
          >{{ line.text }}</p>
        </template>
        <p v-else class="state">这张图还没认出文字。等识别跑完再看。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.image-view {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  height: 100%;
  min-height: 0;
}

.spread {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  gap: var(--space-4);
}

@media (max-width: 1100px) {
  .spread {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(0, 1fr);
  }
}

.shot {
  margin: 0;
  min-height: 0;
  overflow: auto;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.shot img {
  display: block;
  max-width: 100%;
  height: auto;
}

.shot-missing {
  padding: var(--space-4);
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.text {
  min-height: 0;
  overflow: auto;
  padding-right: var(--space-2);
  font-family: var(--font-reading);
  font-size: 14px;
  line-height: 1.9;
  color: var(--c-text-2);
}

.warn {
  margin: 0 0 var(--space-2);
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
}

.line {
  margin: 0 0 2px;
  white-space: pre-wrap;
  word-break: break-word;
}

.low {
  background: var(--c-warning-soft);
  border-radius: 3px;
}

/* 问答引用命中的那一段（T11.2）：与纯文本原文同一个标记色 */
.hit {
  background: var(--c-mark);
  color: var(--c-text-1);
  border-radius: 3px;
  scroll-margin: 120px;
}

.state {
  margin: var(--space-3) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
