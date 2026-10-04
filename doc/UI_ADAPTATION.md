# PrintHub（云打印系统）- UI 适配开发规范

本文件面向后续在本仓库开发**新功能**的开发者与编码代理，规定前端 UI（尤其是手机端）的适配约定。目标是：**新功能默认同时兼容电脑版和手机端，风格一致、布局不溢出、桌面端不被手机端改动波及。**

产品需求见 `documents/PRD.md`，工程结构与业务逻辑见 `AGENTS.md`。本文件只约束 UI 呈现与响应式适配，不改变任何后端/功能逻辑。

---

## 0. 铁律（务必遵守）

1. **只用 media query 做手机端适配**，不要为了手机端去改桌面基础样式。手机端专用元素在桌面基础样式里默认隐藏（`display: none`），仅在手机断点内显示。这样能保证「改手机端 ≠ 影响电脑版」。
2. **不为 UI 适配改功能代码**。Tab 切换、视图拆分等一律靠「路由 query 参数 + CSS 显隐」实现，不新增后端接口、不改业务流程。
3. **不新增独立路由来做手机端视图拆分**，优先「同页面内按 query 参数 + CSS 控制显隐」。
4. **本机 Windows 环境无 node/npm**，无法 `npm run build` 或本地起前端。改动后由**用户本人**在重建 Docker 前端镜像后于真机/移动模拟器验证；代理不主动启动浏览器测试。
5. 所有样式集中在 `frontend/src/assets/styles.css`，遵循现有「单行规则、类名语义化」的写法，不要引入新的 CSS 方案（CSS-in-JS、Tailwind、scoped 重写等）。

---

## 1. 断点与全局约定

`styles.css` 采用移动优先之外的「桌面为主 + 向下覆盖」策略，现有断点如下：

| 断点 | 用途 |
| --- | --- |
| 默认（无 media query） | 电脑版 / 大屏基础样式 |
| `@media (max-width: 1200px)` | 中等屏，表格类多列降级 |
| `@media (max-width: 1023px)` | 平板 / 窄屏，多栏网格改单栏 |
| `@media (max-width: 767px)` | **手机端主断点**（大部分手机适配写这里） |
| `@media (max-width: 420px)` | 超小屏手机的微调（如超窄机型、字号/按钮再收紧） |

- 最小支持宽度：`body { min-width: 320px }`。任何新组件在 320px 宽下不得出现横向滚动或元素被裁切。
- 全局盒模型 `* { box-sizing: border-box }` 已开启。
- 页面主容器 `main` 在手机端已预留底部安全空间（见第 2 节底部 Tab 栏），新页面无需再单独处理。

### 新功能 UI 自检清单
- [ ] 桌面端在 ≥1024px 下布局与改动前一致（若新增页面，风格与现有 `.panel`/`.section-heading` 一致）
- [ ] 767px、420px、320px 三个宽度下无横向溢出、无重叠、无被 Tab/底部栏遮挡
- [ ] 长文本（文件名、订单号等）用 `overflow-wrap: anywhere` 处理，不撑破容器
- [ ] 触控目标（按钮、可点区域）手机端最小高度 ≥ 44px
- [ ] 固定定位元素处理了 `env(safe-area-inset-*)`（刘海屏/底部手势条）

---

## 2. 手机端底部 Tab 导航栏

底部 Tab 栏是手机端的核心导航，定义在 `App.vue`，样式在 `styles.css`。

- 结构：`<nav class="mobile-tabbar">`，三个 `.tab-item`（首页 / 订单 / 我的），图标使用 `lucide-vue-next` 的 `Home` / `ClipboardList` / `User`。
- **桌面端默认隐藏**：`.mobile-tabbar { display: none }`（基础规则），仅在 `@media (max-width: 767px)` 内 `display: grid` 显示。
- 导航复用现有路由，不新增功能：
  - 首页 → `/`
  - 订单 → 登录用户 `/user/dashboard?tab=orders`，未登录 `/login`
  - 我的 → 登录用户 `/user/dashboard?tab=me`，未登录 `/login`
- 高亮态按 `route.path` + `route.query.tab` 判断，加 `.active` 类。
- `main` 在手机端底部 padding 预留 `78px + env(safe-area-inset-bottom)`；任何固定在底部的操作栏（如提交栏）必须落在 Tab 栏**之上**（示例：`.mobile-submit-bar` 用 `bottom: calc(68px + env(safe-area-inset-bottom))`）。

