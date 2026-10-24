import { defineStore } from 'pinia'
import { request } from '../api/client'

// 与 frontend/index.html 的 <title> / 内联 SVG favicon 保持一致：
// 后台未配置（或清空）站点标题/图标时回退到这套默认值。
export const DEFAULT_SITE_TITLE = 'PrintHub 云打印'
export const DEFAULT_SITE_FAVICON =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%231d4ed8'/%3E%3Crect x='19' y='13' width='26' height='11' rx='2' fill='%23ffffff' opacity='.92'/%3E%3Cpath d='M14 27h36a4 4 0 0 1 4 4v12a4 4 0 0 1-4 4h-6v9a2 2 0 0 1-2 2H22a2 2 0 0 1-2-2v-9h-6a4 4 0 0 1-4-4V31a4 4 0 0 1 4-4z' fill='%23ffffff'/%3E%3Ccircle cx='46' cy='33' r='2.5' fill='%231d4ed8'/%3E%3Crect x='24' y='42' width='16' height='11' rx='1.5' fill='%23c3d7f8'/%3E%3C/svg%3E"

// 全站唯一一个 <link rel="icon">：先清掉旧的（含 index.html 的内联 SVG）再插入，保证不叠加。
function applyFavicon(url) {
  if (typeof document === 'undefined') return
  document.head.querySelectorAll('link[rel="icon"]').forEach((link) => link.remove())
  const link = document.createElement('link')
  link.rel = 'icon'
  link.href = url
  if (/\.ico($|\?)/i.test(url)) link.type = 'image/x-icon'
  document.head.appendChild(link)
}

export const useSiteStore = defineStore('site', {
  state: () => ({
    title: '',
    faviconUrl: '',
    icpNumber: '',
    loaded: false
  }),
  getters: {
    displayTitle: (state) => state.title || DEFAULT_SITE_TITLE
  },
  actions: {
    // 应用后端站点配置：只接收后端给的字段，留空即回退默认（前端不做任何业务判断）。
    apply(settings) {
      if (typeof settings?.site_title === 'string') this.title = settings.site_title.trim()
      if (typeof settings?.site_favicon_url === 'string') this.faviconUrl = settings.site_favicon_url
      if (typeof settings?.site_icp_number === 'string') this.icpNumber = settings.site_icp_number.trim()
      this.loaded = true
      document.title = this.displayTitle
      applyFavicon(this.faviconUrl || DEFAULT_SITE_FAVICON)
    },
    // 应用启动时拉取一次公开站点配置（/api/site-settings）；失败时保持 index.html 默认值即可。
    async load() {
      try {
        this.apply(await request('/api/site-settings'))
      } catch {
        // 拉取失败不阻塞应用启动：标题/图标维持 index.html 的默认值，备案条不渲染。
      }
    }
  }
})
