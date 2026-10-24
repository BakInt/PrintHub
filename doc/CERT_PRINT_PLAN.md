# 证照模板打印模块（形态 A · 模块化页面版）完整实施方案

> 版本：v3（合并「自包含目录架构」与「模块化页面设计」，为当前最新方案）。
> 状态：方案文档，**未实现任何代码**。实现时以本文为需求依据；实现完成后按仓库惯例将功能说明回写 `doc/PRD.md` 与 `doc/AGENTS.md`。
> 适用范围：在现有 PrintHub 云打印系统（FastAPI + Vue 3 单容器架构）内新增独立的「证照打印」模块。

## 0. 方案要点（TL;DR）

- **功能定位**：用户在证照门户选择功能卡片（身份证正反面打印、户口本打印等）→ 进入该功能的独立模块页 → 拍摄/上传证件照片 → 系统自动裁剪矫正 → 按模板排成**尺寸精确的标准打印件**（如身份证正反面同页 A4、1:1 实际尺寸）→ 点「确认打印」完成余额校验、扣费、派发打印。
- **架构形态**：现有系统内的独立模块（形态 A）。登录态、余额、订单、打印管线全部复用，无跨系统 SSO。
- **硬性约束**：新增文件 100% 集中在 `backend/app/cert/` 与 `frontend/src/cert/` 两个目录；主程序文件只允许出现预算表内的「必要钩子」（合计约 10–20 行）；可整体回滚。
- **模块化原则**：一个打印功能 = 一个独立页面模块文件（身份证正反面打印一个模块、户口本打印一个模块），模块间零引用，共享能力下沉到公共骨架与基础组件；门户页完全由模板数据驱动。
- **首发范围**：3 个模块页（身份证正反面 / 户口本个人页 / 户口本户主页）+ 门户页 + 余额一键打印 + 隐私即删。
- **隐私红线**：证件原始照片不落盘持久化；生成件默认保留 24 小时自动清理；页面知情确认声明。

## 1. 隔离架构总则（硬性约束）

### 1.1 两条铁律

1. **新文件只进两个目录**：后端 `backend/app/cert/`，前端 `frontend/src/cert/`。主程序目录内零新增文件（唯一例外：`backend/tests/cert_feature_test.py` 测试文件，遵循仓库测试目录约定，属新增而非修改）。
2. **主程序只留必要钩子**：对现有文件的每一处改动都必须出现在 1.3 预算表内；预算表之外的现有文件一律不动。

### 1.2 目录规划

后端（全部新文件）：

```text
backend/app/cert/
├── __init__.py          # 模块门面：只导出 router / admin_router / ensure_schema / start_cleanup_scheduler
├── router.py            # 用户侧路由 /api/cert/*（templates、generate、docs、docs/{id}/preview、删除）
├── admin_router.py      # 管理侧路由 /api/admin/cert-templates/* 与 /api/admin/cert-settings
├── schema.py            # cert_templates / cert_docs 建表 + 内置模板与设置键播种（自持迁移，幂等）
├── templates_seed.py    # 内置模板 layout_json 数据（含门户卡片元数据，唯一维护入口）
├── service.py           # 业务逻辑：generate 校验/每日上限/入库、docs 查询、属主校验
├── render.py            # 图像管线：EXIF 矫正→裁剪→增强→重采样→A4 合成→PDF
├── detect.py            # OpenCV 自动识别（可选依赖，导入失败自动降级）
├── pricing.py           # 证照计价分支（被主计价服务调用的唯一钩子函数 apply_cert_pricing）
└── cleanup.py           # 保留期清理线程（每小时）
```

前端（全部新文件）：

```text
frontend/src/cert/
├── CertPortal.vue            # /cert 证照门户页（卡片宫格，参照截图样式）
├── routes.js                 # 模块路由清单（本地维护，router/index.js 一次性引入）
├── constants.js              # 门户卡片 icon/theme 映射、公共文案
├── api.js                    # cert 接口封装（复用 api/client.js 请求器）
├── modules/
│   ├── ModuleShell.vue       # 模块页公共骨架（编排：槽位→预览→下单）
│   ├── IdCardModule.vue      # 身份证正反面打印（独立模块页）
│   ├── HukouPersonalModule.vue  # 户口本个人页打印（独立模块页）
│   └── HukouHolderModule.vue    # 户口本户主页打印（独立模块页）
├── components/
│   ├── PortalCard.vue        # 门户功能卡（图标/名称/说明/主题色）
│   ├── SlotUploader.vue      # 槽位拍照/上传/回显/重拍
│   ├── CropOverlay.vue       # 四点手动裁剪弹层（SVG，无第三方库）
│   └── CertOrderPanel.vue    # 参数/价格/余额/知情确认/确认打印
└── CertAdminView.vue         # /cert-admin 管理页（独立小页，不进 AdminView 内部）
```

