import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/composables/useAuth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'Login', component: () => import('@/views/LoginView.vue') },
    { path: '/', redirect: '/tasks' },
    ...['tasks', 'results', 'sources', 'history', 'settings'].map(section => ({ path: `/${section}`, name: section, component: () => import('@/views/ShopeeView.vue'), meta: { requiresAuth: true } })),
    { path: '/:pathMatch(.*)*', redirect: '/tasks' },
  ],
})
router.beforeEach(to => {
  const { isAuthenticated } = useAuth()
  if (to.meta.requiresAuth && !isAuthenticated.value) return { name: 'Login', query: { redirect: to.fullPath } }
  if (to.name === 'Login' && isAuthenticated.value) return '/tasks'
})
router.afterEach(to => {
  const titles: Record<string, string> = { tasks: '監控任務', results: '商品與推薦', sources: '資料來源', history: '執行紀錄', settings: 'AI 與通知設定', Login: '登入' }
  document.title = `${titles[String(to.name)] ?? '監控中心'} · 蝦皮臺灣 AI 監控`
})
export default router
