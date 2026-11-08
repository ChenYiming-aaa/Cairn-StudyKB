import { createRouter, createWebHashHistory } from 'vue-router'

import Ask from '../views/Ask.vue'
import Dashboard from '../views/Dashboard.vue'
import HtmlPages from '../views/HtmlPages.vue'
import Knowledge from '../views/Knowledge.vue'
import Practice from '../views/Practice.vue'
import Review from '../views/Review.vue'
import Setup from '../views/Setup.vue'
import Tasks from '../views/Tasks.vue'

// hash 模式：M5 打包成 Electron 用 file:// 加载时不会 404（history 模式需要服务端兜底）
export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'knowledge', component: Knowledge },
    { path: '/dashboard', name: 'dashboard', component: Dashboard },
    { path: '/ask', name: 'ask', component: Ask },
    { path: '/pages', name: 'html-pages', component: HtmlPages },
    { path: '/practice', name: 'practice', component: Practice },
    { path: '/review', name: 'review', component: Review },
    { path: '/tasks', name: 'tasks', component: Tasks },
    // 首次引导（T5.7）：不进主导航，靠顶栏的「环境」状态点与启动时的自动跳转进入
    { path: '/setup', name: 'setup', component: Setup },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
