<script setup>
import { Moon, Sun } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { useThemeStore } from '@/stores/theme'

// 亮/暗主题切换按钮（顶栏内使用，桌面与手机端共用同一份用户选择）。
const theme = useThemeStore()
</script>

<template>
  <Button
    variant="ghost"
    size="icon"
    class="size-9"
    type="button"
    :aria-label="theme.isDark ? '切换到亮色模式' : '切换到深色模式'"
    :title="theme.isDark ? '切换到亮色模式' : '切换到深色模式'"
    :aria-pressed="theme.isDark"
    @click="theme.toggleTheme()"
  >
    <Sun v-if="theme.isDark" class="size-5" />
    <Moon v-else class="size-5" />
  </Button>
</template>
