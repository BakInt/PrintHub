import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
// 先加载主题变量（PC 亮/暗 + 移动端亮/暗，见 assets/theme.css），再加载组件样式
import './assets/theme.css'
import './assets/styles.css'

createApp(App).use(createPinia()).use(router).mount('#app')
