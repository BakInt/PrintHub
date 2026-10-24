<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ClipboardList, Home, User } from 'lucide-vue-next'
import { useNavTargets } from '@/composables/useNavTargets'
import { useAuthStore } from '@/stores/auth'

// 手机端（< md 断点）底部 Tab 导航栏：首页 / 订单 / 我的。
// 图标 + 文字 + 选中高亮，底部适配 iOS 安全区；桌面端隐藏。
// 后台（/admin）的底部栏由 AdminView 自己的 AdminTabbar 承担，前台壳不渲染。
const auth = useAuthStore()
const route = useRoute()
const { ordersTarget, mineTarget, isHome, isOrders, isMine } = useNavTargets()

const items = computed(() => [
  { key: 'home', label: '首页', icon: Home, to: '/', active: isHome.value },
  { key: 'orders', label: '订单', icon: ClipboardList, to: auth.user ? ordersTarget.value : '/login', active: isOrders.value },
  { key: 'mine', label: '我的', icon: User, to: auth.user ? mineTarget.value : '/login', active: isMine.value }
])
</script>

<template>
  <nav
    v-if="!route.path.startsWith('/admin')"
    class="fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 border-t border-border bg-background/92 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
    aria-label="主导航"
    style="box-shadow: 0 -6px 24px rgb(13 27 62 / 0.08)"
  >
    <RouterLink
      v-for="item in items"
      :key="item.key"
      :to="item.to"
      class="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold transition-colors"
      :class="item.active ? 'text-primary' : 'text-muted-foreground active:text-foreground'"
      :aria-current="item.active ? 'page' : undefined"
    >
      <span
        class="grid h-7 w-12 place-items-center rounded-full transition-colors"
        :class="item.active ? 'bg-primary/10' : ''"
      >
        <component :is="item.icon" class="size-5" />
      </span>
      <span class="leading-none">{{ item.label }}</span>
    </RouterLink>
  </nav>
</template>
