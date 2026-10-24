import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
// 全局样式入口：Tailwind v4 + shadcn-vue CSS 变量主题（亮/暗由 html.dark 切换）
import './assets/index.css'

createApp(App).use(createPinia()).use(router).mount('#app')
