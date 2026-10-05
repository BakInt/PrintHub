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
- [ ] 同一页面手机端**只有一条**底部固定栏（前台 `.mobile-tabbar` 与后台 `.admin-tabbar` 互斥，见第 2.1 节）
- [ ] 新增样式**没有写死颜色**，全部走 `var(--cp-*)`；在亮色与深色下都检查过对比度（见第 5.5 节）

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

### 2.1 后台（`/admin`）的独立底部 Tab 栏

后台是单页多 tab（`AdminView.vue`，共 8 个 tab：概览/订单/用户/配置/支付/兑换码/备份/打印机），手机端原先把 8 个 tab 压成顶部横向滚动条，窄屏看不全，因此改为**后台自己的底部 Tab 栏**：

- 结构：`<nav class="admin-tabbar">`，`grid-template-columns: repeat(5, 1fr)`。前 4 格是常用 tab（`.admin-tab-item`，图标 + 文字），第 5 格是「更多」按钮；其余 4 个 tab 收进「更多」面板（`.admin-more-mask` 遮罩 + `.admin-more-sheet` 抽屉，内含 `.admin-more-item` 与返回前台的 `.admin-more-back` → `/`）。
- **桌面端零变化**：`.admin-tabbar` / `.admin-more-mask` 的基础规则是 `display: none`，仅 `@media (max-width: 767px)` 内显示；桌面端仍由左侧 `.admin-menu` 展示全部 8 个 tab，手机端 767px 内 `.admin-menu { display: none }`。
- **切换行为不变**：两端共用同一个 `tab` ref 与 `loadTab()`（`watch(tab, loadTab)`）。底部栏点击调用 `selectTab(key)`，只做 `tab.value = key; moreOpen.value = false`，**不涉及路由跳转**，与点桌面 `.admin-menu` 按钮完全等价。
- **一条页面只允许一条底部栏**：`App.vue` 给外壳绑定 `:class="{ 'app-shell-admin': isAdminRoute }"`（`isAdminRoute = route.path.startsWith('/admin')`），`styles.css` 在 767px 内用 `.app-shell-admin .mobile-tabbar { display: none }` 隐藏前台的「首页/订单/我的」底部栏。新增「自带底部栏」的页面时照此互斥。
- **安全区**：`height: calc(60px + env(safe-area-inset-bottom))` + `padding-bottom: env(safe-area-inset-bottom)`，与前台 Tab 栏同高，因此 `main` 既有的底部 `padding` 预留无需改动。
- **层级约定**：底部 Tab 栏 `z-index: 40`，固定底部操作栏 `30`（`.mobile-submit-bar`），「更多」遮罩 `39`（**低于** Tab 栏，遮罩不挡 Tab 栏本身），二级抽屉（`.redemption-drawer-overlay`）`110`。
- 手机端顶栏导航文字入口被隐藏（第 6 节），所以后台页返回前台首页的入口放在「更多」面板底部（`.admin-more-back`）。

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

## 5.5 亮色 / 深色主题（PC 与移动端两套独立配色）

系统支持亮色与深色两种主题，**PC 电脑端与移动手机端各有独立的亮/暗 palette，不共用一套 CSS 控制两端**。这是硬要求，新增功能必须按同一套机制接入。

### 文件与加载顺序

| 文件 | 职责 |
| --- | --- |
| `frontend/src/assets/theme.css` | 只放主题变量（4 套 palette），不放组件规则 |
| `frontend/src/assets/styles.css` | 组件规则，颜色**一律**写成 `var(--cp-*)`，不出现写死 hex/rgba |
| `frontend/src/stores/theme.js` | Pinia store：读写 localStorage、跟随系统、监听视口宽度 |
| `frontend/index.html` | `<head>` 内联脚本，样式生效前写入 `data-theme`，防止首屏闪白/闪黑 |

`frontend/src/main.js` 必须先 `import './assets/theme.css'`，再 `import './assets/styles.css'`（变量在前，否则首帧无值）。

### 四套 palette（`theme.css` 的四个块）

```css
:root { ... }                                            /* PC 电脑端 · 亮色 */
:root[data-theme='dark'] { ... }                         /* PC 电脑端 · 深色 */
@media (max-width: 767px) { :root { ... } }              /* 移动手机端 · 亮色 */
@media (max-width: 767px) { :root[data-theme='dark'] { ... } } /* 移动手机端 · 深色 */
```

设备判定用**视口宽度**（与第 1 节断点一致，手机主断点 767px），判定结果与 `stores/theme.js` 的 `MOBILE_QUERY = '(max-width: 767px)'` 必须保持同一个值。手机端 palette 用的是手机端蓝紫风配色（主色 `#4f46e5` 系），PC 端沿用桌面蓝色体系（`#2563eb` 系），两端互不影响。