### 1.3 触碰面预算表（主程序全部改动，超出的都算污染）

后端（现有文件只动这些）：

| 文件 | 改动内容 | 规模 |
| --- | --- | --- |
| `backend/app/main.py` | import cert → `include_router` ×2 + 启动时 `start_cleanup_scheduler()` | 约 4 行 |
| `backend/app/database.py` | `init_db()` 中（`ensure_columns()` 之后）调用 `cert.ensure_schema(db)` | 1–2 行 |
| `backend/app/services/pricing.py` | import `apply_cert_pricing` + 计价完成后 1 处调用 | 约 3 行 |
| `backend/app/middleware.py` | 敏感路径集合加 `'/api/cert/generate'`（复用现有专项限速） | 1 行 |
| `backend/requirements.txt` | + `opencv-python-headless`（可选依赖设计，见第 8 节） | 1 行 |

前端（现有文件只动这些）：

| 文件 | 改动内容 | 规模 |
| --- | --- | --- |
| `frontend/src/router/index.js` | 引入 cert 模块路由清单（`/cert` 门户 + 3 个模块页 + `/cert-admin` 管理页守卫） | 约 6 行 |
| `frontend/src/components/layout/AppHeader.vue` | 桌面导航 +「证照打印」一项（指向 `/cert`） | 约 2 行 |
| `frontend/src/components/layout/MobileTabbar.vue` | 三格扩四格 + 证照项（active 用 `route.path` 内联判断，**不改 useNavTargets.js**） | 约 4 行 |
| `frontend/src/views/AdminView.vue` | 侧边栏 +「证照模板」菜单项（跳 `/cert-admin`） | 约 2 行 |
| `frontend/src/views/HomeView.vue` | （可选）推广卡片 | 约 10 行，可省 |

**明确零改动清单**：`api/client.js`、`stores/*`、`assets/index.css`、`index.html`、`components/ui/*`、`composables/useNavTargets.js`、`models/schemas.py`、`config.py`、Dockerfile、docker-compose.yml，以及后端上传/支付/打印/兑换码/站点设置全部 router 与 service、`files` 表结构。

### 1.4 依赖方向规则

- **cert → core（允许）**：后端可 import `config`、`database(get_db)`、`routers/deps(current_user/admin_user)`、`models/schemas(PHONE_PATTERN 等)`、`services/files(page_count 等)`；前端可 import `api/client.js`、`stores/auth.js`、`components/ui/*`、`lib/utils.js`。
- **core → cert（仅 3 个注册点）**：`main.py`（路由注册 + 清理线程启动）、`database.py`（`ensure_schema`）、`pricing.py`（`apply_cert_pricing`）。除此之外任何 core 文件禁止 import cert。
- **禁止**：改共享组件外观、加全局 CSS、动主题/站点/认证 store、在 `components/ui/*` 内加组件。

### 1.5 可回滚性

删除 `backend/app/cert/` 与 `frontend/src/cert/` 两个目录 + 还原 1.3 表中约 10–20 行钩子 → 功能完全移除。`cert_templates`/`cert_docs` 两张表留在库里无害（可手动 DROP）。这同时是灰度下线的预案。

### 1.6 隔离性自检清单（实现完成后逐项核对）

- [ ] `grep -r "cert"` 扫描 `backend/app` 与 `frontend/src`：core 文件中出现 cert 引用的位置仅 1.3 预算表所列；
- [ ] `backend/app/cert/`、`frontend/src/cert/` 之外无本次新增文件（`backend/tests/cert_feature_test.py` 除外）；
- [ ] `assets/index.css`、`stores/`、`api/client.js`、`components/ui/*` 的 git diff 为空；
- [ ] 不装 OpenCV 时全部流程仍可用（自动识别降级为手动裁剪）；
- [ ] 删除两个 cert 目录后主程序可正常构建启动。

## 2. 模块化设计总览

### 2.1 交互模型（门户 + 独立模块页）

```text
/cert 证照门户（宫格卡片：宣传位[可选] + 两列功能卡）
   ├─ 图文打印        → 跳转现有首页 /（既有主打印功能，静态卡）
   ├─ 身份证正反面打印 → /cert/id-card（独立模块页）
   ├─ 户口本个人页打印 → /cert/hukou-personal（独立模块页）
   ├─ 户口本户主页打印 → /cert/hukou-holder（独立模块页）
   └─ （后续新模块自动出现：证书打印、驾驶证打印…，由后台启停控制）
```

用户路径：门户选卡片 → 进入该功能的独立模块页 → 拍照 → 自动排版 → 确认打印（余额校验扣费）→ 支付结果页。

### 2.2 模块化三原则

