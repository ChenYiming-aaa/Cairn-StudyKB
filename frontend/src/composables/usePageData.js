/**
 * 原件页签的「第一次可见才加载」—— Word / PPT / 图片三处逐字相同的那个块。
 *
 * 这段逻辑的坑踩过两次（M11）：`active` 的 watcher 漏了 `immediate` 会「切过去
 * 不加载」，`itemId` 变了没清 `loaded` 会「换了内容还显示上一份」。各写一份时
 * 要改三处、漏一处就只在一个页签上坏，所以收在这里。
 *
 * 调用方只需给两件事：怎么取数（`fetcher`）、切内容时要额外清什么（`onReset`）。
 *
 * `PdfView` 与 `pdf/PdfTextPanel` 不用它：前者管理 pdf.js 文档对象（要 destroy、
 * 失败还要退页图模式），后者按页重取且带竞态守卫（快速翻页时后到的旧响应不能覆盖），
 * 硬套会把这两件事塞进参数里，反而更难读。
 */
import { ref, watch } from 'vue'

import { friendlyMessage } from '../api/client'

/**
 * @param {() => number} itemId 用 getter：异步回来时 props 可能已经变了
 * @param {() => boolean} active 页签是否可见
 * @param {(itemId: number) => Promise<any>} fetcher 取数
 * @param {{ onReset?: () => void }} [options] 切内容时额外清掉的本地状态
 */
export function usePageData(itemId, active, fetcher, { onReset } = {}) {
  const data = ref(null)
  const loading = ref(false)
  const error = ref('')
  let loaded = false

  async function load() {
    loading.value = true
    error.value = ''
    try {
      data.value = await fetcher(itemId())
    } catch (err) {
      data.value = null
      error.value = friendlyMessage(err)
    } finally {
      loading.value = false
    }
  }

  watch(itemId, () => {
    data.value = null
    onReset?.()
    loaded = false
    if (active()) {
      loaded = true
      load()
    }
  })

  // immediate 是必须的：从别处切进来时组件是刚挂载的，`active` 在挂载前就已经是 true，
  // 非 immediate 的 watcher 根本不会触发
  watch(
    active,
    (on) => {
      if (!on || loaded) return
      loaded = true
      load()
    },
    { immediate: true }
  )

  return { data, loading, error, load }
}