**四个块必须各自完整**：每个 palette 都要把全部 67 个变量写全（当前实测：PC 亮 67 / PC 深 67 / 移动亮 67 / 移动深 67，定义集合完全一致）。**不要依赖「移动端没写的从 `:root` 继承」**——那等于让手机端跟着 PC 端变，违反「两套独立配色」。新增变量时四个块一起加，缺一个就会在「该设备 + 该主题」组合下取到空值（表现为控件透明、文字看不见）。可用 `python scripts/theme_audit.py` 一键核对：它会列出四个 palette 的定义差集、使用了但没定义的变量、以及漏写 `var()` 的裸变量。

### 变量命名（`--cp-` 前缀）

- 品牌：`--cp-brand` `--cp-brand-strong` `--cp-brand-deep` `--cp-brand-text` `--cp-brand-border` `--cp-brand-soft` `--cp-brand-softer` `--cp-brand-emphasis` `--cp-brand-bright` `--cp-brand-mid` `--cp-brand-hi` `--cp-accent-deep`
- 中性/表面：`--cp-app-bg` `--cp-surface` `--cp-surface-glass` `--cp-soft` `--cp-softer`
- 边框：`--cp-border` `--cp-border-soft` `--cp-border-mid` `--cp-border-input`
- 文字（对比度由强到弱）：`--cp-ink-title` `--cp-ink-strong` `--cp-ink-body` `--cp-ink-sub` `--cp-ink-muted`
- 阴影/遮罩：`--cp-shadow-1` `--cp-shadow-3` `--cp-shadow-4` `--cp-shadow-5` `--cp-shadow-6` `--cp-shadow-brand` `--cp-shadow-brand-lg` `--cp-shadow-button` `--cp-shadow-tabbar` `--cp-swatch-inset` `--cp-overlay`
- 反白/半透明白（只用于深色渐变主色块上的文字与图标）：`--cp-white-soft` `--cp-white-dim`
- 状态：`--cp-success*` `--cp-warn` `--cp-warn-soft` `--cp-danger*`（含 `-soft`/`-border`/`-chip` 等变体）
- 渐变/色卡：`--cp-gradient-intro` `--cp-gradient-soft` `--cp-gradient-drop` `--cp-gradient-drop-2` `--cp-chip-accent` `--cp-swatch-red|amber|green|cyan|purple`
- 媒体：`--cp-img-filter`（亮色 `none`，深色 `brightness(0.92) contrast(1.04)`）、`--cp-preview-bg`（iframe/PDF 预览底色）

### 写新样式时的硬规则

1. **禁止写死颜色**。新增规则里出现 `#rrggbb`、`rgb()`、`rgba()` 即为不合格；一切颜色（含阴影、渐变端点、placeholder、边框、hover 底色）都走 `var(--cp-*)`。
2. **不要为了深色去写 `.xxx { color: #fff }`**。同一份规则在亮/暗下都由变量决定；只有确实需要「结构变化」的才写 `:root[data-theme='dark'] .xxx`。
3. **深色下阴影要重做，不要照搬亮色阴影**：亮色阴影是「深色低透明度投影」，深色下改成更暗更实的投影（已由 `--cp-shadow-*` 承载），照搬会让控件发灰、发脏。
4. **hint/辅助文字不许用低到看不清的透明度**。深色下辅助文字统一取 `--cp-ink-sub`，不要再叠加 `opacity: .5` 之类的写法；两个主题都要保证正文与背景有足够对比。
5. **图片/图标不改文件**，统一靠 CSS 滤镜：`img { filter: var(--cp-img-filter) }` 已在深色专项段落统一处理（`html[data-theme='dark'] img`）。验证码这类「浅底深字」的特殊图另写反向滤镜（`.captcha-button img { filter: invert(1) hue-rotate(180deg) }`）。lucide 图标用 `currentColor`，跟随文字色即可，不要额外加滤镜。
6. **iframe/PDF 预览**必须给底色 `background: var(--cp-preview-bg)`，否则深色下会出现刺眼白块。
7. **表单/滚动条**：`input`/`select`/`textarea` 的底色、文字、`::placeholder`、`select option`、`accent-color`、`scrollbar-color`、`::-webkit-scrollbar*` 都已在深色专项段落里统一处理；新增自定义输入控件（如 `.key-input`）要自己补一条。
8. **过渡动画只在切换时生效**：`html.theme-ready` 才开启 0.25s 的颜色过渡（类名由 store 在首帧后加），`prefers-reduced-motion` 下关闭。首屏不加过渡，避免进场时整体闪一下。

### 主题状态（`stores/theme.js`）

