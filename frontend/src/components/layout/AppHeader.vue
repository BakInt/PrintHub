<script setup>
import { RouterLink } from 'vue-router'
import { Printer } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import ThemeToggle from './ThemeToggle.vue'
import { useNavTargets } from '@/composables/useNavTargets'
import { useAuthStore } from '@/stores/auth'

// 全局顶栏：品牌 + 桌面端导航（md 及以上）+ 主题切换 / 登录态按钮。
// 手机端隐藏文字导航入口（导航改由底部 Tab 栏承担，见 MobileTabbar），
// 仅保留主题切换与登录/退出主按钮。
const auth = useAuthStore()
const { ordersTarget, mineTarget, isHome, isOrders, isMine } = useNavTargets()

// RouterLink 的高亮由互斥的 isOrders/isMine 判定驱动（query 拆分视图），
// 而不是 RouterLink 自带的按路径高亮。
const navLinkClass = (active) =>
  active ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:text-foreground'
</script>

<template>
  <header class="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur-md">
    <div class="mx-auto flex h-14 w-full max-w-7xl items-center justify-between gap-3 px-4 sm:px-6">
      <RouterLink to="/" class="flex min-w-0 items-center gap-2.5">
        <span
          class="grid size-8 shrink-0 place-items-center rounded-lg bg-linear-to-br from-primary to-(--brand-deep) text-primary-foreground shadow-sm"
          aria-hidden="true"
        >
          <Printer class="size-4" />
        </span>
        <span class="truncate font-display text-base font-bold tracking-tight text-primary sm:text-lg">
          PrintHub 云打印
        </span>
      </RouterLink>

      <nav class="hidden items-center gap-1 md:flex" aria-label="主导航">
        <Button as-child variant="ghost" size="sm" :class="navLinkClass(isHome)">
          <RouterLink to="/">打印</RouterLink>
        </Button>
        <Button v-if="auth.user" as-child variant="ghost" size="sm" :class="navLinkClass(isOrders)">
          <RouterLink :to="ordersTarget">订单</RouterLink>
        </Button>
        <Button v-if="auth.user" as-child variant="ghost" size="sm" :class="navLinkClass(isMine)">
          <RouterLink :to="mineTarget">个人中心</RouterLink>
        </Button>
        <Button v-if="auth.user?.is_admin" as-child variant="ghost" size="sm" :class="navLinkClass(false)">
          <RouterLink to="/admin">后台</RouterLink>
        </Button>
      </nav>

      <div class="flex items-center gap-1.5">
        <ThemeToggle />
        <Button
          v-if="auth.user"
          variant="outline"
          size="sm"
          class="h-9 rounded-full px-4 max-md:bg-card"
          @click="auth.logout()"
        >
          退出
        </Button>
        <Button v-else as-child size="sm" class="h-9 rounded-full px-4 font-semibold">
          <RouterLink to="/login">登录/注册</RouterLink>
        </Button>
      </div>
    </div>
  </header>
</template>
