/* global process */
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 版本号从 package.json 注入：演示站（VITE_DEMO=1）的「关于」页要显示真版本，
// 不能像以前那样在 demo/index.js 里写死（v0.1.0 发完后线上还显示旧号）。
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

const ROOT = dirname(fileURLToPath(import.meta.url))

/**
 * pdf.js 的两类附属资源拷进 `public/pdf/`（T11.1）。
 *
 * 为什么不在代码里 `import ... ?url`：cmaps 是 169 个 `.bcmap`、wasm 三个，
 * 逐个 import 既不现实也没有意义 —— 它们是**按名字在运行时拼接**取用的
 * （`cMapUrl` + 编码名），Vite 的哈希改名反而会让 pdf.js 找不到。
 *
 * 为什么放在 vite 配置里而不是 npm prebuild：CI 直接跑 `npx vite build`，
 * 不经过 npm 生命周期，放 package.json 的 prebuild 在 CI 上不会执行。
 *
 * 目录在 .gitignore 里：它是 node_modules 的副本，入库只会随版本升级悄悄漂掉。
 */
function pdfAssets() {
  const from = join(ROOT, 'node_modules', 'pdfjs-dist')
  const to = join(ROOT, 'public', 'pdf')
  // 只带渲染真正要用的三样：cmaps（中文未嵌字体）、JBIG2 / JPEG2000（扫描件图）、 ICC（色彩）
  const files = [
    ['wasm/jbig2.wasm', 'wasm/jbig2.wasm'],
    ['wasm/openjpeg.wasm', 'wasm/openjpeg.wasm'],
    ['wasm/qcms_bg.wasm', 'wasm/qcms_bg.wasm'],
  ]
  const copy = () => {
    if (!existsSync(from)) return
    const cmaps = join(from, 'cmaps')
    if (existsSync(cmaps)) {
      mkdirSync(join(to, 'cmaps'), { recursive: true })
      for (const name of readdirSync(cmaps)) {
        copyFileSync(join(cmaps, name), join(to, 'cmaps', name))
      }
    }
    for (const [src, dst] of files) {
      const target = join(to, dst)
      if (!existsSync(join(from, src))) continue
      mkdirSync(dirname(target), { recursive: true })
      copyFileSync(join(from, src), target)
    }
  }
  return { name: 'cairn-pdf-assets', buildStart: copy, configureServer: copy }
}

/**
 * 演示站的「自带 Key 试用」要把提示词原样复刻到前端。
 *
 * 为什么不手抄一份到 `src/demo/`：抄一遍就多一份会漂的副本。提示词改了口径，
 * 演示站却还按旧的跑 —— 那是「演示效果不代表产品效果」，比不演示更糟。
 * 所以构建演示包时直接从 `backend/app/prompts/` 读，正式构建注入 `null`（约 10 KB 不进包）。
 */
function demoPrompts() {
  if (process.env.VITE_DEMO !== '1') return 'null'
  const dir = join(ROOT, '..', 'backend', 'app', 'prompts')
  const out = {}
  for (const name of ['organize', 'ask', 'quiz']) {
    const file = join(dir, `${name}.md`)
    // 缺一条就整条构建失败，不做「缺哪个跳过哪个」：演示站少一条提示词，
    // 那一步就成了空跑，而页面看起来完全正常 —— 这类错最难发现。
    if (!existsSync(file)) throw new Error(`演示站要读 ${file}，但它不在（提示词目录被挪了？）`)
    const text = readFileSync(file, 'utf-8')
    if (!text.trim()) throw new Error(`${file} 是空的，注入进去会把那一步变成空跑`)
    out[name] = text
  }
  return JSON.stringify(out)
}

// 开发期：/api 反代到后端 8756，前端走同源，不依赖 CORS（M1 §7 排障表）。
// 生产（Electron）由 window.api.baseUrl 注入绝对地址，见 src/api/client.js。
// CAIRN_API_TARGET 只给「另起一个实例做联调/UI 验收」用：不覆盖时行为与以前完全一致。
export default defineConfig({
  plugins: [vue(), pdfAssets()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __DEMO_PROMPTS__: demoPrompts(),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.CAIRN_API_TARGET || 'http://127.0.0.1:8756',
        changeOrigin: true,
      },
    },
  },
})
