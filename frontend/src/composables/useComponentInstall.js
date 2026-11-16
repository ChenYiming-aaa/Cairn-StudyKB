/**
 * 组件安装的「看门人」（跨界面审计 6-4）。
 *
 * 原来只有「设置 → 下载」在轮询，而设置是模态：关掉窗口那个 tab 就卸载了，
 * 于是 toast 里那句「装完会通知」从来没兑现过 —— 全站没有第二处订阅安装进度。
 *
 * 这里补上唯一的一处：**只在真的有组件在下载时才轮询**（5 秒一次），
 * 没在下载就一个请求也不发。下载结束（装好 / 没装成）时：
 * 1. 通知各页重新探测组件（6-1：检索页、采集面板、引导页、详情页的按钮）；
 * 2. 弹一条 toast —— 用户可能已经关掉设置窗口，在别的页面等着。
 *
 * 两个入口：`watchNow()` 由 App 在启动时调一次（接住重启前没下完的），
 * 以及「下载」tab 点了安装之后调一次。
 */
import { api } from '../api/client'
import { useToast } from './useToast'
import { useUi } from './useUi'
import { installed } from '../utils/components'

const POLL_MS = 5000

let timer = null
let inflight = false
/** 上一次看到的「下载中」：id → 组件名（判断谁刚刚结束，以及该说装好了还是没装成） */
let prev = new Map()

function stop() {
  if (timer) clearTimeout(timer)
  timer = null
}

function schedule() {
  if (timer) return
  timer = setTimeout(() => {
    timer = null
    tick()
  }, POLL_MS)
}

async function tick() {
  if (inflight) return
  inflight = true
  try {
    const data = await api.components()
    const items = data.items || []
    const next = new Map()
    for (const item of items) {
      if (item.state === 'downloading') next.set(item.id, item)
    }

    // 从「下载中」变成别的状态：装好了还是没装成，说法不一样
    for (const [id, before] of prev) {
      const now = items.find((item) => item.id === id)
      if (now && now.state === 'downloading') continue
      const { requestComponentsRefresh } = useUi()
      const { ok, info } = useToast()
      requestComponentsRefresh()
      // 取消已经在「下载」tab 里说过一次，这里不再重复
      const cancelled = now?.install?.status === 'cancelled'
      if (installed(now)) ok(`「${before.name}」装好了，回原来的页面就能用`)
      else if (!cancelled) info(`「${before.name}」没装完，去「设置 → 下载」看原因`)
    }

    prev = next
    if (next.size) schedule()
    else stop()
  } catch {
    // 后端没起来 / 演示版：不轮询，下次点安装再接管
    stop()
  } finally {
    inflight = false
  }
}

/** 接住当前正在下载的组件；没有就立即停（不常驻轮询） */
async function watchNow() {
  if (inflight) return
  await tick()
}

export function useComponentInstall() {
  return { watchNow }
}