1. **一个功能 = 一个页面模块文件**：每个证照打印功能有自己独立的路由与页面文件，文件内包含该功能专属的槽位定义、标题文案、拍摄建议、参数默认值。
2. **模块间零引用**：模块页之间不互相 import、不互相跳转（回退统一回门户）；任何两个模块需要同样能力时，下沉到公共层，不允许模块互相复制。
3. **模块页只做「声明 + 组合」**：公共骨架 `ModuleShell` 负责编排（槽位上传 → 预览 → 下单面板），模块页只声明「我是哪个模板、我有哪几个槽位、我的文案是什么」，单文件预期 50–80 行量级。

### 2.3 路由与模块注册表

| 路由 | 页面模块文件（均在 `frontend/src/cert/`） | 对应模板 code | 槽位 | 门户卡片 |
| --- | --- | --- | --- | --- |
| `/cert` | `CertPortal.vue`（门户，不对应模板） | — | — | — |
| `/cert/id-card` | `modules/IdCardModule.vue` | `id_card` | 人像面、国徽面 | 身份证正反面打印 |
| `/cert/hukou-personal` | `modules/HukouPersonalModule.vue` | `hukou_personal` | 个人页照 | 户口本个人页打印 |
| `/cert/hukou-holder` | `modules/HukouHolderModule.vue` | `hukou_holder` | 户主页照 | 户口本户主页打印 |
| `/` | （现有 HomeView，静态卡跳转） | — | — | 图文打印 |

路由注册：cert 目录内维护「模块路由清单」（`routes.js`），`router/index.js` 钩子一次性引入。**新增一个证照功能的成本公式：1 个模块页文件 + 1 行本地路由注册 + 1 条模板数据（后台启用即自动出现在门户），主程序零改动。**

### 2.4 模块页统一行为（所有模块一致，由骨架保证）

- 进入即检查登录态：未登录显示置顶登录引导卡（可浏览但上传/下单时 401 → `/login?redirect=本模块路由`，登录后回到**当前模块页**）。
- 每槽位：拍照/上传（手机直调相机）→ 服务端自动识别裁剪 → 缩略回显 → 可重拍；识别失败仅对该槽位弹四点裁剪。
- 生成成功 → A4 版式预览（等比缩放，标注「实际打印尺寸 1:1」）。
- 下单面板：份数（1–50）、黑白/彩色（仅打印机支持时展示，默认黑白）、姓名/手机号（资料预填）、价格试算 + 余额、知情确认勾选、「确认打印」→ 余额不足提示 +「去充值」；成功扣费派发 → `/payment/{order_id}`。
- 页头：模块标题 + 「返回证照门户」。
- 证照模块页无「双面」选项（生成件均为单页文档，现有规则本就强制单面）。

## 3. 门户页 `/cert` 设计（参照截图样式）

### 3.1 布局结构（自上而下）

1. **宣传位（可选，P2）**：横向 banner 卡（一句话 + 小图/二维码），P0 可省略，预留位置。
2. **功能宫格**：两列卡片网格（手机端 2 列，桌面 md+ 3–4 列），每卡 = 图标 + 功能名 + 一句话说明 + 价格提示；「图文打印」静态卡排首位指向 `/`。
3. **我的证照件（P1 预留入口）**：底部一行次要入口，进历史生成件列表。
4. 底部沿用全站备案条/导航规范。

### 3.2 卡片规格与数据来源

- 数据源：`GET /api/cert/templates`（只返回 `enabled=1` 的模板），卡片展示字段取自模板 `layout_json.card`：`icon`（lucide 图标名，前端映射组件）、`desc`（一句话说明）、`theme`（配色主题键）。
- 配色遵守 UI 规范：**不写死色值**，`theme` 键映射到现有 CSS 变量组合（如 `--chart-1..5`/`--brand-*` 派生的浅底深字工具类），亮暗主题自动适配；卡片圆角、间距、触控目标（≥ 40px）按 `doc/UI_ADAPTATION.md`。
- 模板停用 → 卡片即时消失；新模板启用 → 卡片自动出现（门户完全数据驱动，无硬编码）。
- 320px 下两列不溢出、无横向滚动。

## 4. 模块页规格（每个功能一个模块）

### 4.1 公共骨架 `ModuleShell`（模块页的底座，模块页只填空）

骨架负责：页头（标题/返回）、登录引导、槽位区渲染（按模块声明的槽位清单循环渲染 `SlotUploader`）、生成调用与 `DETECT_FAILED` 分支（弹 `CropOverlay`）、预览区、`CertOrderPanel` 挂载、错误与限流提示。模块页通过声明式配置注入差异：

| 声明项 | 说明 | 示例（身份证模块） |
| --- | --- | --- |
| `templateCode` | 对应后端模板 code | `id_card` |
| `slots` | 槽位 key/标签/是否必传 | 人像面、国徽面 |
| `slotTips` | 每槽位拍摄建议 | 「平放深色背景上，四角完整，避免反光遮挡国徽/文字」 |
| `moduleCopy` | 模块标题、副标题、页面说明 | 「身份证正反面打印 · 正反面排入同一页 A4，1:1 实际尺寸」 |
| `defaults` | 参数默认值覆盖 | 份数 1、黑白 |

