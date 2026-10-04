<template>
  <div class="app-shell">
    <header class="topbar">
      <RouterLink class="brand" to="/">云打印系统</RouterLink>
      <nav class="nav-actions">
        <RouterLink to="/">打印</RouterLink>
        <RouterLink
          v-if="auth.user"
          :to="ordersTarget"
          active-class="nav-no-auto"
          exact-active-class="nav-no-auto"
          :class="{ 'router-link-active': isOrders }"
        >订单</RouterLink>
        <RouterLink
          v-if="auth.user"
          :to="mineTarget"
          active-class="nav-no-auto"
          exact-active-class="nav-no-auto"
          :class="{ 'router-link-active': isMine }"
        >个人中心</RouterLink>
        <RouterLink v-if="auth.user?.is_admin" to="/admin">后台</RouterLink>
        <button v-if="auth.user" class="ghost-btn" @click="auth.logout()">退出</button>
        <RouterLink v-else class="primary-link" to="/login">登录/注册</RouterLink>
      </nav>
    </header>
    <main>
      <RouterView />
    </main>

    <nav class="mobile-tabbar" aria-label="主导航">
      <RouterLink class="tab-item" to="/" :class="{ active: isHome }">
        <Home :size="22" />
        <span>首页</span>
      </RouterLink>
      <RouterLink class="tab-item" :to="ordersTarget" :class="{ active: isOrders }">
        <ClipboardList :size="22" />
        <span>订单</span>
      </RouterLink>
      <RouterLink class="tab-item" :to="mineTarget" :class="{ active: isMine }">
        <User :size="22" />
        <span>我的</span>
      </RouterLink>
    </nav>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ClipboardList, Home, User } from 'lucide-vue-next'
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
const route = useRoute()
onMounted(() => auth.loadMe())

// 顶部 header（桌面）与底部 Tab（手机端）复用同一套导航目标，功能完全复用现有路由：
// 已登录用户进入个人中心，未登录用户引导登录。
// 「订单」只看最近订单，「我的/个人中心」看余额/联系人/充值等其余内容，两端都按 ?tab= 拆分显隐
// （见 UI_ADAPTATION 4.1）。两个链接都用带 ?tab= 的普通 RouterLink（保证可点击跳转），并把
// active-class/exact-active-class 改名到无样式的 nav-no-auto 以禁用 RouterLink 按路径自动高亮
// （否则 query 被忽略会导致「订单」「个人中心」同时高亮），高亮改由互斥的 isOrders/isMine 控制。
const ordersTarget = computed(() => (auth.user ? { path: '/user/dashboard', query: { tab: 'orders' } } : '/login'))
const mineTarget = computed(() => (auth.user ? { path: '/user/dashboard', query: { tab: 'me' } } : '/login'))
const onDashboard = computed(() => route.path === '/user/dashboard')
const isHome = computed(() => route.path === '/')
const isOrders = computed(() => (onDashboard.value && route.query.tab === 'orders') || route.path.startsWith('/payment'))
const isMine = computed(() => (onDashboard.value && route.query.tab !== 'orders') || route.path === '/login')

</script>
