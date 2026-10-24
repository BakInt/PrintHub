# PrintHub（云打印系统）- UI 适配与组件规范

本文件面向后续在本仓库开发**新功能**的开发者与编码代理，规定前端 UI 的组件体系与响应式适配约定。目标是：**新功能默认同时兼容电脑版和手机端，风格一致、布局不溢出、亮暗主题自动跟随。**

产品需求见 `doc/PRD.md`，工程结构与业务逻辑见 `doc/AGENTS.md` 第 8 节。本文件只约束 UI 呈现与响应式适配，不改变任何后端/功能逻辑。

> 2026-10 起，前端 UI 层已整体迁移到 **Tailwind CSS v4 + shadcn-vue**（reka-ui，reka-nova 风格，`typescript: false` 生成 JS 组件）。旧版「单文件手写 CSS（`theme.css` + `styles.css`，`var(--cp-*)` 变量体系）」已废弃删除；本文档描述的是迁移后的规范。

---

## 0. 铁律（务必遵守）

1. **组件外观一律来自官方组件**：页面只允许使用 `frontend/src/components/ui/*` 里 shadcn-vue CLI 生成的组件（新增用 `pnpm dlx shadcn-vue@latest add <component>`），在其基础上用 Tailwind 工具类和 CSS 变量定制。**禁止手写 CSS 复刻/模仿组件外观，禁止绕过组件直接堆原始元素**。
2. **禁止写死色值**：页面与定制类里不许出现 hex/rgba/named color。颜色一律走 `frontend/src/assets/index.css` 定义的 CSS 变量（shadcn token 与扩展 token，见第 3/5.5 节），Tailwind 工具类（`bg-card`、`text-primary`、`text-success` 等）编译后即引用这些变量。
3. **业务逻辑不动**：改 UI 时保持 `<script>` 里的接口请求、数据结构、校验与状态管理原样（`api/client.js`、`stores/*`、各视图的请求/提交逻辑是业务层）。
4. **不做平台判断**：桌面/手机布局只用 Tailwind 响应式断点切换（主断点 `md` = 768px，与 shadcn-vue Sidebar 内置的 `useMediaQuery('(max-width: 768px)')` 一致），不按 UA/平台分支；也不新增独立路由做视图拆分（沿用「路由 query 参数 + 显隐」）。
5. **全站不出现底部版权/开源提示条**：任何页面不得添加版权条、开源声明条等固定底部条（底部固定区只允许导航 Tab 栏与手机端提交栏）。**唯一例外是 ICP 备案条**（2026-10 新增，合规要求）：由 `components/layout/IcpFooter.vue` 渲染，仅当后台「站点设置」填写了备案号才出现，非固定定位、随内容排在页尾（前台在 App.vue 的 `<main>` 内，后台在 AdminView 内容底部，手机端位于底部 Tab 栏预留 padding 之上），样式限定为居中一行、`text-xs text-muted-foreground`，只显示备案号本身并链接 `https://beian.miit.gov.cn/`（新窗口），不加版权/声明等其它内容。
6. 图标统一用 `lucide-vue-next`（shadcn-vue 官方配套），尺寸用 Tailwind `size-4`/`size-5` 等统一控制，不混用 emoji 或其它图标库。

---

## 1. 断点与全局约定

使用 Tailwind 默认断点：

| 断点 | 宽度 | 用途 |
| --- | --- | --- |
| （基础） | < 640px | 手机竖屏：单列布局、底部 Tab 栏导航 |
| `sm` | ≥ 640px | 手机横屏/小平板：局部双列（如表单行、统计行） |
| `md` | ≥ 768px | **主断点**：底部 Tab 栏消失、顶部/侧边导航出现；兑换码列表从卡片折叠为表格 |
| `lg` | ≥ 1024px | 首页双栏（上传 + 设置侧栏 sticky）、个人中心双栏 |
| `xl` | ≥ 1280px | 后台指标卡 6 列、更宽的表单网格 |