### 4.2 身份证正反面打印模块（`/cert/id-card`）

- 槽位：人像面照片、国徽面照片（2 个，均必传）。
- 版式：1 页 A4 竖版，正上反下，各 85.6×54mm 1:1，水平居中 x=62.2mm，正面 y=89.5mm、反面 y=153.5mm（垂直居中，间距 10mm），浅灰裁剪细框默认开。
- 专属文案：本页说明「正反面自动排入同一页，打印后沿框裁剪即为实际尺寸」；拍摄建议强调「证件平放、四角完整、避免手指遮挡」。
- 计价：模板独立价（¥X/套 × 份数），未设价时回退标准按页价。

### 4.3 户口本个人页打印模块（`/cert/hukou-personal`）

- 槽位：个人页照片（1 个必传）。
- 版式：1 页 A4，矫正后近整页摆放（**尺寸须实物样张实测校准后才上线**）。
- 专属文案：拍摄建议强调「页面平整、避免装订阴影、字迹清晰」。

### 4.4 户口本户主页打印模块（`/cert/hukou-holder`）

- 与 4.3 同构，槽位为户主页照片，模板 code `hukou_holder`。两个户口本模块是两个独立页面文件（满足「一个功能一个模块」），共享同一套 A4 整页版式配置。

### 4.5 模块页的联动打印（所有模块一致）

- 价格试算走现有 `POST /api/price`（file_ids 模式），证照计价在后端计价服务内部生效，前端无感知。
- 「确认打印」走现有 `POST /api/payment/create`（balance）——服务端校验最低余额 → 扣款 → 订单置 `paid` → `dispatch_order_print()`；**模块内不出现任何支付代码**。
- 彩色选项严格跟随 `/api/print-options` 的 `is_support_color`（不支持则不展示、不携带参数）。
- P0 仅余额支付（符合「必须登录、只判断钱够不够」）；游客支付为 P2 可选开关。

## 5. 产品设计要点

### 5.1 入口与角色

- 仅登录用户可完成「生成 + 打印」；门户浏览与模板列表不需要登录。
- 入口三处：桌面端顶栏导航「证照打印」；手机端底部 Tab 四格（首页 / 证照 / 订单 / 我的）；首页推广卡片（可选）。
- 角色沿用现有体系：注册用户（本模块唯一使用者）、管理员（后台管模板与配置）。

### 5.2 功能分期

| 阶段 | 内容 |
| --- | --- |
| P0（MVP） | 3 个模块页 + 门户页、自动识别 + 手动四点裁剪、300dpi 1:1 PDF、余额一键打印、余额不足引导充值、登录回跳、原照片不落盘、每日生成上限、敏感路径限速、导航三处入口、知情确认声明、自持建表与清理线程 |
| P1 | 模板定价/启停后台完善、卡片文案编辑、历史生成件重打、多模板合并一单、扩展模块（驾驶证/行驶证/结婚证/营业执照/毕业证，需实样校准）、失败拍摄引导 |
| P2 | 宣传位 banner（站点配置驱动）、门店扫码直链模块页、证照打印量统计、「推荐黑白」提示、游客支付可选开关、（按需）拆独立程序走形态 B |

## 6. 数据库设计（schema 全部自持在 `cert/schema.py`）

### 6.1 `cert_templates`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT (uuid) PK | |
| `code` | TEXT UNIQUE | 模板标识（`id_card` 等），与前端模块页绑定 |
| `name` | TEXT | 展示名 |
| `layout_json` | TEXT (JSON) | 槽位版式 + 门户卡片元数据（见 6.2） |
| `price` | REAL NULL | 模板单价（元）；NULL = 回退标准按页计价 |
| `enabled` | INTEGER (0/1) | 是否启用（控制门户卡片与生成接口） |
| `sort` | INTEGER | 门户排序 |
| `created_at` / `updated_at` | TEXT | |

### 6.2 `layout_json` 规格（身份证模板示例）

```json
{
  "card": { "icon": "credit-card", "desc": "正反面排入一页 A4，1:1 实际尺寸", "theme": "blue" },
  "page_size_mm": [210, 297],
  "orientation": "portrait",
  "slots": [
    { "key": "front", "label": "身份证人像面", "size_mm": [85.6, 54.0], "position_mm": [62.2, 89.5], "rotation": 0 },
    { "key": "back",  "label": "身份证国徽面", "size_mm": [85.6, 54.0], "position_mm": [62.2, 153.5], "rotation": 0 }
  ],
  "cut_guides": true,
  "slot_labels": false
}
```

