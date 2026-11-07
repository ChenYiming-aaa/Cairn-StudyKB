/* global process */
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期：/api 反代到后端 8756，前端走同源，不依赖 CORS（M1 §7 排障表）。
// 生产（Electron）由 window.api.baseUrl 注入绝对地址，见 src/api/client.js。
// CAIRN_API_TARGET 只给「另起一个实例做联调/UI 验收」用：不覆盖时行为与以前完全一致。
export default defineConfig({
  plugins: [vue()],
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
