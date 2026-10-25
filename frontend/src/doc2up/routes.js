// 两页合一模块路由清单：router/index.js 一次性引入（隔离钩子）。
// 路由规则：所有功能模块页统一挂在 /cert/ 下，后缀 = 模块 code 的 kebab-case
//（id_card→id-card、hukou→hukou、doc2up→doc-2up）；门户 /cert，证件照管理在
// AdminView「证件照管理」tab 内（无独立管理路由）。
import Doc2UpModule from './Doc2UpModule.vue'

export default [{ path: '/cert/doc-2up', component: Doc2UpModule }]
