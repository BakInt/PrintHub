<template>
  <div class="app-shell" :class="{ 'app-shell-admin': isAdminRoute }">
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
        <!-- 手机端主题切换按钮：只在手机顶栏显示（基础样式 display:none），排在「退出」左边。
             它是顶栏内的普通 flex 子项，不使用 fixed/absolute，因此不受顶栏 backdrop-filter 影响。 -->
        <button
          class="theme-toggle theme-toggle-mobile"
          type="button"
          :aria-label="theme.isDark ? '切换到亮色模式' : '切换到深色模式'"
          :title="theme.isDark ? '切换到亮色模式' : '切换到深色模式'"
          :aria-pressed="theme.isDark"
          @click="theme.toggleTheme()"
        >
          <Moon v-if="!theme.isDark" :size="18" />
          <Sun v-else :size="18" />
        </button>
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

    <!-- 电脑端主题切换按钮：固定到视口左下角，手机上隐藏（见 CSS 767px 断点）。
         必须写在 <header class="topbar"> 外面：顶栏有 backdrop-filter，会让其内部
         position: fixed 的子元素以顶栏为包含块，按钮会被粘到顶栏左上角（已踩坑）。 -->
    <button
      class="theme-toggle theme-toggle-pc"
      type="button"
      :aria-label="theme.isDark ? '切换到亮色模式' : '切换到深色模式'"
      :title="theme.isDark ? '切换到亮色模式' : '切换到深色模式'"
      :aria-pressed="theme.isDark"
      @click="theme.toggleTheme()"
    >
      <Moon v-if="!theme.isDark" :size="20" />
      <Sun v-else :size="20" />
    </button>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { ClipboardList, Home, Moon, Sun, User } from 'lucide-vue-next'
import { useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'

const auth = useAuthStore()
// 主题：亮/暗由 html[data-theme] 决定，用户选择存 localStorage，未选择时跟随系统
const theme = useThemeStore()
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
// 手机端后台（/admin）的底部栏由 AdminView 自己的 .admin-tabbar 承担：这里给外壳加一个标记类，
// 供 CSS 在 767px 断点下隐藏前台底部 Tab 栏（首页/订单/我的），避免两条底部栏叠在一起。
const isAdminRoute = computed(() => route.path.startsWith('/admin'))

</script>