- `icon` 只存 lucide 图标名（字符串），前端 `constants.js` 负责映射到组件；`theme` 只存主题键，前端映射到 CSS 变量组合——后端不感知视觉实现。
- **卡片数据后端驱动**（启停即生效），**模块页内的拍摄建议/说明由前端模块文件自持**（与本模块强绑定）。
- P0 阶段 `layout_json` 只随代码发布（`templates_seed.py`），后台只改价格与启停；完整版式编辑器列 P1。
- 非身份证模板的目标尺寸必须用实物样张实测校准后才上线，不凭资料写死。

### 6.3 `cert_docs`（生成件记录）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT (uuid) PK | |
| `user_id` | TEXT | 属主（索引） |
| `template_code` | TEXT | 冗余模板 code（模板变更不影响历史展示） |
| `pdf_file_id` | TEXT | 关联 `files.id`（索引） |
| `page_count` | INTEGER | 生成页数 |
| `used_manual_crop` | INTEGER (0/1) | 是否用了手动裁剪（识别改进统计依据，P1 用） |
| `status` | TEXT | `active` / `expired` |
| `created_at` | TEXT | |
| `expires_at` | TEXT | 保留期截止时间，清理任务依据 |

### 6.4 `files` 表复用（零改动）

- 生成件直接写 `files` 表：`user_id`=属主、`original_filename`=`证照打印件-{模板名}.pdf`、`pdf_path`=`uploads/<file_id>/converted.pdf`、`page_count` 正常统计、**`is_safe=1`**。
- 理由：生成件是系统按固定版式合成的受信产物，不经 `POST /api/upload` 的外部文件检测；跳过安全检测是设计决定，不是绕过——外部上传文件仍走原管线。
- **不加 `source` 列**：「是否证照件」一律以 `cert_docs.pdf_file_id` 关联判定。
- **计价保护**：证照件 `coverage` 为 NULL，任何情况下不得落入按覆盖率计价（见第 9 节）。

### 6.5 设置键（由 cert 模块自持读写 `settings` 表，不动 `DEFAULT_SETTINGS`）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `cert_retention_hours` | 24 | 生成件保留时长（小时）；0 = 允许订单完成后即清 |
| `cert_daily_generate_limit` | 20 | 每用户每日生成上限（防滥用） |

### 6.6 自持播种与迁移

- `ensure_schema(db)`：`CREATE TABLE IF NOT EXISTS` ×2 → `INSERT OR IGNORE` 播种 3 个内置模板 → 播种 2 个设置键。幂等，旧库升级自动补建；主程序 `database.py` 仅在 `init_db()` 里加一行调用（钩子）。
- 清理任务删除 `cert_docs` 时必须跳过仍被未支付/待派发订单引用的文件。

## 7. 后端接口设计

### 7.1 接口一览（`cert/router.py` 与 `cert/admin_router.py`）

| 方法 | 路径 | 鉴权 | 归属 |
| --- | --- | --- | --- |
| GET | `/api/cert/templates` | 公开只读 | router.py |
| POST | `/api/cert/generate` | 登录 + 限速 + 每日上限 | router.py |
| GET | `/api/cert/docs` | 登录（分页） | router.py |
| GET | `/api/cert/docs/{id}/preview` | 登录 + 属主 | router.py |
| DELETE | `/api/cert/docs/{id}` | 登录 + 属主 | router.py |
| GET | `/api/admin/cert-templates` | 管理员 | admin_router.py |
| PATCH | `/api/admin/cert-templates/{code}` | 管理员（改 price/enabled） | admin_router.py |
| GET/PUT | `/api/admin/cert-settings` | 管理员（保留期/每日上限） | admin_router.py |

- 管理员接口放在 cert 模块自己的 admin_router（复用 `deps.admin_user`），**不往 `admin.py` 里加代码**。
- 下单闭环不改任何现有接口：`/api/price`、`/api/payment/create`、`/api/orders/{id}` 原样使用。

### 7.2 `POST /api/cert/generate` 规格

- 入参（multipart/form-data）：`template_code`；`cut_guides`（可省，用模板默认）；每槽位图片字段 `slot_<key>`（如 `slot_front`/`slot_back`）；每槽位可选手动裁剪四点 JSON `quad_<key>`（归一化 0–1 坐标）。
- 流程：登录校验 → 模板存在且启用 → 槽位齐全 → 图片可读（JPEG/PNG/WebP，大小沿用后台「文件大小限制」）→ 每日生成上限（超限 429）→ 图像管线（第 8 节）→ 合成 PDF → 写 `files` + `cert_docs` → **请求级临时目录销毁（原始照片全程不落盘持久化）**。
- 成功响应：`{cert_doc_id, file_id, page_count, preview_url}`。
- 错误：401 未登录；400 模板不存在/停用、槽位缺失、图片损坏或格式不支持；400 自动识别失败且无手动四点 → `detail = {"code": "DETECT_FAILED", "slots": ["front"]}`（前端只对失败槽位弹手动裁剪）；429 超每日上限；500 走全局中文兜底。
- 限速：`/api/cert/generate` 加入 `middleware.py` 敏感路径集合（1 行钩子，复用现有 `sensitive_rate_limit_per_minute`）。

