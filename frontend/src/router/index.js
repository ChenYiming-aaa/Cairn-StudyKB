import { createRouter, createWebHashHistory } from 'vue-router'

import Ask from '../views/Ask.vue'
import Knowledge from '../views/Knowledge.vue'
import Tasks from '../views/Tasks.vue'

// hash 模式：M5 打包成 Electron 用 file:// 加载时不会 404（history 模式需要服务端兜底）
export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'knowledge', component: Knowledge },
    { path: '/ask', name: 'ask', component: Ask },
    { path: '/tasks', name: 'tasks', component: Tasks },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
