import { createRouter, createWebHashHistory } from 'vue-router'

import Ask from '../views/Ask.vue'
import Dashboard from '../views/Dashboard.vue'
import ExamReview from '../views/ExamReview.vue'
import HtmlPages from '../views/HtmlPages.vue'
import Knowledge from '../views/Knowledge.vue'
import Practice from '../views/Practice.vue'
import Review from '../views/Review.vue'
import Setup from '../views/Setup.vue'
import Tasks from '../views/Tasks.vue'

// 试用页只在演示站（VITE_DEMO=1）注册：正式包里 `import.meta.env.VITE_DEMO` 是 undefined，
// 条件恒假，Rollup 会把这条连同 Try.vue 一起摇掉 —— 桌面版没有这个页面（它本来就是真后端）。
const demoRoutes =
  import.meta.env.VITE_DEMO === '1'
    ? [{ path: '/try', name: 'try', component: () => import('../views/Try.vue') }]
    : []

// hash 模式：M5 打包成 Electron 用 file:// 加载时不会 404（history 模式需要服务端兜底）
export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'knowledge', component: Knowledge },
    { path: '/dashboard', name: 'dashboard', component: Dashboard },
    { path: '/ask', name: 'ask', component: Ask },
    { path: '/pages', name: 'html-pages', component: HtmlPages },
    { path: '/practice', name: 'practice', component: Practice },
    // 试卷复核（T10.3）：从原件详情进，参数是原件 id —— 复核的是「这份文件」，不是内容
    { path: '/exam/:fileId', name: 'exam-review', component: ExamReview },
    { path: '/review', name: 'review', component: Review },
    { path: '/tasks', name: 'tasks', component: Tasks },
    // 首次引导（T5.7）：不进主导航，靠顶栏的「环境」状态点与启动时的自动跳转进入
    { path: '/setup', name: 'setup', component: Setup },
    ...demoRoutes,
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