### 7.3 `GET /api/cert/templates` 响应要点

返回 `[{code, name, slots:[{key,label,size_mm}], page_count, cut_guides, price, price_mode, card:{icon,desc,theme}}]`；只含 `enabled=1` 的模板；`price_mode` 为 `template`（独立价，前端显示「¥X/套」）或 `standard`（按页计价）。

### 7.4 归属校验

`docs` 相关接口一律「属主或管理员」，非属主与「不存在」返回同一响应（沿用安全修复 V-07 同级防护，不泄露他人 doc_id 存在性）。

## 8. 图像处理与 PDF 生成设计（`cert/render.py` + `cert/detect.py`）

### 8.1 管线总览

```text
槽位图片(请求级临时目录)
  → EXIF 方向矫正 (ImageOps.exif_transpose) → 可读性/格式校验
  → 自动识别卡片并透视矫正（OpenCV，detect.py，导入失败整体降级）
      失败 → 有手动四点：Pillow Image.transform(QUAD/PERSPECTIVE)
             无四点  → 返回 DETECT_FAILED（对应槽位）
  → 尽力而为增强：去阴影/背景提亮/对比度拉伸（失败不阻断）
  → LANCZOS 重采样到槽位目标像素（300dpi）
  → 按 layout_json 合成 A4 页位图（白底 + 可选浅灰裁剪框）
  → Pillow 逐页存单页 PDF（resolution=300.0）+ PyPDF2 合并 → 入库
```

### 8.2 自动识别（OpenCV，可选依赖）

- 依赖：`opencv-python-headless`（requirements.txt 钩子，约增加镜像 100MB，可接受）；`detect.py` 内 import 守卫，导入失败自动降级为「仅手动四点裁剪」，功能不残废（验收项）。
- 方法：灰度 → 边缘/阈值 → 最大四边形轮廓 → 多边形逼近 → 透视矫正（`warpPerspective`）到目标长宽比；置信度不足（轮廓面积占比过低、长宽比偏差过大）视为失败，交给手动裁剪。
- 首版只做「找到卡片并摆正」，不做遮挡/反光修复类重处理。

### 8.3 手动四点裁剪

- 前端 `CropOverlay`：SVG 四角点拖拽（无第三方裁剪库），提交归一化坐标。
- 后端用 `Image.transform(size, QUAD/PERSPECTIVE, ...)` 完成矫正——**纯 Pillow 实现，不依赖 OpenCV**，是识别失败时的体验下限保障。

### 8.4 PDF 合成规格

- 每页 = 一张 300dpi A4 位图：210mm→2480px、297mm→3508px（换算 `px = mm / 25.4 × 300`）；身份证卡 85.6mm→1011px、54mm→638px。
- 槽位定位按 `layout_json` 的 mm 坐标换算像素贴图；白底 RGB，JPEG 质量 92。
- 组 PDF：**Pillow 逐页存单页 PDF（`resolution=300.0`，页尺寸自动为 A4）+ PyPDF2 合并**——两个都是现有依赖，**PDF 组装零新增依赖**（备选：`img2pdf` 无损嵌入）。
- 与打印链路协同：现有 `rasterize_pdf_for_print()` 打印前按 300dpi 整页光栅化，与合成精度一致，**打印端不会二次降质**；产物无字体、无 SMask，天然规避「公式消失/偏灰」类问题。
- 生成后调用现有 `page_count()` 逻辑写 `files.page_count`。

## 9. 计价设计（`cert/pricing.py`，唯一被主计价调用的钩子）

- `apply_cert_pricing(db, files, copies, result)`：在 `calculate_files_price_detail()` 标准计价完成后调用，对 `cert_docs.pdf_file_id` 命中的文件重算该项金额：
  - `cert_templates.price` 非空 → `amount = price × copies`，`pricing_detail` 记 `mode='cert_template'`、模板名、单价；
  - `price` 为空 → 回退 **standard 单面价**（按页）；
  - **任何情况下证照件不得落入 `coverage_tiered`**（其 coverage 为 NULL，且照片页覆盖率无意义）；
  - 多文件混合下单时逐文件分支后求和；价格一律服务端计算，前端传值不参与计价。
- `orders.pricing_detail` 照常入库，后台订单详情金额拆分自动可见；后台订单列表可显示「证照」标签（P2，经 `cert_docs` 关联实现，无需改 orders 表）。
- 双面解析：生成件单页，`resolve_file_double_sided` 自动强制单面，无需特判。
- `services/pricing.py` 的改动 = 1 个 import + 1 行调用（预算表内）。

