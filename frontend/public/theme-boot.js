/* 首屏防白闪：在 CSS 之前把主题写到 <html>。
 *
 * 为什么必须是一个外部文件而不是 index.html 里的内联脚本：
 * 桌面壳的 CSP 是 `script-src 'self'`（desktop/main.js），内联脚本会被直接拦掉，
 * 拦掉之后刷新就白闪一帧 —— 而白闪恰恰是这行的唯一目的。
 *
 * 读的键与 composables/useTheme.js 一致；缺省值与 tokens.css 的默认主题一致。 */
(function () {
  var root = document.documentElement
  try {
    var theme = localStorage.getItem('cairn.theme') || 'paper'
    var mode = localStorage.getItem('cairn.mode') || 'system'
    var font = localStorage.getItem('cairn.fs') || 'md'
    if (mode === 'system') {
      var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      mode = dark ? 'dark' : 'light'
    }
    root.setAttribute('data-theme', theme)
    root.setAttribute('data-mode', mode)
    root.setAttribute('data-fs', font)
  } catch (err) {
    /* 隐私模式 / 存储被禁：留 index.html 上的默认属性即可 */
  }
})()