- 最小视口 320px，任何页面不得出现横向滚动（兑换码等宽表格在 `md` 以下折叠为卡片列表）。
- 内容区宽度：前台 `max-w-7xl` 限宽居中（内边距 `px-3 sm:px-6`）；**后台 `/admin` 通栏不限宽**（App.vue 在 admin 路由下移除 main 的限宽与内边距，由 AdminView 自己的 SidebarInset 布局撑满，保证信息密度）。
- 排版阶梯（统一使用，不再自造字号）：
  - 页面主标题 `font-display text-2xl sm:text-3xl font-bold tracking-tight`；
  - 区块标题 `font-display text-lg/xl font-bold`；
  - 眉题 `text-[13px] font-bold tracking-widest text-primary`；
  - 正文 `text-sm`（14px），辅助文字 `text-[13px]` 或 `text-xs`（12px，仅短注释）；
  - 金额数字 `font-display tabular-nums`（Space Grotesk + 等宽数字）。
- 间距用 Tailwind spacing scale（`gap-2` / `gap-3` / `gap-4` / `gap-6`），卡片内边距 `p-3.5` / `p-4`。
- 触控目标：手机端主要按钮 `h-10`/`h-11`，底部 Tab 项 `min-h-14`，Tabs 分段控件 `h-10`（桌面可用默认 h-8/h-9）。手机端正文不小于 12px。
- 输入框字号与高度：表单输入框文字用 `text-base md:text-base`（16px，覆盖 reka-nova Input 默认的 `md:text-sm`，防止 iOS 聚焦自动放大页面）；登录/注册等独立表单页输入框 `h-11`，普通视图内 `h-10`。
- 独立表单页（登录/注册）布局：`flex min-h-[calc(100svh-…)] items-center justify-center` 让卡片在视口内水平垂直居中，卡片 `max-w-sm md:max-w-md`、内边距 `py-8 sm:px-8`，标题 `text-2xl sm:text-3xl`，行距 `gap-4 sm:gap-5`；验证码图片固定 `h-11 w-[132px] object-cover`、点击整块刷新。
- 新功能 UI 自检清单：颜色全走 CSS 变量、hover/active/focus-visible/disabled 完整、触控目标 ≥ 40px、320px 不溢出、亮暗两套都检查过、不新增底部版权条。

---

## 2. 导航结构

| 场景 | 桌面端（≥ md） | 手机端（< md） |
| --- | --- | --- |
| 前台 | `AppHeader` 顶部导航（品牌 + 打印/订单/个人中心/后台 + 主题切换 + 登录/退出） | 顶栏只留品牌 + 主题切换 + 登录/退出；导航走 `MobileTabbar` 底部三格（首页/订单/我的） |
| 后台 `/admin` | **不渲染全局 AppHeader**；shadcn `Sidebar`（`collapsible="icon"`，宽度 w-60，菜单项 `h-10 font-medium`、图标 `size-4` 与文字左对齐，`:is-active` 高亮）+ 自己的顶栏 `h-14`（左：`SidebarTrigger` + 标题 `text-sm font-medium`；右：`ThemeToggle` + 退出） | 侧边栏隐藏；后台自己的底部 Tab 栏 5 列（4 个常用 tab + 「更多」收进 `Sheet side="bottom"` 抽屉），顶栏保持 h-14 |

- 两条底部 Tab 栏互斥：`MobileTabbar` 内部用 `route.path.startsWith('/admin')` 判断，在后台路由不渲染。
- 底部 Tab 栏规格：`fixed inset-x-0 bottom-0 z-40`、`min-h-14`、`pb-[env(safe-area-inset-bottom)]` 安全区适配、毛玻璃 `backdrop-blur-md`；选中态 `text-primary` + 图标底部 `bg-primary/10` 胶囊。
- 壳层 `<main>` 的底部内边距 `pb-[calc(84px+env(safe-area-inset-bottom))] md:pb-10` 同时满足两条底部栏的高度预留。
- 导航高亮（订单/个人中心）由 `composables/useNavTargets.js` 的互斥 computed（`isOrders`/`isMine`）驱动，**不要改回 RouterLink 自带的按路径高亮**（会忽略 `?tab=` 导致两项同时点亮）。

---

## 3. 视觉风格