## 10. 隐私与安全设计（红线，全部实现在 cert 模块内）

1. **原始照片不落盘**：槽位照片仅存在于请求处理期间的临时目录（`tempfile.TemporaryDirectory` 请求结束自动销毁），成功失败都不持久化——比「先存后删」更强。
2. **生成件保留期**：默认 24 小时自动清理（`cert_retention_hours`）；清理线程每小时执行：`expires_at < now` → 删 `uploads/<file_id>/` 目录 → 删 `files` 行 → 删 `cert_docs` 行；**跳过仍被未支付/待派发订单引用的文件**；用户可手动删除（`DELETE /api/cert/docs/{id}`）。
3. **知情确认**：生成前必须勾选「本人确认打印自有证件，仅用于合法用途」；模块页固定展示用途声明。系统不做证件真伪校验，该声明用于留存合规姿态。
4. **防滥用**：每用户每日生成上限（`cert_daily_generate_limit`）+ 生成接口纳入敏感路径限速 + 必须登录。
5. **归属校验**：生成件预览/引用仅属主或管理员；非属主与不存在同响应。
6. **日志脱敏**：日志只记 doc_id/模板/用户/结果，不打印照片内容或 base64。
7. **传输与回跳**：生产环境 HTTPS（现有部署约定）；登录回跳 `redirect` 参数只允许站内路径（以 `/` 开头且非 `//`），防开放重定向。
8. 后台订单详情沿用「默认不加载 PDF 预览、点预览才加载」的现有交互。

## 11. 管理后台（`/cert-admin`，独立页）

- `frontend/src/cert/CertAdminView.vue` + `cert/admin_router.py` 提供独立管理小页，**路径刻意避开 `/admin` 前缀**（防 App.vue 的 `isAdminRoute` 即 `startsWith('/admin')` 误判导致顶栏/底部导航异常）；页面在前台壳内渲染，靠路由守卫限制管理员；AdminView 仅加一个菜单项；P1 可再评估并入 AdminView tab。
- 功能：模板列表（名称/卡片说明/价格/状态/排序）、启用停用、改单价（留空=按标准页价）；「系统设置」区：生成件保留时长、每用户每日生成上限。卡片文案（desc）P0 只读、P1 可编辑。
- 模板启停即时生效：门户卡片消失、对应模块页生成接口 400、模块页头部显示「该功能已下架」。

## 12. 边界情况与异常处理

| 场景 | 处理 |
| --- | --- |
| 用户直接访问已下架模板的模块页（深链） | 页面头部显示「功能已下架」，槽位区禁用，引导返回门户 |
| 门户拿不到模板列表（接口异常） | 显示重试空态，不影响「图文打印」静态卡 |
| 自动识别失败 | `DETECT_FAILED` + 失败槽位 → 仅该槽位弹手动裁剪，不死循环 |
| 照片过小/模糊（短边 < 目标像素 60%） | 判定识别失败，引导重拍或手动裁剪 |
| 图片格式不支持/损坏（含 HEIC） | 400 中文提示「图片无法识别，请使用 JPG/PNG 格式重新拍摄」（iOS/微信内置浏览器拍照一般已自动转 JPEG） |
| 未配置默认打印机 | 订单照常创建，派发失败走现有 `print_failed`；结果页提示「打印失败请联系店家处理」（无自动退款，与现状一致） |
| 模板在下单前被停用 | 已生成文件不受影响（`cert_docs` 冗余 code）；不能再生成新件 |
| 保留期内文件被清理后点重打 | 404 → 提示「生成件已过期，请重新生成」 |
| 并发生成 | 每日上限 + 接口限速兜底；单请求内多槽位串行处理 |
| 彩色/双面越权提交 | 彩色走现有打印机能力兜底 400；单页文件双面被现有规则强制单面 |
| 证照件落入 coverage_tiered 模式 | 计价钩子硬性排除 |
| 不装 OpenCV | 手动裁剪全流程可用（验收项） |

## 13. 测试计划与验收口径

### 13.1 测试计划

- 新测试文件 `backend/tests/cert_feature_test.py`（Windows 本地可跑，不依赖 CUPS/前端）：
  - schema 播种幂等（重复执行结果一致）；
  - mm→px 换算与槽位定位（合成后在已知 dpi 下量测偏差 ≤ 1px）；
  - 手动四点透视变换（合成标准四边形样图验证）；
  - 计价钩子三分支（独立价 / 回退 standard / 拒绝 coverage）；
  - 每日上限与限速；清理任务（含跳过未支付订单引用）；属主校验。
