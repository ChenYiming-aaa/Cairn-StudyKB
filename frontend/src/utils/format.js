/** 时间显示：后端返回 ISO 8601 带时区（总纲 §7），这里只做展示层格式化。 */

export function shortTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fullTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes()
  )}`
}

export function charCount(text) {
  return (text || '').length
}

/**
 * 字节 → 「12.9 MB / 1.2 GB」。列表里只需要一个量级，不显示精确字节。
 *
 * **十进制**：1 MB = 10⁶ 字节、1 GB = 10⁹。全应用只有这一个体积算法 ——
 * 曾经这里按 1024² 算、`Setup.vue` 与下载页按 10⁶ 算，同一个安装包
 * 一边显示 174 MB、一边显示 182 MB，而 README 与 Release 页写的是 182 MB。
 * 「MB」按定义就是 10⁶，文档也一直是这个口径，所以统一到这里。
 *
 * `digits` 只影响 MB 的小数位：文件列表要 1 位（`12.3 MB`），
 * 下载体积 / 组件体积是给人看量级的，传 0 就是 `182 MB`。GB 固定 1 位（`1.2 GB`）。
 */
export function fileSize(bytes, digits = 1) {
  const n = Number(bytes) || 0
  if (n <= 0) return '—'
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`
  if (n >= 1e6) return `${(n / 1e6).toFixed(digits)} MB`
  if (n >= 1e3) return `${Math.round(n / 1e3)} KB`
  return `${Math.round(n)} B`
}

/** 秒 → mm:ss（倒计时用；超过 1 小时退化成 h:mm:ss） */
export function clock(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0))
  const pad = (n) => String(n).padStart(2, '0')
  const hours = Math.floor(total / 3600)
  const body = `${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`
  return hours ? `${hours}:${body}` : body
}

/** 秒 → 「1 小时 25 分」/「25 分钟」/「40 秒」，统计展示用 */
export function humanDuration(seconds) {
  const total = Math.max(0, Math.round(seconds || 0))
  if (total < 60) return `${total} 秒`
  const minutes = Math.round(total / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} 小时 ${rest} 分` : `${hours} 小时`
}
