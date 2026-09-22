import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../composables/useAuth'

const routes = [
  { path: '/login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
  { path: "/", component: () => import('../views/HomeView.vue') },
  { path: "/academic/schedule", component: () => import('../views/ScheduleView.vue') },
  { path: "/academic/grades", component: () => import('../views/GradesView.vue') },
  { path: "/academic/makeup", component: () => import('../views/MakeupView.vue') },
  { path: "/library", component: () => import('../views/LibraryView.vue') },
]

// scrollBehavior：换页显式回到顶部。不写它的话，上一页滚到中部再跳新页
// 会停在半截——视口落在新页中段，看起来也是"抖"。只在路径真变了才回顶，
// 否则同路径带 query（如 /login?next=…）也会被拽回顶部。
const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from) {
    if (to.path === from.path) return false
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const { status, bootstrap } = useAuth()
  // 首个导航先问一次 /auth/me：刷新页面时内存状态是空的，只有服务端知道你是谁
  if (status.value === 'unknown') await bootstrap()

  if (!to.meta.public && status.value !== 'authed') {
    return { path: '/login', query: { next: to.fullPath } }
  }
  if (to.path === '/login' && status.value === 'authed') return { path: '/' }
  return true
})

export default router
