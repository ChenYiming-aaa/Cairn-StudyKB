/* global process */
import { readFileSync } from 'node:fs'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 版本号从 package.json 注入：演示站（VITE_DEMO=1）的「关于」页要显示真版本，
// 不能像以前那样在 demo/index.js 里写死（v0.1.0 发完后线上还显示旧号）。
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

// 开发期：/api 反代到后端 8756，前端走同源，不依赖 CORS（M1 §7 排障表）。
// 生产（Electron）由 window.api.baseUrl 注入绝对地址，见 src/api/client.js。
// CAIRN_API_TARGET 只给「另起一个实例做联调/UI 验收」用：不覆盖时行为与以前完全一致。
export default defineConfig({
  plugins: [vue()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
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