- 组件基座：shadcn-vue **reka-nova** 风格（`components.json` 的 `style` 字段）。Button 共 6 个 variant（default/outline/secondary/ghost/destructive/link），全部自带 hover/active/focus-visible/disabled 态——**不要覆盖掉 hover 样式**；主按钮需要更强 hover 时用 `hover:bg-primary/90` 这类增量类。
- 品牌：亮色 `--primary: #1d4ed8`（深墨蓝），暗色 `--primary: #60a5fa`；品牌渐变端点 `--brand-deep`（Logo 徽标、手机端上传区用 `bg-linear-to-br from-primary to-(--brand-deep)`）。旧版「桌面墨蓝 / 移动蓝紫」双配色已合并为一套亮/暗变量。
- 语义状态色（`index.css` 自定义 token，供 Badge/Alert 组合）：
  - 成功 `bg-success/10 text-success border-success/30`；
  - 警示 `bg-warning/15 text-warning border-warning/30`；
  - 信息/强调 `bg-accent text-accent-foreground border-primary/25`。
- 圆角：全局 `--radius: 0.75rem`，阶梯 `--radius-sm(8px)/md(10px)/lg(12px)/xl(16px)`，与旧版一致。
- 图表色板 `--chart-1..5`（蓝/琥珀/青/绿/紫），亮暗两套取值都定义在 `index.css`。
- 页面背景：`body` 有一层 `radial-gradient(... var(--brand-soft) ...)` 的品牌色晕染（亮暗各自取值），桌面 `background-attachment: fixed`、手机端 `scroll`。

> 旧版「桌面端墨蓝、移动端蓝紫两套独立配色」的约定已废止：现在亮/暗各一套变量，桌面与手机共用，只靠响应式类切换布局。

---

## 4. 同页面按 Tab/query 拆分视图

个人中心（DashboardView）沿用「单路由 + `?tab=` 拆分」模式（桌面与手机端都生效）：

- 顶部导航/底部 Tab 的「订单」→ `/user/dashboard?tab=orders`（只显示最近订单），「个人中心」→ `?tab=me`（余额/联系人/充值）。
- 实现是纯展示层的 `v-if`/class 绑定：`isOrdersTab` 时隐藏左列与充值卡、单列展示订单卡；`isMineTab` 时隐藏订单卡。**不要为拆分新增路由**。
- 后台 tabs 是纯前端状态（`tab` ref + `watch(tab, loadTab)`），不是路由，切换行为见 `doc/AGENTS.md` 第 8 节。
- 个人中心「打印联系人」在手机端已绑定且非编辑态时折叠为摘要卡（`profileCollapsed` + `max-md:hidden`/`md:hidden` 组合），桌面端始终展开表单——保持该行为。

---

## 5. 组件使用规范（shadcn-vue 组件映射）

常用交互一律用官方组件（旧手写元素 → 新组件对照）：

- 面板/卡片：旧 `.panel` → `Card`（+ `CardHeader/CardTitle/CardDescription/CardContent/CardFooter`）；
- 按钮：旧 `.primary-btn` → `Button`（默认 variant；跳转用 `as-child` 包 `RouterLink`）；旧 `.secondary-btn` → `variant="secondary"`；旧 `.icon-btn` → `size="icon-sm"` + variant；危险操作 → `variant="destructive"`；
- 输入：旧 `.input`/`.field-label` → `Input` + `Label`（手机端输入框统一 `h-10`）；旧 `<select>` → `Select` 系；
- 分段选择：旧 `.segmented` → `Tabs`（受控 `:model-value` + `@update:model-value`）。**全站统一规格**：`TabsList h-9!` + 触发器 `text-sm`、默认圆角 rounded-lg、选中态为 muted 轨道上的卡片色胶囊——同一页面出现多组 Tabs 时必须同高同字号（如每日统计的时间组与维度组）；触控要求高的独立分段控件可用 `h-10!` 加高。用于支付方式、黑白/彩色、有效期模式、打印配置模式、每日统计的时间/维度切换等；
- 勾选 → `Checkbox`；开关 → `Switch`（旧 `.toggle-switch`）；徽标 → `Badge`；提示条 → `Alert`（旧 `.notice`，语义配色见第 3 节）；
- 弹窗 → `Dialog`（旧 `.modal-overlay`）；抽屉（兑换码详情、后台「更多」）→ `Sheet`（`side="right"`/`side="bottom"`，旧 `.redemption-drawer`/`.admin-more-*`）；轻提示 → `toast`（vue-sonner，`<Toaster>` 挂在 `App.vue`）；
- 表格（桌面端兑换码列表）→ `Table` 系；空状态 → `Empty` 系（旧 `.empty-preview`）；加载 → `Skeleton` / `Spinner`；提示悬浮 → `Tooltip`；滚动区 → `ScrollArea`；
- 后台侧边栏 → `Sidebar` 系（`components/ui/sidebar/`）。

