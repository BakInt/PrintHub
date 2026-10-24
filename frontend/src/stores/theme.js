import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

// 主题（亮色 / 深色）状态管理。
// - 用户手动切换过 → 读写 localStorage（键名沿用 cloud-print-* 前缀），刷新后保持。
// - 用户没切换过 → 跟随操作系统 prefers-color-scheme，并监听系统变化实时跟随。
// - 亮暗通过 <html> 上的 .dark 类切换（shadcn-vue CSS 变量主题，见 assets/index.css），
//   index.html 的防闪烁内联脚本使用同一套规则。
const STORAGE_KEY = 'cloud-print-theme'
const DARK_QUERY = '(prefers-color-scheme: dark)'
// 移动端 UI 断点（底部 Tab 栏 / 隐藏桌面导航），与 Tailwind md 断点保持一致。
const MOBILE_QUERY = '(max-width: 767px)'

function readSystemTheme() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light'
  return window.matchMedia(DARK_QUERY).matches ? 'dark' : 'light'
}

function readSavedTheme() {
  if (typeof window === 'undefined') return null
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    return saved === 'light' || saved === 'dark' ? saved : null
  } catch {
    // 隐私模式等场景下 localStorage 不可用，静默降级为跟随系统
    return null
  }
}

function resolveIsMobile() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia(MOBILE_QUERY).matches
}

export const useThemeStore = defineStore('theme', () => {
  const saved = ref(readSavedTheme())
  const systemTheme = ref(readSystemTheme())
  const isMobile = ref(resolveIsMobile())

  // 有效主题：用户显式选择优先，否则跟随系统
  const theme = computed(() => saved.value || systemTheme.value)
  const isDark = computed(() => theme.value === 'dark')

  function applyTheme(value) {
    if (typeof document === 'undefined') return
    const root = document.documentElement
    root.classList.toggle('dark', value === 'dark')
    root.style.colorScheme = value
    // 追加类名后颜色才有过渡动画；延后到下一帧再加，避免首屏加载时整体闪一下
    if (document.body) window.requestAnimationFrame(() => root.classList.add('theme-ready'))
  }

  // 首屏与 index.html 内联脚本都已写过 .dark 类，这里做一次兜底同步
  function sync() {
    applyTheme(theme.value)
  }

  function setTheme(value) {
    const next = value === 'dark' ? 'dark' : 'light'
    saved.value = next
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // 存储不可用不影响本次切换效果
    }
    applyTheme(next)
  }

  function toggleTheme() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  // 恢复「跟随系统」：清除本地记录，系统主题变化会实时同步
  function followSystem() {
    saved.value = null
    try {
      window.localStorage.removeItem(STORAGE_KEY)
    } catch {
      // 忽略
    }
    sync()
  }

  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const darkMedia = window.matchMedia(DARK_QUERY)
    const onSystemChange = (event) => {
      systemTheme.value = event.matches ? 'dark' : 'light'
      // 用户已手动选择时，系统变化不覆盖用户选择
      if (!saved.value) applyTheme(systemTheme.value)
    }
    if (typeof darkMedia.addEventListener === 'function') {
      darkMedia.addEventListener('change', onSystemChange)
    } else if (typeof darkMedia.addListener === 'function') {
      darkMedia.addListener(onSystemChange)
    }

    const mobileMedia = window.matchMedia(MOBILE_QUERY)
    const onViewportChange = (event) => {
      isMobile.value = event.matches
    }
    if (typeof mobileMedia.addEventListener === 'function') {
      mobileMedia.addEventListener('change', onViewportChange)
    } else if (typeof mobileMedia.addListener === 'function') {
      mobileMedia.addListener(onViewportChange)
    }
  }

  sync()

  return {
    theme,
    isDark,
    isMobile,
    hasSavedTheme: computed(() => saved.value !== null),
    setTheme,
    toggleTheme,
    followSystem,
    sync
  }
})