### 新增一个底部 Tab 项时
1. 在 `App.vue` 的 `.mobile-tabbar` 内加一个 `.tab-item`，用 lucide 图标 + 文案。
2. 若指向已有页面的不同视图，用 query 参数区分（见第 4 节），不要新建路由。
3. `.mobile-tabbar` 的 `grid-template-columns` 从 `repeat(3, 1fr)` 相应改为对应列数。
4. 更新对应的 `.active` 高亮判断。

---

## 3. 视觉风格（贴合参考图的蓝紫风）

手机端整体采用蓝紫渐变风格，色板如下（仅手机端使用；桌面端沿用既有蓝色体系 `#2563eb` 等，不要改）：

| 用途 | 颜色 |
| --- | --- |
| 主色 / 强调 | `#4f46e5` |
| 渐变主色 | `linear-gradient(135deg, #4f46e5, #6366f1)` |
| 渐变高光 | `#818cf8` |
| 深色文字强调 | `#4338ca` |
| 选中底色 | `#eef2ff` |
| 卡片描边 | `#e0e7ff` / `#e6e9f5` |

规范：
- 卡片圆角：手机端 `.panel` 用 `border-radius: 16px`；主卡片（上传区）可到 `20px`；小控件 `12px`。
- **主按钮**（`.primary-btn`）手机端用蓝紫渐变 + 圆角 `12px` + 轻投影；最小高度 46px。
- **分段选择器**（`.segmented`，如色彩/纸张/双面/支付方式）手机端做成圆角胶囊：按钮 `border-radius: 12px`，选中态 `.selected` 用 `background: #eef2ff; color: #4f46e5; box-shadow: inset 0 0 0 1px #4f46e5`。
- 上传区 `.dropzone` 手机端为蓝紫渐变主卡片（白字），是首页视觉焦点。
- 促销条 `.promo-banner` 手机端走浅紫底 + 紫色描边。
- 首页三步引导 `.empty-state-grid` 在手机端隐藏（`display: none`）以节省空间，仅电脑版/平板显示。

> 新组件若含"选择/切换"类交互，优先复用 `.segmented` 的胶囊样式，保持一致，不要自造按钮组风格。

---

## 4. 同页面内按 Tab / query 拆分视图（重要模式）

当一个页面在电脑上要**整页展示所有内容**、但手机端要**按底部 Tab 拆成几屏**时，用以下模式（已在个人中心 `DashboardView.vue` 落地，可直接参考）：

**步骤：**
1. 底部 Tab 用 query 参数指向同一路由的不同视图，例如 `/user/dashboard?tab=orders` 与 `?tab=me`。
2. 页面根元素绑定一个由 `route.query.tab` 派生的 class：
   ```js
   const mobileTabClass = computed(() => (route.query.tab === 'orders' ? 'mobile-tab-orders' : 'mobile-tab-me'))
   ```
   ```html
   <section class="account-dashboard" :class="mobileTabClass">
   ```
3. 给各内容块加稳定的语义类（如 `.orders-panel`）。
4. **仅在手机断点内**用这些组合类控制显隐：
   ```css
   @media (max-width: 767px) {
     .account-dashboard.mobile-tab-orders .account-sidebar,
     .account-dashboard.mobile-tab-orders .recharge-panel { display: none; }
     .account-dashboard.mobile-tab-me .orders-panel { display: none; }
   }
   ```

**要点：**
- 这些 `.mobile-tab-*` 规则**必须写在 media query 内**，桌面端因此忽略该类、始终整页显示 → 电脑版零变化。
- 只做「显隐」，不卸载组件、不改数据加载逻辑，切 Tab 无需重新请求。
- 视图切换靠 Vue Router 的 query 响应式，同一组件实例内 computed 自动重算，不重新 mount。

### 4.1 例外：个人中心桌面端也按 Tab 拆分（`DashboardView.vue`）

按用户明确要求，个人中心 `DashboardView.vue` 的「订单 / 个人中心」拆分**在桌面端也生效**（不再整页展示），是对上面「仅手机端拆分」约定的一个**明确例外**：