---

## 5.5 亮色/深色主题（CSS 变量 + `.dark` 类）

| 文件 | 职责 |
| --- | --- |
| `src/assets/index.css` | 唯一全局样式入口：`@import "tailwindcss"`、`@custom-variant dark`、`@font-face`（Space Grotesk）、`:root` 亮色变量块、`.dark` 暗色变量块、`@theme`/`@theme inline` 映射、base 层、主题过渡 |
| `src/stores/theme.js` | 主题状态：`localStorage['cloud-print-theme']` 优先，否则跟随系统并监听变化；`applyTheme()` 切换 `<html>` 的 `.dark` 类 + `colorScheme` |
| `index.html` | 防闪烁内联脚本：样式生效前按同一规则切换 `.dark` 类 |
| `src/components/layout/ThemeToggle.vue` | 顶栏主题切换按钮（Sun/Moon） |

- 亮色变量在 `:root`，暗色在 `.dark`，两块变量集合必须一致（shadcn 全套 + `--success`/`--warning`/`--chart-1..5`/`--brand-deep`/`--brand-soft`/`--brand-hi`）。新增颜色先加变量、再用工具类引用。
- `@theme inline` 把颜色映射成 Tailwind 色板（`--color-*: var(--*)`）；`@theme` 里定义 `--font-sans`（系统栈 + 中文回退）与 `--font-display`（Space Grotesk 优先）。
- 主题过渡：`html.theme-ready` 之后才对颜色属性开 0.25s 过渡（`theme.js` 在下一帧追加该类，避免首屏闪烁），`prefers-reduced-motion: reduce` 时关闭。
- 暗色下原生控件（日期/时间输入、滚动条）通过 `color-scheme: dark` 统一底色；图片类内容不做滤镜。

---

## 5.6 图表（shadcn-vue Chart / Unovis）

「每日数据统计」使用 shadcn-vue 官方 Chart（`components/ui/chart/`，底层 `@unovis/vue`）：

- 系列颜色只允许 `var(--chart-1)`（柱/左轴）与 `var(--chart-2)`（线/右轴），通过 `ChartContainer :config` 传入（`{ key: { label, color } }`），`ChartStyle` 会自动生成亮/暗两份 `--color-<key>`。
- 双轴：`VisStackedBar` + `VisLine` + 两个 `VisAxis`（`position="left"/"right"`），各自 `:y-domain` 由保留的 `axisMax()`/`niceMax()`（nice-number 算法）计算，柱顶留 8% 余量、全 0 时给最小刻度。
- 提示框：`ChartCrosshair :template`（内部用 `h(ChartTooltipContent, ...)` 渲染并按内容缓存 HTML，键含 tab/时间范围/日期/可见系列，切 Tab 或刷新数据后清缓存）。
- 空数据显示 `Empty` 占位（不是空白）；加载中用 Skeleton（首次）/Spinner 遮罩（刷新）；图例按钮可切换系列显隐（按「Tab+系列」记忆）。
- 时间范围切换后重新请求 `/api/admin/daily-stats?days=`，图表随响应重绘；亮/暗主题下坐标轴、图例、tooltip 的颜色全部跟随 CSS 变量（ChartContainer 内置 `.tick_text`/`.tick_line` 的主题化）。

---

## 6. 常见坑

- **不要覆盖 Button hover**：reka-nova 的 variant 自带 hover/active 态；需要调整就叠加 Tailwind 类，不要重写 variant。
- **TabsList 高度**：reka-nova 横向 TabsList 默认 `h-8`，统一加 `h-9!`（important 前缀）覆盖为 36px 规格并配 `text-sm`；触控要求高的独立分段控件可再加高到 `h-10!`。
- **底部固定层叠加顺序**：底部 Tab 栏 `z-40` > 手机端提交栏 `z-30`；壳层 `<main>` 的底部 padding 已按 Tab 栏预留，页面内不要再加 `padding-bottom`。
- **两条底部栏互斥**靠 `MobileTabbar` 的路由判断 + `AdminView` 只在自身渲染后台底部栏；别在壳层加第二个底部导航。
- 图标尺寸统一交给组件内置规则（如 `SidebarMenuButton` 的 `[&_svg]:size-4`）或显式 `size-4/size-5`，保证同行图标与文字基线对齐、严格左对齐。
- `components.json` 的 `typescript: false`：CLI 生成的组件是 `.js`/`.vue`（JS）；`sidebar` 组件因 registry 转换器对跨文件类型导入有 bug，是按官方 registry 源码（reka-nova/sidebar.json）做导入路径重写后落盘的 TS 文件（`lang="ts"`，Vite 原生支持），更新 sidebar 时注意保持一致。

