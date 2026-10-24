<template>
  <div class="flex min-h-svh min-h-dvh flex-col">
    <a
      class="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:inline-flex focus:min-h-10 focus:items-center focus:rounded-md focus:bg-primary focus:px-4 focus:font-bold focus:text-primary-foreground"
      href="#main-content"
    >跳到主要内容</a>

    <!-- 后台路由使用 AdminView 自己的完整顶栏（含主题切换/退出），避免双顶栏叠加 -->
    <AppHeader v-if="!isAdminRoute" />

    <!-- 后台路由（/admin）自带全高布局（侧边栏 + 内容），主容器不限宽、不加内边距；
         前台页面限宽居中，并为底部 Tab 栏预留安全区内边距。 -->
    <main
      id="main-content"
      class="flex-1"
      :class="isAdminRoute
        ? 'w-full'
        : 'mx-auto w-full max-w-7xl px-3 pb-[calc(84px+env(safe-area-inset-bottom))] pt-3 sm:px-6 md:pb-10 md:pt-6'"
    >
      <RouterView />
      <!-- ICP 备案条（仅后台配置了备案号才渲染）：随内容排在页尾、手机端位于底部 Tab 栏预留区内侧；
           后台路由由 AdminView 自己在内容底部渲染，避免被全高布局截断。 -->
      <IcpFooter v-if="!isAdminRoute" />
    </main>

    <!-- 手机端底部 Tab 导航（< md 断点）：后台页面（/admin）由 AdminView 自己的
         底部栏承担，这里通过 isAdminRoute 隐藏前台三条 Tab，避免两条底部栏叠加。 -->
    <MobileTabbar v-if="!isAdminRoute" />

    <!-- 全局轻提示（vue-sonner）：跟随亮暗主题变量 -->
    <Toaster position="top-center" :duration="4000" />
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import AppHeader from '@/components/layout/AppHeader.vue'
import IcpFooter from '@/components/layout/IcpFooter.vue'
import MobileTabbar from '@/components/layout/MobileTabbar.vue'
import { Toaster } from '@/components/ui/sonner'
import { useAuthStore } from '@/stores/auth'
import { useSiteStore } from '@/stores/site'

const auth = useAuthStore()
const site = useSiteStore()
const route = useRoute()
// 站点配置（标题/favicon/备案号）在应用启动时拉取一次并全局应用，登录页/前台/后台共用。
onMounted(() => {
  auth.loadMe()
  site.load()
})

// 手机端后台（/admin）的底部栏由 AdminView 自己的底部 Tab 栏承担：
// 外壳据此隐藏前台的「首页/订单/我的」底部 Tab，避免两条底部栏叠在一起。
const isAdminRoute = computed(() => route.path.startsWith('/admin'))
</script>
