import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期：/api 反代到后端 8756，前端走同源，不依赖 CORS（M1 §7 排障表）。
// 生产（Electron）由 window.api.baseUrl 注入绝对地址，见 src/api/client.js。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8756',
        changeOrigin: true,
      },
    },
  },
})
