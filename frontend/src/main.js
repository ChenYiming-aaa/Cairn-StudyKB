import { createApp } from 'vue'

import App from './App.vue'
import { initTheme } from './composables/useTheme'
import router from './router'
import './styles/tokens.css'
import './styles/app.css'
import './styles/content.css'

async function bootstrap() {
  // 静态演示（github.io）：挂载前把网络层换成抓好的 fixture。
  // VITE_DEMO 未设时这段是死代码，Rollup 会连同 demo/ 一起摇掉，正式构建体积不受影响。
  if (import.meta.env.VITE_DEMO === '1') {
    const { installDemo } = await import('./demo')
    installDemo()
  }
  // 主题要在挂载前落定：`theme-boot.js` 已经写过一次（防白闪），这里补上
  // 「跟随系统」的监听，并保证 data-* 与 localStorage 一致
  initTheme()
  createApp(App).use(router).mount('#app')
}

bootstrap()
