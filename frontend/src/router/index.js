import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import AuthView from '../views/AuthView.vue'
import PaymentView from '../views/PaymentView.vue'
import DashboardView from '../views/DashboardView.vue'
import AdminView from '../views/AdminView.vue'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/login', component: AuthView },
    { path: '/payment/:orderId', component: PaymentView },
    { path: '/user/dashboard', component: DashboardView },
    { path: '/admin', component: AdminView, meta: { requiresAdmin: true } }
  ]
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAdmin) return true
  const auth = useAuthStore()
  const user = await auth.ensureLoaded()
  if (!user) {
    window.alert('请先登录管理员账号')
    return { path: '/login' }
  }
  if (!user.is_admin) {
    window.alert('无效请求')
    return { path: '/login' }
  }
  return true
})

export default router