- 优先级：**localStorage（`cloud-print-theme`，值 `light`/`dark`）> 系统偏好（`prefers-color-scheme`）**。未手动选择过时跟随系统并实时监听系统变化；用户点过切换后写 localStorage，不再跟随系统。
- 切换入口在 `App.vue` 顶部导航（`.theme-toggle`，桌面为文字胶囊，手机端 767px 内为 36×36 圆形图标按钮）。切换立即全局生效，无需刷新。
- 新增需要「按设备/按主题」分支的逻辑时，用 store 暴露的 `theme`/`isDark`/`isMobile`，不要自己再写一份 `matchMedia`。

---

## 5.6 横向可滑动的 Tab 条（窄屏放不下时）

一排 Tab / 分段按钮在窄屏放不下时，**不要**把它挪位置或改成下拉，而是保持原位置、只加横向滑动能力。参考实现：后台概览「每日数据统计」卡片的三个维度 Tab `.daily-stats-tabs`（订单趋势 / 收入趋势 / 打印失败分布），桌面端仍是 `display: flex; flex-wrap: wrap` 换行，手机端只加滑动：

```css
@media (max-width: 767px) {
  .daily-stats-tabs {
    display: grid; grid-auto-flow: column; grid-auto-columns: max-content; gap: 8px;
    padding: 0 2px 2px;
    overflow-x: auto; overflow-y: hidden;      /* 只横向滚，不产生纵向滚动条 */
    scrollbar-width: none;                     /* Firefox 隐藏滚动条 */
    -webkit-overflow-scrolling: touch;         /* iOS 触摸惯性 / 回弹 */
    overscroll-behavior-x: contain;            /* 滑到头不带动页面滚动、不触发浏览器返回手势 */
    scroll-snap-type: x proximity;             /* 松手停在按钮边缘 */
    -webkit-mask-image: linear-gradient(to right, transparent 0, black 8px, black calc(100% - 14px), transparent 100%);
            mask-image: linear-gradient(to right, transparent 0, black 8px, black calc(100% - 14px), transparent 100%);
  }
  .daily-stats-tabs::-webkit-scrollbar { display: none; }
  .daily-stats-tab { white-space: nowrap; scroll-snap-align: start; }
}
```

要点：

- **只加在 767px 内**，桌面端基础样式保持 `flex-wrap: wrap` 换行，电脑版零变化。
- `overscroll-behavior-x: contain` 是「横向滑动不与页面垂直滚动 / 返回手势冲突」的关键，**不要**用 `overscroll-behavior: none`（会连带禁掉纵向）。
- 两侧渐变遮罩提示「还能滑动」，用 `transparent` / `black` 关键字即可；**不要**写 `rgba()`/hex，`scripts/theme_check.py` 会把 `styles.css` 里的写死颜色判为不合格。
- 用 `scroll-snap-type: x proximity` 而不是 `mandatory`：`mandatory` 在窄屏下会强制吸附，滚动不足半个按钮时松手回弹，手感发"粘"。
- 若同一屏还有固定底部栏（第 5 节），横向滑动条不需要额外留位；内容区仍由 `main` 的底部 padding 兜底。

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
4. 主题相关改动另需静态核查：`styles.css` 里是否残留写死 `#hex`/`rgba()`、`var(--cp-*)` 是否都在 `theme.css` 里有定义、**四个 palette 块的定义集合是否完全一致**（缺一个就会在对应场景下取到空值）。`scripts/` 下有 `theme_check.py`（变量定义/使用差集、残留写死颜色、括号平衡）、`theme_audit.py`（四个 palette 的定义差集、未定义引用、漏写 `var()` 的裸变量）与 `theme_class_audit.py`（模板 class 是否有对应规则）可复跑。

---

## 8. 相关文件索引

- 底部 Tab 栏与全局壳、顶部导航、主题切换按钮：`frontend/src/App.vue`
- 全部样式（含所有断点与手机端规则）：`frontend/src/assets/styles.css`
- 主题变量（PC/移动端 × 亮/暗 四套 palette）：`frontend/src/assets/theme.css`
- 主题状态（localStorage / 跟随系统 / 视口判定）：`frontend/src/stores/theme.js`
- 首屏防闪烁内联脚本（写入 `data-theme`）：`frontend/index.html`
- 首页（上传/打印设置/固定提交栏）：`frontend/src/views/HomeView.vue`
- 个人中心（Tab 拆分、联系人折叠、订单分页示例）：`frontend/src/views/DashboardView.vue`
- 订单进度 / 收银台：`frontend/src/views/PaymentView.vue`
- 登录注册：`frontend/src/views/AuthView.vue`
- 后台（单页多 tab，含手机端底部 Tab 栏与「更多」面板）：`frontend/src/views/AdminView.vue`
- 后台概览「每日数据统计」卡片（内联 SVG 图表、维度 Tab 横向滑动）：`frontend/src/components/DailyStatsCard.vue`
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

