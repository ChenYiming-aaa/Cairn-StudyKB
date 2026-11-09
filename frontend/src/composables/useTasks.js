/**
 * 顶栏「任务」角标（T7.4）：只要**未完成**的数量（排队中 + 进行中），不是总数。
 *
 * 为什么另起一个模块：顶栏在 App.vue，任务页在 Tasks.vue，两边都在轮询同一件事。
 * 这里只保留一个计数与一个定时器，谁先要谁调 `refreshTasks()`，不各跑一套。
 *
 * 轮询策略：有未完成才每 3 秒看一次，全部落定就停 —— 闲时零请求。
 * 计数从 `GET /api/tasks?limit=50` 的 items 里数：排队的任务一定是最新的，
 * 总在前 50 条里，所以不需要额外的 count 接口（零契约变更）。
 */
import { computed, ref } from 'vue'

import { api } from '../api/client'

const active = ref(0)
const ACTIVE_STATUS = ['queued', 'running']

let timer = null
let running = false

function schedule() {
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  if (!active.value) return
  timer = setTimeout(() => {
    timer = null
    refresh()
  }, 3000)
}

async function refresh() {
  if (running) return
  running = true
  try {
    const data = await api.listTasks({ limit: 50 })
    active.value = (data.items || []).filter((t) => ACTIVE_STATUS.includes(t.status)).length
  } catch {
    // 角标失败不该打扰用户（后端没起来时顶栏已经有「未连接」）
  } finally {
    running = false
    schedule()
  }
}

export function useTasks() {
  return { activeTasks: computed(() => active.value), refreshTasks: refresh }
}
