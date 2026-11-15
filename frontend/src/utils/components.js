/**
 * 可选组件的「现在到底能不能用」—— 只有这一份判据。
 *
 * 后端 `components.status()` 已经把答案算在 `mode` 里：
 *   component = 独立组件已装且握手通过；local = 本机自带库；null = 用不了。
 *
 * 为什么不看 `state`：`state` 说的是"组件目录在不在"。源码运行、或本机已装库时
 * 它一直是 `missing`，可功能其实是可用的 —— 照 `state` 判会出现「采集面板说能读
 * PDF、引导页却把向量/识别列成未安装」，用户为已经能用的能力再下 100–260 MB。
 *
 * 2026-11-15 之前三处各写一份（FileForm 判 `state === 'installed' || mode`、
 * Setup 只判 `state`、DownloadsTab 各判一半），这里收成一份。
 */

/** 功能现在能不能用（组件已装 或 本机自带库） */
export function usable(item) {
  return Boolean(item && item.mode)
}

/** 独立组件包是否已装好（看磁盘，不看功能）——「卸载 / 重装」才需要区分这个 */
export function installed(item) {
  return Boolean(item && item.state === 'installed')
}

/** 状态徽标：文案要说清"现在到底能不能用"，不是复述枚举 */
export function badge(item) {
  if (item.state === 'downloading') {
    return { tone: 'run', text: `安装中 ${item.install?.pct ?? 0}%` }
  }
  if (item.state === 'installed') return { tone: 'ok', text: '已安装' }
  if (item.state === 'broken') return { tone: 'bad', text: '装好了但起不来' }
  if (item.install?.status === 'failed') return { tone: 'bad', text: '上次没装成' }
  if (item.install?.status === 'cancelled') return { tone: '', text: '已取消' }
  // mode=local：源码运行、本机装了库，功能可用 —— 不能写"未安装"骗人
  return { tone: '', text: item.mode === 'local' ? '用本机已安装的版本' : '未安装' }
}
