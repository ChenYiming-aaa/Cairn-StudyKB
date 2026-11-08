import { createApp } from 'vue'

import App from './App.vue'
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
  createApp(App).use(router).mount('#app')
}

bootstrap()