- `.account-dashboard.mobile-tab-*` 的显隐规则被提到 **media query 外**（`styles.css` 桌面基础样式区，`.account-dashboard` 定义之后），桌面与手机端共用同一套拆分。
- `?tab=orders` → 只显示 `.orders-panel`（最近订单），并把 `.account-dashboard` 网格改为单栏 `grid-template-columns: 1fr`（隐藏左侧 `.account-sidebar` 后不留空栏）。
- `?tab=me` 或无 `tab`（默认）→ 隐藏 `.orders-panel`，显示余额/联系人/充值等其余内容。
- 桌面顶部 `header` 与手机端底部 Tab 复用同一组导航目标（见 `App.vue` 的 `ordersTarget` / `mineTarget`），两者都带显式 `?tab=orders` / `?tab=me`。

**导航高亮坑（务必注意）：** 顶部「订单」「个人中心」指向的是**同一路由 `/user/dashboard` 只是 query 不同**。`RouterLink` 默认按**路径**匹配高亮、**忽略 query**，会导致两个链接在任一子 tab 下**同时高亮**，甚至内容判断错乱。正确做法：

- 两个链接仍用**普通 `RouterLink`**（保证 `<a href>` 可点击跳转，不要用 `custom` slot + `@click.prevent` 自造 `<a href="#">`，那样会导致点击失效——已踩过坑）。
- 给它们加 `active-class="nav-no-auto"` `exact-active-class="nav-no-auto"`，把 RouterLink 自动高亮类改名到一个**无样式类**，等于禁用其按路径自动高亮。
- 高亮改由 `:class="{ 'router-link-active': isOrders }"` / `isMine` 手动控制，`isOrders`/`isMine` 为**互斥** computed，任一时刻只亮一个。

> 注意：这是针对个人中心的定向例外。**其他页面**仍遵循第 0 节铁律与本节主流程（仅手机端拆分、桌面整页展示），不要照搬本例外把桌面基础样式改成拆分。

### 4.2 「填一次就折叠」表单模式（`DashboardView.vue` 打印联系人）

当某个设置类表单**填过一次后不常改**（如打印联系人），可折叠为一张摘要卡 + 「修改」按钮，点按钮再展开表单编辑。按用户要求，此折叠**桌面端与手机端均生效**（是第 0 节「仅手机端适配」的又一处定向例外，同 4.1）：

**步骤（以 `.profile-panel` 为例）：**
1. 脚本加编辑态开关和折叠 computed：
   ```js
   const editingProfile = ref(false)
   // 已完成绑定且未在编辑 → 折叠
   const profileCollapsed = computed(() => profileComplete.value && !editingProfile.value)
   ```
2. 模板：折叠摘要卡（姓名 + 打码手机号 + 「修改」按钮）与完整表单**同时渲染**，靠 CSS 显隐；「修改」`startEditProfile()` 置 `editingProfile=true`，「取消」`cancelEditProfile()` 复位并同步表单，保存成功后 `editingProfile=false` 自动折叠回摘要卡。
3. 面板根节点绑定 `:class="{ 'profile-collapsed': profileCollapsed }"`。
4. CSS 写在**桌面基础层**（两端共用，不放进 media query）：
   ```css
   .profile-summary { display: none; }                                   /* 缺省关闭 */
   .profile-panel .profile-summary { display: grid; }                    /* 面板内开启 */
   .profile-panel.profile-collapsed .profile-form { display: none; }     /* 折叠时藏表单 */
   .profile-panel:not(.profile-collapsed) .profile-summary { display: none; } /* 编辑/未绑定藏摘要卡 */
   ```

**要点：**
- 手机号等敏感信息在摘要卡里打码显示（如 `138****8888`）。
- 折叠只做显隐，不卸载表单、不清空 `profileForm`；「取消」要 `syncProfileForm()` 还原用户已保存值。
- 未完整绑定（缺姓名或手机号非法）时 `profileCollapsed=false`，两端都直接显示完整表单，方便首次填写。



---

## 5. 固定底部操作栏

某些页面（如首页下单）需要手机端固定在底部的操作栏：

- 桌面端隐藏（基础规则 `display: none`），手机端 `position: fixed`。
- 必须堆叠在**底部 Tab 栏之上**（`bottom` 至少留出 Tab 栏高度 60px + 间距 + safe-area），`z-index` 低于 Tab 栏（Tab 栏用 `z-index: 40`，操作栏用 `30`）。
- 处理 `env(safe-area-inset-bottom)`。
- 对应内容区要有 `padding-bottom` 兜底，避免最后一屏内容被两条固定栏遮住。

参考实现：`.mobile-submit-bar`（首页金额 + 去支付）。

---