- 冒烟测试扩展（`backend/tests/smoke_test.py`，桩掉 `print_pdf`）：登录 → generate（合成样图）→ price → payment/create(balance) → 订单 paid → 派发被调用；余额不足 400；未登录 401；模板停用 400。
- 隔离性自检：第 1.6 节清单逐项核对。
- 前端：`pnpm --prefix frontend run build`；浏览器人工检查亮/暗 × 桌面/手机四种组合。

### 13.2 模块化专项验收（新增）

1. 门户卡片完全由 `/api/cert/templates` 驱动：后台停用某模板，卡片消失且其模块页深链进入显示「已下架」；重新启用即恢复。
2. 三个模块页互相独立：任一模块页刷新/直链进入均正常；模块间无相互跳转依赖；删除任一模块页文件（开发环境）不影响其余模块与门户构建。
3. 新增一个模板数据 + 一个模块页文件 + 一行路由注册，即可在不改任何主程序文件的前提下上线一个新证照功能（在测试环境演练一次）。

### 13.3 常规验收口径

1. 身份证模块：上传正反面照片 → 自动生成 1 页 A4 PDF，预览中卡片为 85.6×54mm（1:1）、正上反下；自动识别失败时可用手动四点裁剪成功生成。
2. 未登录点「确认打印」→ 跳登录页 → 登录后回跳当前模块页；余额不足 → 提示并可去充值；余额足够 → 点击后直接扣费并派发打印，无任何额外操作。
3. 生成成功后服务端不存在原始照片文件；到期后生成件与文件记录被自动清理；用户可手动删除。
4. `/cert-admin` 可启停模板、改单价、调保留期与上限，即时生效。
5. 手机端 320px 无横向滚动、亮暗主题正常、彩色选项严格跟随打印机能力。
6. 未勾选知情确认时「确认打印」不可用；不装 OpenCV 时全流程可用。

## 14. 实施任务拆解（P0，约 7–9 人日）

1. `cert/schema.py` + `templates_seed.py`（含 card 元数据）+ `database.py` 钩子（0.5d）
2. `cert/render.py` 合成管线 + 手动四点裁剪 + Pillow/PyPDF2 组 PDF（1.5d）
3. `cert/detect.py` OpenCV 自动识别（含可选依赖降级）（1d）
4. `cert/service.py` + `cert/router.py`（生成/上限/临时目录/归属）+ middleware 1 行（1d）
5. `cert/pricing.py` 钩子 + `pricing.py` 3 行 + `/api/price` 联调（0.5d）
6. 前端公共层：`api.js` / `constants.js` / `SlotUploader` / `CropOverlay` / `CertOrderPanel` / `ModuleShell`（1.5–2d）
7. 门户页 `CertPortal.vue` + `PortalCard.vue` + `routes.js` + 路由/导航钩子 + 首页推广卡（可选）（0.5–1d）
8. 三个模块页（声明式，平均每页 0.25d）（0.75d）
9. `CertAdminView.vue` + `cert/admin_router.py` + AdminView 菜单项（0.5d）
10. `cert/cleanup.py` + `main.py` 启动钩子（0.5d）
11. 测试（单测 + 冒烟扩展）+ 隔离性自检 + 模块化演练（新增一个模板走通全流程）+ 四组合 UI 自检（1d）

依赖顺序：1 → 2 →（3、4 可并行）→ 5 → 6/7 → 8 → 9 → 10 → 11。

## 15. 未来演进

- **P1**：模板后台版式编辑（`layout_json` 可视化）、卡片文案编辑、历史生成件重打、多模板合并一单、扩展模块上线流程（样张实测 → `templates_seed.py` 增配 → 后台启用 → 新增模块页文件 + 一行路由注册）。
- **P2**：宣传位 banner、门店扫码（前台生成指向模块页的二维码，天然支持手机端）、证照打印量统计指标、「推荐黑白」提示、游客支付可选开关；照片冲印类业务属新增品类，需另行立项。
- **形态 B 路径**（若将来要拆独立程序/域名）：cert 包天然是拆分接缝——把 `backend/app/cert/` 整体迁出为独立服务，联动改为共享 `bridge_secret`（不用 `app_secret`）+ 一次性 HMAC 票据（120s、jti 一次性、act 白名单）+ 打印端新增 `POST /api/bridge/exchange` 换取原生会话 + 生成件经标准 `POST /api/upload` 用换来的 token 回传 + 跳转首页预选文件；硬性前提 HTTPS、redirect 白名单防开放重定向。

## 16. 文档影响

- 本文件为方案依据；实现完成后需同步更新：`doc/PRD.md`（新增功能范围、用户流程、验收口径）、`doc/AGENTS.md`（目录结构、路由概览、数据表、修改注意事项、代码链路、隔离架构钩子说明）。
- 在实现完成前，`doc/PRD.md`、`doc/AGENTS.md` 保持原样，不提前描述未实现的功能。
