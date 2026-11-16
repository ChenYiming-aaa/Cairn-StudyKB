/**
 * 「今日」概览数字（跨界面审计 2-1）——**模块级单例**。
 *
 * 为什么要有它：`TodayBar` 原来只在 `onMounted` 取一次 `/api/stats/today`，
 * 而同页的采集入库、开始整理、批量移入、结束专注都不会通知它。结果是一屏三处数字
 * 互相打脸：顶部「待整理 1」、左栏「待整理 2」、列表「3 条」。
 *
 * 现在的规矩：**数字只有一份**，谁改了数据谁调一次 `loadToday()`。
 * 反向的做法（TodayBar 里 watch(refreshTick)，再让 refreshAll 调 requestRefresh）
 * 会互相触发成死循环，别这么改。
 */
import { ref } from 'vue'

import { api } from '../api/client'

const today = ref(null)
const loaded = ref(false)
let inflight = null

/**
 * 拉一次今日数字。并发调用合并成一个请求：一次页面动作常常同时触发两三处刷新，
 * 没必要打三遍同一个接口。
 */
async function loadToday() {
  if (inflight) return inflight
  inflight = (async () => {
    try {
      today.value = await api.statsToday()
    } catch {
      // 拿不到就不显示数字：顶栏已有「未连接」，这里不再叠一条错误
      today.value = null
    } finally {
      loaded.value = true
      inflight = null
    }
  })()
  return inflight
}

export function useToday() {
  return { today, loaded, loadToday }
}
