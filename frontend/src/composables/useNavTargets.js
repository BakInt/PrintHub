import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// 顶部导航（桌面端顶栏）与底部 Tab（手机端）共用的导航目标与高亮判定，
// 功能完全复用现有路由：已登录用户进入个人中心，未登录用户引导登录。
// 「订单」只看最近订单，「个人中心」看余额/联系人/充值等其余内容，两端都按
// ?tab= 拆分显隐（见 doc/UI_ADAPTATION.md）。高亮由互斥的 isOrders/isMine
// 控制，避免 RouterLink 按路径自动高亮时忽略 query 导致两项同时点亮。
export function useNavTargets() {
  const auth = useAuthStore()
  const route = useRoute()

  const ordersTarget = computed(() => (auth.user ? { path: '/user/dashboard', query: { tab: 'orders' } } : '/login'))
  const mineTarget = computed(() => (auth.user ? { path: '/user/dashboard', query: { tab: 'me' } } : '/login'))
  const onDashboard = computed(() => route.path === '/user/dashboard')
  const isHome = computed(() => route.path === '/')
  const isOrders = computed(() => (onDashboard.value && route.query.tab === 'orders') || route.path.startsWith('/payment'))
  const isMine = computed(() => (onDashboard.value && route.query.tab !== 'orders') || route.path === '/login')

  return { ordersTarget, mineTarget, isHome, isOrders, isMine }
}
