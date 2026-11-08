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
