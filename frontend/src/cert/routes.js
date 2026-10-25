// cert 模块路由清单：本地维护，router/index.js 一次性引入（隔离钩子）。
// 新增一个证照功能 = 1 个模块页文件 + 这里 1 行注册 + 1 条模板数据，主程序零改动。
// 证件照管理已并入 AdminView「证件照管理」tab（CertAdminPanel.vue），无独立路由。
import CertPortal from './CertPortal.vue'
import IdCardModule from './modules/IdCardModule.vue'
import HukouModule from './modules/HukouModule.vue'

export default [
  { path: '/cert', component: CertPortal },
  { path: '/cert/id-card', component: IdCardModule },
  { path: '/cert/hukou', component: HukouModule },
]
