import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import AuthView from '../views/AuthView.vue'
import PaymentView from '../views/PaymentView.vue'
import DashboardView from '../views/DashboardView.vue'
import AdminView from '../views/AdminView.vue'
// 【证照打印】隔离钩子（预算表内）：cert 模块路由清单一次性引入（/cert 门户 + 模块页；证件照管理在 AdminView tab 内）。
import certRoutes from '../cert/routes'
// 【两页合一打印】隔离钩子：doc2up 模块路由清单（/cert/doc-2up，见 AGENTS 6.10）。
import doc2upRoutes from '../doc2up/routes'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/login', component: AuthView },
    { path: '/payment/:orderId', component: PaymentView },
    { path: '/user/dashboard', component: DashboardView },
    { path: '/admin', component: AdminView, meta: { requiresAdmin: true } },
    ...certRoutes,
    ...doc2upRoutes
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