---

## 7. 验证方式

本机（Windows）没有 Node，前端验证用 Docker 容器构建：

```bash
# 一次性工具链（node:22 容器，挂载 frontend 目录；pnpm 版本与 packageManager 字段一致）
docker run -d --name ph_fe -v "<仓库>/frontend:/host" node:22.18-bookworm-slim sleep infinity
docker exec ph_fe bash -c "npm i -g pnpm@12.11.2"

# 同步源码进容器并构建（在仓库的 frontend/ 目录执行）
tar cf - --exclude=node_modules --exclude=dist . | docker exec -i ph_fe bash -c "cd /work && tar xf - && pnpm install --frozen-lockfile && pnpm run build"
```

- 构建产物 `dist/` 由 FastAPI 托管（生产）；正式验证由**用户本人**重建 Docker 镜像后在真机/浏览器完成（亮/暗 × 手机/桌面四种组合、`md` 断点前后导航切换、图表亮暗配色、空态、长 token 文案溢出）。
- 本地调试可在容器里 `pnpm run dev`（Vite `/api` 代理到 `localhost:8000`）。
- `assets/fonts/space-grotesk-latin.woff2` 不许删除（Vite 打包，品牌字/数字）；`scripts/theme_*.py` 是旧 CSS 体系的检查工具，已废弃，不要再运行。

---

## 8. 相关文件索引

| 文件 | 说明 |
| --- | --- |
| `src/assets/index.css` | 全局样式 + 主题变量（唯一入口） |
| `src/assets/fonts/` | 自托管 Space Grotesk（latin 子集） |
| `src/App.vue` | 全局壳（Header/Tabbar/Toaster） |
| `src/components/layout/` | AppHeader / MobileTabbar / ThemeToggle / IcpFooter（ICP 备案条，仅后台配置了备案号才渲染） |
| `src/components/ui/` | shadcn-vue 官方组件（CLI 生成） |
| `src/components/DailyStatsCard.vue` | 每日数据统计（shadcn Chart） |
| `src/composables/useNavTargets.js` | 导航目标与互斥高亮 |
| `src/lib/utils.js` | `cn()`（clsx + tailwind-merge） |
| `src/stores/theme.js` | 主题状态与切换 |
| `src/stores/site.js` | 站点配置（标题/favicon/备案号）：启动时拉取 `/api/site-settings` 并全局应用（`document.title` + 替换唯一 `<link rel="icon">`；未配置回退 index.html 默认值） |
| `src/views/*.vue` | 五个页面视图 |
| `index.html` | 防闪烁脚本、meta、favicon |
| `components.json` / `jsconfig.json` / `vite.config.js` | shadcn-vue CLI、路径别名、Tailwind 插件 |
| `pnpm-workspace.yaml` | `minimumReleaseAge: 0`（构建可复现） |

---

## 9. 后台入口安全约定

后台入口保持三层防护，缺一不可（迁移未改动）：

1. 顶栏/侧边栏入口 `v-if="auth.user?.is_admin"` 只对管理员渲染；
2. 路由守卫 `meta: { requiresAdmin: true }` + `ensureLoaded()` 校验；
3. 后端 `admin_user()` 依赖校验（前端隐藏只是体验层）。

> 任何 UI 改动都不得绕过这三层，例如「为了演示方便」临时放开路由守卫。

---

## 10. 列表分页加载

订单列表、兑换码列表沿用后端真分页：`{items,total,has_more,total_spent}` + `limit/offset`，前端「加载更多」按钮（`hasMore` 控制、`loadingMore` 防重复、按 id 去重追加）。UI 上「加载更多」用 `Button variant="secondary"` 全宽，全部加载完显示一行「已显示全部订单」文案。
