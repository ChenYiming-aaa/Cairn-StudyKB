/**
 * 打开 PDF 并量出每页尺寸（T11.1）。
 *
 * 三件事都在这里：把 worker / cmaps / wasm 指到**本站**（离线、同源，
 * Electron 的 `script-src 'self'` 不用放宽）、打开文档、算虚拟滚动要用的高度。
 *
 * **尺寸先按第 1 页占位、随后逐页纠正**：30 页全量量一遍要几百毫秒，
 * 让首屏等这个数没有意义 —— 同一份 PDF 里页高差 1% 用户看不出来，
 * 而首屏多等半秒感觉得到。纠正时只在该页尺寸真的不同时才回调，避免反复重排。
 *
 * `url` 指向原件（`GET /api/knowledge/{id}/file`）：pdf.js 会自己发 Range 请求，
 * 取到第一页所需的数据就能开画，不必等整份下完。
 */
let lib = null

/**
 * pdf.js 按需加载：它连 worker 差不多 1.7 MB，而打开首页、问答、练习时一次都用不上。
 * 静态 import 会把它算进主包，等于让每次启动都替「偶尔看一眼 PDF」付这笔钱。
 */
async function loadLib() {
  if (lib) return lib
  const [mod, worker] = await Promise.all([
    import('pdfjs-dist'),
    import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
  ])
  mod.GlobalWorkerOptions.workerSrc = worker.default
  lib = mod
  return lib
}

/** 资源目录：vite 插件把 cmaps / wasm 拷到 `public/pdf/`，这里与部署前缀对齐 */
export function assetBase() {
  const base = import.meta.env.BASE_URL || '/'
  return `${base.replace(/\/$/, '')}/pdf/`
}

export async function openPdf(url, { onSizes } = {}) {
  const pdfjs = await loadLib()
  const task = pdfjs.getDocument({
    url,
    // 中文讲义常见「字体没嵌进 PDF」，靠 cMap 才能在 canvas 上出字
    cMapUrl: `${assetBase()}cmaps/`,
    cMapPacked: true,
    wasmUrl: `${assetBase()}wasm/`,
  })
  const doc = await task.promise
  const first = await doc.getPage(1)
  const base = first.getViewport({ scale: 1 })
  const sizes = Array.from({ length: doc.numPages }, () => ({
    width: base.width,
    height: base.height,
  }))
  onSizes?.(sizes)

  // 后台慢慢纠正其余页：失败一页不影响别的（尺寸错了只是滚动位置略偏）
  ;(async () => {
    for (let n = 2; n <= doc.numPages; n += 1) {
      try {
        const page = await doc.getPage(n)
        const view = page.getViewport({ scale: 1 })
        const cur = sizes[n - 1]
        if (Math.abs(view.width - cur.width) > 0.5 || Math.abs(view.height - cur.height) > 0.5) {
          sizes[n - 1] = { width: view.width, height: view.height }
          onSizes?.([...sizes])
        }
      } catch {
        // 文档中途被 destroy（切内容）时必然抛这里，静默跳过
        return
      }
    }
  })()

  return { doc, sizes }
}

/** 打开失败时的退路：用页数 + A4 比例撑起滚动区，只显示后端页图（不渲染 canvas） */
export function fallbackSizes(pageCount) {
  return Array.from({ length: Math.max(1, pageCount || 0) }, () => ({ width: 1240, height: 1754 }))
}
