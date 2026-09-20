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

const router = createRouter({ history: createWebHistory(), routes })

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