## 6. 常见坑

- **不要**为了手机端把桌面基础样式里的颜色/圆角直接改掉——会污染电脑版。改动只进 media query。
- **不要**用固定像素宽度做手机端多列布局；用 `grid-template-columns: 1fr` 或 `minmax(0, 1fr)`，避免 320px 溢出。
- **不要**忘了固定栏叠加：新增任何 `position: fixed` 的底部元素，先算好它和底部 Tab 栏的高度关系。
- 图标统一用 `lucide-vue-next`，不要混入 emoji 作为功能图标（品牌装饰性 emoji 除外）。
- 手机端隐藏了顶部导航文字入口，导航由底部 Tab 承担；新功能的主入口应考虑挂到底部 Tab 或页面内，而非只放在桌面顶部导航。

---

## 7. 验证方式（本仓库特有）

1. 本机无 node/npm，**不要**假设能本地 `npm run build`；正在跑的服务端口可能是旧 Docker 产物。
2. 改完前端后需**重建 Docker 前端镜像**，UI 实测由用户本人在手机真机/浏览器移动模拟器完成。
3. 代理侧的验证限于：CSS 语法/括号平衡、类名与结构一致性、断点覆盖是否遗漏、桌面基础样式是否被误改。

---

## 8. 相关文件索引

- 底部 Tab 栏与全局壳、顶部导航：`frontend/src/App.vue`
- 全部样式（含所有断点与手机端规则）：`frontend/src/assets/styles.css`
- 首页（上传/打印设置/固定提交栏）：`frontend/src/views/HomeView.vue`
- 个人中心（Tab 拆分、联系人折叠、订单分页示例）：`frontend/src/views/DashboardView.vue`
- 订单进度 / 收银台：`frontend/src/views/PaymentView.vue`
- 登录注册：`frontend/src/views/AuthView.vue`
- 后台（单页多 tab）：`frontend/src/views/AdminView.vue`
- 路由守卫（`requiresAdmin`）：`frontend/src/router/index.js`

---

## 9. 后台入口的安全约定（不可削减）

「后台」入口与后台数据涉及权限，必须保持**三层防护**，新增导航/入口时不得只做其中一层：

1. **前端隐藏入口**：顶部导航「后台」链接用 `v-if="auth.user?.is_admin"`，普通用户/未登录**不渲染**该入口（`App.vue`）。这是体验层，不是安全边界。
2. **前端路由守卫**：`/admin` 路由带 `meta: { requiresAdmin: true }`，`router.beforeEach` 校验 `user.is_admin`，未登录/非管理员一律跳 `/login`（`router/index.js`）。
3. **后端接口鉴权（真正边界）**：所有 `/api/admin/*` 经 `admin_user()` 校验 `is_admin`，普通用户 403。即使前端被绕过也不泄露后台数据。

> 隐藏入口只是"看不见"，真正安全靠后端鉴权。三层缺一不可；新增任何后台相关入口或接口，务必同时补齐前端 `v-if`、路由守卫与后端 `admin_user()` 校验。

---

## 10. 列表分页加载（订单列表示例）

数据量可能增长的列表（如个人中心订单）用「加载更多」分页，避免一次拉全量导致卡顿。已在 `DashboardView.vue` + `GET /api/user/orders` 落地，两端交互一致：

- **后端真分页**：`GET /api/user/orders?limit=10&offset=N`（`limit` 1–50、默认 10），返回 `{ items, total, has_more, total_spent }`。`total_spent`/`total` 为全量统计，不随分页变化，供前端统计展示。
- **前端**：首屏 `fetchFirstPage()` 只加载 10 条；底部「加载更多」`loadMoreOrders()` 以 `offset=orders.length` 追加 10 条。
- **加载态**：`loadingMore` 期间按钮转圈 + "加载中…" 并禁用。
- **无更多**：`has_more=false` 时隐藏按钮、显示"已显示全部订单"。
- **防重复请求**：`loadingMore` 标志位 + `!hasMore` 提前返回；追加时按订单 id 去重。
- 手机端「加载更多」按钮做全宽 + 触控高度优化（`.orders-more`/`.load-more-btn`，见 `styles.css`）；桌面端与手机端同组件，交互天然一致。

> 新增其他分页列表时复用此模式：后端返回 `{items,total,has_more}`，前端用同一套 `loadingMore`/`hasMore`/去重逻辑，样式复用 `.load-more-btn`。

