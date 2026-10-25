# PrintHub（云打印系统）- 代码协作说明

这份文件面向后续维护本仓库的编码代理和开发者。它描述当前代码的真实结构、业务逻辑、运行方式和修改注意事项。产品愿景和需求边界可参考 `doc/PRD.md`；本文件以现有代码为准。

## 1. 项目用途

这是一个基于 FastAPI + Vue 3 的在线云打印系统。用户可以上传 PDF、Office 文档或图片，后端保存原文件并转换为 PDF，计算页数和黑色覆盖率，通过安全检测后创建打印订单。订单支持支付宝/微信易支付、注册用户余额支付；注册用户还可以在线充值余额、用兑换码充值。支付成功或余额扣费成功后，系统会把 PDF 下发到打印服务。

后台提供运营概览、异常告警、订单详情、未支付订单清理、文件缓存清理、用户管理、系统价格/阈值/促销设置、易支付配置、支付自测、打印机管理和兑换码管理。

本系统没有「打印模式」配置项（`PRINT_MODE` 环境变量与 `print_mode` 设置已整体移除），打印方式完全由运行平台决定：Linux/macOS 走 CUPS 命令，Windows 读取系统已安装打印队列并优先使用 SumatraPDF 打印 PDF。所有打印都是真实打印，没有 mock 模拟模式。

## 2. 技术栈

- 后端：Python 3.12、FastAPI、SQLite、Pydantic Settings、bcrypt、PyPDF2、pdf2image、Pillow；`opencv-python-headless` 为证照打印的可选依赖（缺失时自动降级为手动四点裁剪，全流程仍可用）。
- 文档转换：系统安装 LibreOffice、Poppler、CUPS client、完整字体库（Noto CJK/CJK-extra、Noto Core/Extra/Mono、Liberation、Carlito、Caladea、DejaVu、STIX、Noto Color Emoji）和 `zh_CN.UTF-8`。字体映射与回退由 `docker/fontconfig/49-cloud-print-aliases.conf` 提供，把 Windows/Office 专有字体名（宋体/黑体/微软雅黑/Times New Roman/Arial/Wingdings 等）映射到已装字体，并为所有字体追加 CJK + 数学符号 + 图案符号兜底，避免转换/打印乱码。
- 打印：CUPS 命令、Windows PowerShell/SumatraPDF 分流（已移除 mock 模拟模式）。
- 前端：Vue 3、Vite、Vue Router、Pinia、**Tailwind CSS v4 + shadcn-vue（reka-ui，reka-nova 风格，`typescript: false` 生成 JS 组件）**、lucide-vue-next、unovis（shadcn-vue Chart 底层）、vue-sonner（Toast）。组件一律来自 `frontend/src/components/ui/*`（shadcn-vue CLI 生成，`components.json` 驱动），页面层只用 Tailwind 工具类 + CSS 变量定制外观，禁止手写 CSS 复刻组件。品牌字/数字用自托管 Space Grotesk 变量字体（仅拉丁字符与数字，中文自动回退系统字体），文件在 `frontend/src/assets/fonts/`，由 `assets/index.css` 的 `@font-face` 与 `--font-display` 暴露。
- 部署：Docker Compose 单容器。`Dockerfile` 多阶段构建（Node 构建前端 → Python 运行镜像，FastAPI 同时托管 API 与前端静态文件），pnpm 版本由 `frontend/package.json` 的 `packageManager` 字段固定（当前 `pnpm@12.11.2`，Dockerfile 安装同版本），`frontend/pnpm-workspace.yaml` 里 `minimumReleaseAge: 0` 关闭 pnpm 供应链发布龄期检查以保证锁文件可冻结安装——**该文件必须与 `package.json`/`pnpm-lock.yaml` 一起在 `pnpm install` 前拷入构建层**（见 Dockerfile Stage 1 注释；只拷 package.json 会让 install 落回默认 1 天龄期策略并拒绝刚发布的包）。`frontend/package.json` 里 `shadcn-vue` 是 devDependency（`assets/index.css` 的 `@import "shadcn-vue/tailwind.css"` 依赖它提供 data-* 变体等基础样式层，不要移除）。`docker-compose.yml` 用 `./config:/app/config` 绑定挂载持久化，`docker/entrypoint.sh` 负责建目录与生成配置文件。仓库里没有 `install.sh`/`configure.sh`/`start.sh`/`uninstall.sh`。
- 存储：唯一持久化目录是配置目录 `<CONFIG_ROOT>`（容器内 `/app/config`，由 `docker-compose.yml` 绑定挂载到宿主机 `./config`）：`config.json`、`cloud_print.db`、`uploads/`、`backups/`、`logs/`、`cups-drivers/` 全在里面，备份 = 复制整个配置目录。
- 配置优先级：环境变量 > `config.json` > 代码内建默认值。`config.json` 首次启动自动生成（含随机 `app_secret`），之后只在缺失键时补齐、绝不覆盖已有值。

## 3. 目录结构

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 应用入口，注册中间件、路由和打印状态监控
│   │   ├── bootstrap.py         # 首次部署引导：生成 config.json 并创建数据目录
│   │   ├── config.py            # 唯一配置文件（config.json）的生成/读取、环境变量覆盖、按 mtime 热加载
│   │   ├── database.py          # SQLite schema、轻量迁移、默认管理员和设置（含 cert.ensure_schema 钩子）
│   │   ├── middleware.py        # 限流、安全响应头、生产配置校验；CSRF helper 尚未在 main.py 注册
│   │   ├── models/schemas.py    # 请求/响应 Pydantic 模型和支付方式归一化
│   │   ├── routers/             # public/auth/files/orders/user/admin API
│   │   ├── cert/                # 【证照打印】隔离模块（见 6.9）：router/admin_router/schema/templates_seed/service/render/detect/pricing/cleanup
│   │   ├── doc2up/              # 【两页合一打印】隔离模块（见 6.10）：router/service（两页缩排一页 A4 合成）
│   │   ├── services/            # 文件、支付、计价、安全检测、认证会话、打印、打印派发、按日统计、站点设置服务
│   │   │   ├── print_dispatch.py # 打印派发：支付完成后调度后台线程异步执行 dispatch_order_print（防重/等 paid/补派发）
│   │   │   └── stats.py        # 后台「每日数据统计」：把 UTC 时间戳按**本地时区**聚合成每日订单数/收入/失败数（收入只计已支付状态 PAID_STATUSES）
│   │   └── utils/security.py    # bcrypt 密码哈希和自定义 HMAC token
│   ├── tests/smoke_test.py      # 后端冒烟测试（import app.main 需要 pycups，适合容器内跑）
│   ├── tests/config_test.py     # config.json 生成/热加载/管理员重置测试（不依赖 CUPS，本地可跑）
│   ├── tests/queue_feature_test.py
│   ├── tests/daily_stats_test.py # 「每日数据统计」本地时区分日聚合专项测试（不依赖 CUPS，本地可跑）
│   ├── tests/cert_feature_test.py # 【证照打印】cert 模块专项测试（不依赖 CUPS/OpenCV，本地可跑）
│   ├── requirements.txt
│   └── run.py                   # 本地开发入口
├── frontend/
│   ├── src/
│   │   ├── App.vue              # 全局壳：AppHeader + RouterView + MobileTabbar + Toaster
│   │   ├── api/client.js        # fetch 封装、token 注入、CSRF token 自动携带（业务逻辑，勿动）
│   │   ├── router/index.js
│   │   ├── stores/auth.js
│   │   ├── stores/site.js       # 站点配置（标题/favicon/备案号）：启动时拉取 /api/site-settings 并全局应用
│   │   ├── stores/theme.js      # 亮/暗主题状态：localStorage 记忆 + 跟随系统，切换 html.dark 类
│   │   ├── composables/useNavTargets.js  # 顶栏/底部 Tab 共用的导航目标与互斥高亮判定
│   │   ├── views/               # 首页、认证、支付、个人中心、后台（模板用 shadcn 组件 + Tailwind）
│   │   ├── cert/               # 【证照打印】隔离模块前端（见 6.9）：CertPortal/CertAdminPanel（AdminView「证件照管理」tab 面板）/routes/constants/api + modules/（ModuleShell + IdCard/Hukou 模块页）+ components/（PortalCard/SlotUploader/CropOverlay/CertOrderPanel）
│   │   ├── doc2up/             # 【两页合一打印】隔离模块前端（见 6.10）：Doc2UpModule（/cert/doc-2up）+ api/routes
│   │   ├── components/
│   │   │   ├── layout/          # AppHeader.vue / MobileTabbar.vue / ThemeToggle.vue（布局壳）
│   │   │   ├── DailyStatsCard.vue # 后台概览「每日数据统计」卡片：shadcn Chart(Unovis) 双轴柱线图
│   │   │   └── ui/              # shadcn-vue CLI 生成的官方组件（button/card/dialog/sidebar/chart/...，勿手改外观）
│   │   ├── lib/utils.js         # cn()（clsx + tailwind-merge），shadcn-vue 生成
│   │   └── assets/
│   │       ├── index.css        # 唯一全局样式：Tailwind 入口 + CSS 变量主题（亮/暗两套）+ @font-face
│   │       └── fonts/           # 自托管 Space Grotesk 变量字体（仅 latin 子集，供品牌字/数字）
│   ├── index.html               # 含首屏防闪烁内联脚本（样式生效前切换 html.dark 类）、内联 SVG favicon、meta/og/theme-color
│   ├── components.json          # shadcn-vue CLI 配置（reka-nova 风格、JS 模式、别名 @/*）
│   ├── jsconfig.json            # @/* → src/* 路径别名
│   ├── vite.config.js           # @vitejs/plugin-vue + @tailwindcss/vite + @ 别名 + /api 代理
│   ├── package.json             # 含 packageManager（pnpm@12.11.2）与 "type": "module"
│   ├── pnpm-lock.yaml           # 包管理器是 pnpm（Dockerfile 用 pnpm@12.11.2 --frozen-lockfile）
│   ├── pnpm-workspace.yaml      # minimumReleaseAge: 0（构建可复现，见 §2）
│   └── nginx.conf               # 旧的独立 Nginx 配置，仅备用（生产由 FastAPI 托管前端）
├── scripts/test_printer.py      # 命令行测试样张脚本
├── scripts/theme_*.py           # 旧版手写 CSS 时代的主题检查工具，针对 var(--cp-*) 编写，已废弃不参与运行
├── Dockerfile                   # 多阶段构建：Node 构建前端 → Python 运行镜像（FastAPI 同时托管前端）
├── docker-compose.yml           # 单容器；./config:/app/config 绑定挂载持久化
├── docker/                      # entrypoint.sh、fontconfig 字体映射、nginx 配置（备用）
├── README.md
└── doc/PRD.md
```

仓库中存在若干带 `BakingdeMini.lan的冲突副本...` 的同步冲突副本。正常维护时以不带冲突副本后缀的正式文件为准，除非用户明确要求从冲突副本恢复内容。`release/` 是打包产物快照，通常不要作为源码修改入口。

仓库根目录的 `.gitattributes` 固定行尾策略：`* text=auto eol=lf` 让全部文本文件以 LF 入库（含 `*.sh`/`*.conf`，保证 Linux 容器内 shebang 可用），Windows 侧 `*.bat`/`*.cmd`/`*.ps1` 保持 CRLF，图片/PDF/DB/woff2 字体标记为 binary。因此在 Windows 上工作区若出现 CRLF，`git add` 时会提示 `CRLF will be replaced by LF`，这是预期行为，不要为了消除警告去改 `.gitattributes`。忽略规则集中在 `.gitignore`（Python 缓存、`.env*`、`config/`、`storage/`、`logs/`、`frontend/node_modules/`、`frontend/dist/`、`release/`、编辑器目录、NAS 冲突副本）。

## 4. 后端入口和生命周期

`backend/app/main.py` 创建 FastAPI 应用：

1. 导入时先调用 `bootstrap()`（`backend/app/bootstrap.py`）：确保配置目录里存在 `config.json`（缺失就按默认值生成、含随机 `app_secret`）并创建数据库/上传/备份/日志/CUPS 驱动目录；随后 `get_settings()` 读取配置并打印配置目录、配置文件、数据库位置。
2. 注册 CORS、限流、TrustedHost 和安全响应头中间件，并注册全局兜底异常处理 `@app.exception_handler(Exception)`：未捕获异常记录堆栈后返回 `{"detail": "服务器内部错误，请稍后重试"}` 的 JSON，避免前端只拿到 FastAPI 默认的纯文本 500 "Internal Server Error"。FastAPI 文档端点（`/docs`、`/redoc`、`/openapi.json`）只在 `environment=development` 时开启，其它环境一律禁用，不对外暴露 API 定义（安全修复 V-06）。
3. 启动时先调用 `_warn_data_outside_config_root()`（容器里若数据库/上传等路径跑到配置目录之外会打印警告，提示重建容器会丢数据），再调用 `validate_production_config(settings)`、`init_db()`、`start_print_status_monitor()`、`start_auto_backup_scheduler()`，以及证照打印的 `cert.start_cleanup_scheduler()`（生成件保留期清理线程，见 6.9）。
4. 注册路由：`public`、`auth`、`files`、`orders`、`admin`、`admin.setup_router`、`user`，以及证照模块的 `cert.router` 与 `cert.admin_router`（见 6.9）。
5. 在所有路由之后注册前端静态文件服务（`/assets`、`/static`）和 catch-all 路由。

`backend/app/database.py` 负责：

- 创建 SQLite 表：`users`、`files`、`orders`、`order_items`、`payments`、`settings`、`alerts`、`printers`、`auth_sessions`、`login_failures`、`redemption_codes`、`redemption_logs`。
- 通过 `SCHEMA_MIGRATIONS` 给旧库补列，新增表通过 `CREATE TABLE IF NOT EXISTS` 创建。
- 打印机能力列：`printers.is_support_color INTEGER DEFAULT 0`（是否支持彩色打印）、`printers.is_support_auto_duplex INTEGER DEFAULT 1`（是否支持自动双面打印）；`SCHEMA_MIGRATIONS["printers"]` 同步补 `"is_support_color": "INTEGER DEFAULT 0"`、`"is_support_auto_duplex": "INTEGER DEFAULT 1"`。旧库升级后彩色默认关闭（保持「旧版不展示彩色」）、自动双面默认开启（保持升级后旧行为不变）。
- 订单彩色列：`orders.use_color INTEGER`（**故意不带 DEFAULT**），`SCHEMA_MIGRATIONS["orders"]` 补 `"use_color": "INTEGER"`。语义：NULL=旧数据/旧前端未指定（完全走原有黑白流程）、1=用户选择彩色、0=用户选择黑白。
- 订单合并双面列：`orders.merge_duplex INTEGER DEFAULT 0`，`SCHEMA_MIGRATIONS["orders"]` 同步补 `"merge_duplex": "INTEGER DEFAULT 0"`。语义：0/NULL=按份打印（历史订单行为不变）、1=全部文档合并为一个双面打印流（打印派发据此走合并分支，见 6.3/6.7）。
- 写入默认设置：计价模式、单双面价格、按覆盖率计价基础价、阶梯折扣、每日限时特价、最低余额、安全覆盖率阈值、文件大小限制、最大页数、支付配置、默认打印机。
- 初始化时删除旧库遗留的 `print_mode` 设置键（打印模式配置已整体移除，避免它在后台设置接口里回显）。
- 初始化管理员账号。用户名/密码取 `config.json` 的 `admin_username` / `admin_password`（默认 `admin` / `admin123456`）；`reset_admin_password=true` 时下次启动会把已有管理员密码强制改回该值并自动写回 `false`。

注意：`get_settings()` 不再用 `@lru_cache`，而是按 `config.json` 的 `mtime`/`size` 指纹热加载——改完配置文件无需重启即生效（`reload_settings()` 可强制重读）。优先级仍是「环境变量 > config.json > 内建默认值」，所以测试里改环境变量仍要在导入 `app.main` 之前设置。

`config.json` 里的部署级键：`environment`、`app_secret`、`database_path`、`upload_dir`、`backup_dir`、`log_dir`、`cups_driver_dir`、`trusted_hosts`、`cors_origins`、`session_cookie_secure`、限流与会话有效期（`rate_limit_requests`/`rate_limit_window_seconds`/`access_token_expire_seconds`/`session_expire_seconds`/`captcha_expire_seconds`，含敏感路径专项限速 `sensitive_rate_limit_per_minute`，默认 10 次/分钟/IP，作用于登录/注册/上传，0=关闭）、登录锁定种子（`login_lock_threshold`/`login_lock_seconds`，见第 5 节，建库时播种进站点设置）、`admin_username`/`admin_password`/`reset_admin_password`、`cups_job_timeout_seconds`、`printer_probe_timeout_seconds`、`print_status_check_interval_seconds`、`print_confirm_timeout_seconds`。相对路径按配置目录归一，整个目录搬家后配置依然有效。业务配置（价格、促销、阈值、上传限制、支付、CUPS、默认打印机）不在这个文件里，它们在 SQLite 的 `settings` 表、以后台页面为准；`cups_*`/`epay_*` 只在首次建库时从 `config.json` 播种进数据库。

## 5. 认证和会话

相关文件：`backend/app/routers/auth.py`、`backend/app/services/auth_session.py`、`backend/app/routers/deps.py`、`backend/app/utils/security.py`、`frontend/src/api/client.js`。

- 密码新存储格式是 `bcrypt$...`；旧 `pbkdf2_sha256` 密码登录成功后会自动 rehash 为 bcrypt。
- 登录和注册都需要验证码。验证码通过 `GET /api/auth/captcha` 返回 PNG，答案写入 `auth_sessions` 并在验证后一次性清空。
- `GET /api/auth/csrf` 会创建访客会话并返回 CSRF token；前端非安全方法会自动携带 `X-CSRF-Token`。
- 当前 `main.py` 没有注册 `csrf_middleware`，所以 CSRF token 目前是前端兼容性准备，不是已启用的后端强制校验。
- 登录成功会同时设置 HTTP-only session cookie 和返回自定义 HMAC bearer token。`current_user()` 优先解析 `Authorization: Bearer ...`，没有 token 时回退到 session cookie。
- **Bearer token 服务端吊销（安全修复 V-05）**：`users.token_version`（`SCHEMA` + `SCHEMA_MIGRATIONS`，默认 0）是令牌版本号，登录签发的 token 携带 `ver`，`current_user()` 比对不一致（或旧 token 无 `ver`）即 401。登出（`POST /api/auth/logout` 现在要求登录）、管理员改密/封禁用户时版本号 +1，旧 token 立即失效。改认证时不要丢掉这条链路。
- 登录失败按 IP + 用户名累计，达到阈值后在锁定时长内拒绝；锁定期间返回 **429**（安全修复 V-04），非锁定失败仍返回统一 401「用户名或密码错误」。2026-10 起登录失败响应为**结构化 detail**，前端只展示后端给的信息、不做计数：
  - 普通失败：401，`detail = {"message": "用户名或密码错误，还可尝试 N 次", "remaining_attempts": N}`；
  - 达到阈值（含锁定期间重试）：429，`detail = {"message": "账号已锁定，请 N 分钟后重试", "locked": true, "retry_after_minutes": N}`。
  - 阈值/时长来自**站点设置**（数据库 `settings` 表的 `login_lock_threshold`/`login_lock_minutes`，后台「站点设置」页可改；建库时从 `config.json` 的 `login_lock_threshold`/`login_lock_seconds` 播种，缺键/非法值回退 config.json），读取逻辑在 `services/site_settings.py`，保存后下一笔登录请求即生效。对任何用户名都返回同样的提示，不泄露账号是否存在。
- 敏感路径专项限速（安全修复 V-04）：`/api/auth/login`、`/api/auth/register`、`/api/upload`、`/api/cert/generate`（证照生成，见 6.9）按 IP 限制 `sensitive_rate_limit_per_minute`（config.json 部署级键，默认 10 次/分钟，0=关闭），实现在 `middleware.py` 的 `RateLimitMiddleware._limit_for_path()`；全局默认仍是 `rate_limit_requests` 次/窗口。
- 管理员接口通过 `admin_user()` 检查 `is_admin`，普通用户会返回 403“无效请求”。

## 6. 核心业务流

### 6.1 上传、转换和安全检测

入口：`POST /api/upload`，实现于 `backend/app/routers/files.py`。

执行顺序：

1. `display_filename()` 清理展示文件名。
2. `save_upload()` 校验扩展名、大小、空文件和文件头签名，保存到 `uploads/<file_id>/original.*`；大小上限取后台「系统设置」的「文件大小限制」（数据库 `settings` 表的 `max_file_size_mb`），环境变量 `MAX_FILE_SIZE_MB` 只在设置缺失或非法时作为兜底默认值。
3. `convert_to_pdf()`：
   - PDF 原样使用。
   - PNG/JPG/JPEG 用 Pillow 转成 `converted.pdf`。
   - Office 文件调用 LibreOffice headless 转成 `converted.pdf`。转换使用带参数的 PDF 导出过滤器（`writer_pdf_Export` 开启 `EmbedStandardFonts`/`UseTaggedPDF`，`SelectPdfVersion=17` 即 PDF 1.7），强制把用到的字体子集嵌入 PDF，确保下游打印不再依赖打印机字体、避免乱码。导出参数走**三级降级链**：PDF 1.7 参数版 → PDF 1.4 参数版（`SelectPdfVersion=0`）→ 无参数默认导出——旧版本 LibreOffice 不识别 FilterData 参数时会整体转换失败，逐级降级保证「转换成功」优先于「参数最优」；三级共享 180 秒总预算，避免最坏情况把上传请求拖到 3 倍超时。转换成功后立即调用 `flatten_pdf_smask()`（见 `backend/app/services/pdf_postprocess.py`）拍平图像软遮罩，避免公式/透明图在 CUPS 光栅化时被整块丢弃。
4. `page_count()` 用 PyPDF2 读取页数，并校验最大页数；上限取后台「系统设置」的「最大页数」（数据库 `settings` 表的 `max_pages`），环境变量 `MAX_PAGES` 只在设置缺失或非法时作为兜底默认值。
5. `calculate_black_coverage_details()`（实现于 `backend/app/services/safety.py`）用 pdf2image/Poppler 把 PDF 每页转图片，用 PIL 的 `histogram()`（C 实现，替代旧的逐像素 Python 循环，大页数文档上传明显提速）统计灰度 `< 128` 的深色像素比例，保存平均覆盖率和逐页覆盖率。
6. `safety_result()` 按覆盖率阈值判断是否安全；阈值取后台「系统设置」的「覆盖率阈值」（数据库 `settings` 表的 `safety_coverage_limit`），环境变量 `SAFETY_COVERAGE_LIMIT` 只在设置缺失或非法时作为兜底默认值。因此后台改阈值后，之后新上传的文件立即按新阈值判定；已入库文件保留其上传时的 `is_safe` 结果，不会追溯重算。
7. **按需光栅化标记**（`files.needs_rasterize`，`SCHEMA` 默认 1，旧库经 `SCHEMA_MIGRATIONS["files"]` 补列）：上传入库时写入——Office 转换件标记 1（公式/图元兼容性风险）、图片转换件标记 0、PDF 用 `pdf_postprocess.pdf_has_image_masks()` 检测（含 `/SMask`/`/Mask` 遮罩=1，纯净=0）。打印派发只对标记 1 的文件做打印前整页 300dpi 光栅化（见 6.7），纯净 PDF 直接提交原文件，省掉每页光栅化的几十秒耗时并保留文字矢量；旧数据缺标记时一律按 1 处理（宁慢勿丢图）。
8. **转换后字体自检**（`audit_converted_fonts()`，见 `backend/app/services/files.py`，把「打印乱码」从黑盒变成可归因告警）：① `pdffonts` 检查转换产物是否有未嵌入（`emb=no`）字体——未嵌入意味着打印端必然字体替换；② 解析 docx/pptx 的 `fontTable.xml`（xlsx 为 `styles.xml`）提取文档请求的字体名，比对 `fc-list` 已装字体与 fontconfig 映射表（本系统 `docker/fontconfig/49-cloud-print-aliases.conf` + Debian 度量兼容映射 arial/times/courier/calibri/cambria/helvetica），缺失的字体名单独告警。两类告警都写入后台「告警」供管理员照单补装，并随上传响应返回 `font_warning`/`missing_fonts_warning` 字段。缺 `pdffonts`/`fc-list`（如 Windows 开发机）或任何异常都静默降级，绝不阻断上传。
9. 文件入库。转换或检测失败的文件也会以 `status='failed'`、`is_safe=0` 记录；安全失败、OLE 公式风险与字体自检告警都会写入 `alerts`。

补充：上传时 `inspect_ole_formula_risk()` 会探测 Office 文档中的老式 OLE 公式（MathType/公式3.0，ProgID=`Equation.*`/`DSMT4`）是否带有可渲染的 WMF/EMF 预览图。这类公式在服务器无 MathType 时无法激活渲染，但 LibreOffice 能直接光栅化其 WMF/EMF 矢量预览图，公式即可正常打印。若某文档只有 OLE 二进制而无任何预览图，则判定为高风险：上传响应返回 `formula_warning` 并写入一条告警，提示用户改用 Word/WPS 另存 PDF 后再上传。

关于「公式打印乱码/占位符」的根因与修复机制（已在样本文档 + Docker 镜像内端到端验证）：

- 根因：docx 里的化学式/离子符号/数学公式是 OLE 对象（`<w:object>` + `<o:OLEObject ProgID="Equation.DSMT4">`），能否显示完全取决于随附的 WMF/EMF 矢量预览图能否被下游工具渲染，与「字体缺失」无关。三种链路表现不同：
  - docx→PDF（本项目 LibreOffice + `libwmf-bin` 链路）：LibreOffice 能直接光栅化 WMF/EMF 预览图，公式正常打印，**本链路无需任何修复**。
  - docx→Markdown/HTML（pandoc/mammoth 等）：这些工具不认识 WMF，原样输出 `![](media/imageX.wmf)` 占位符，浏览器无法渲染，公式丢失——这正是用户看到占位符的场景。
  - 换台无 MathType 的电脑用 Word 打开：Word 激活 OLE 失败，公式可能变空白。
- 通用修复工具 `scripts/fix_docx_formula.py`：`--check` 诊断风险等级；默认修复会把每个公式的 WMF/EMF 预览图用 LibreOffice 渲染成 PNG（Pillow 裁掉整页白边并测量真实尺寸），并把 `<w:object>` 的 OLE 嵌入「降级」为标准 DrawingML 内联图片（`<w:drawing><wp:inline>...<a:blip>`），同时删除 `oleObject*.bin` 及其关系、更新 `[Content_Types].xml`。显示尺寸优先沿用原 VML `style`（作者排版意图），生成 `*_fixed.docx`。降级后任何工具都只当它是普通图片，稳定显示、不再依赖 MathType，文字内容与排版位置不变。
- 验证结论：修复后 docx 内 WMF/OLE/`<w:object>` 残留均为 0，公式全部变为 DrawingML+PNG；转 PDF 公式清晰完整、排版与原文一致；转 Markdown 时占位符从 `image*.wmf` 全部变为可被浏览器渲染的 `image*.png`。仅有 OLE 二进制而无预览图的高风险文档无法自动修复，工具会提示用 Word/WPS 另存 PDF。

关于「上传后打印时化学式整块消失（预览正常）」的根因与修复机制（已在样本文档 + Docker 镜像内端到端验证）：

- 现象区分：这与上面的「占位符/乱码」是**不同问题**。占位符是 docx→Markdown 链路的 WMF 不识别；本问题是——文档在电脑上直连打印机正常，但上传本系统打印后化学式整块消失，而网页预览完全正常。
- 根因：LibreOffice 把 docx/Office 转 PDF 时，会给带透明的图像（尤其老式 OLE 公式的 WMF/EMF 预览图、带 alpha 的插图）附加一层 `/SMask` 软遮罩表达透明。桌面打印机驱动、浏览器 PDF.js 能正确合成这层遮罩，所以「预览、直连打印」都正常；但本系统走 CUPS → `pdftoraster`/Ghostscript 光栅化打印，这条管线对 `/SMask` 支持很差，会把带软遮罩的整块图像丢弃——表现为「预览正常、打印后公式消失」。用 `pdfimages -list` 可看到原始转换 PDF 里每个公式图都配一个 `smask` 条目。
- 修复：`backend/app/services/pdf_postprocess.py` 的 `flatten_pdf_smask()` 在 LibreOffice 转出 PDF 后、入库前，遍历每页图像 XObject，把带 `/SMask` 的图像用 Pillow 按遮罩合成到纯白背景、丢弃 alpha、回写为不透明 JPEG，并删除 `/SMask`/`/Mask` 引用。首选 PyPDF2 内部 `_xobj_to_image` 解码（自动合成遮罩），失败则回退到手动读原图+遮罩用 Pillow 合成（覆盖 `/DCTDecode`、`/FlateDecode`）。该后处理是「尽力而为」：只在确有 `/SMask` 时改写文件，任何异常都安全降级为返回原 PDF，绝不阻断上传；只动图像、不动文字矢量层，正文中文仍可搜索/复制、清晰度不变。此修复对 OLE 公式、WMF/EMF、透明 PNG 插图等一切来源通用，且不改动原始文档内容与排版，因此**用户无需先跑 `fix_docx_formula.py`，直接上传原始文档即可**。
- 验证结论：样本试卷（16 个 OLE 化学式）经 `convert_to_pdf` 后，`/SMask` 从 18 降到 0，首页渲染确认 `CH₃COOH`/`CH₃COO⁻`/`H⁺`/`NaOH`/电离平衡常数等公式全部清晰完整，中文文本层 341 字零丢失；对不含 `/SMask` 的普通 PDF 返回不改写、体积不变。`backend/tests/smoke_test.py` 新增合成带 `/SMask` 的最小 PDF 单元测试覆盖此逻辑。
- 打印前整页光栅化（此问题的**根治手段**，`backend/app/services/pdf_postprocess.py` 的 `rasterize_pdf_for_print()`）：本系统真实打印是 `printer.print_pdf()` 用 `lp` 把 PDF 提交给**（通常是远端的）CUPS 打印服务器**，最终由那台机器上的 RIP（Ghostscript/cups-filters）光栅化。老式 OLE 公式、WMF/EMF 预览图、透明图元在不同版本 RIP 上表现差异很大，`flatten_pdf_smask()` 只能保证本地转出的 PDF 不带 SMask，仍无法控制远端 RIP 如何处理这些小位图——这是「本地/直连打印正常、上传本系统打印后公式仍消失」的最终原因。因此 `print_pdf()` 在 `lp` 提交前会调用 `rasterize_pdf_for_print()`：用 poppler 的 `pdftoppm`（本地光栅器，与远端 RIP 无关）把 PDF **每页渲染成 300dpi 不透明位图**，再用 Pillow 重组为「纯图像 PDF」提交打印。这样打印端收到的每页只是一张普通图片，远端 RIP 只需画一张不透明位图，彻底消除 SMask/字体/图元的一切兼容性变量——效果等同「电脑直连打印」（本地驱动同样先整页光栅化）。约定：**仅作用于打印副本**，不改动入库/预览用的原始矢量 PDF（预览仍清晰可选可搜索）；页数、页序保持一致，份数/双面参数语义不变；「尽力而为」，缺 `pdftoppm`/Pillow 或任何异常都降级为直接打印原 PDF，绝不阻断打印。验证：样本试卷经 `convert_to_pdf`→`rasterize_pdf_for_print` 后为单页纯图像（0 嵌入字体、0 `/SMask`、每页一张 A4@300dpi JPEG），150dpi 复检黑像素比矢量版还多 2.1%（保留了抗锯齿），肉眼确认公式与正文全部清晰完整；`backend/tests/smoke_test.py` 新增两页图像 PDF 单元测试覆盖此逻辑。
- 光栅化时加深偏灰笔画（解决「公式打印出来颜色很淡」，`rasterize_pdf_for_print()` 调用 `_darken_faint_content()`）：老式 OLE/WMF/EMF 公式预览图被 LibreOffice 光栅化后，笔画常呈中等灰度而非纯黑（样本试卷 300dpi 光栅化实测：公式笔画灰度铺满 80-180 区间，约占全部深色像素的 1/3），而正文是纯黑。打印机把中灰如实打成浅灰，于是「正文正常、公式颜色很淡」。因此在整页光栅化重组 PDF 前，对每页套一条分段灰度查找表（LUT）：亮于 `white_keep=235` 的像素判为背景/留白保持不变（避免整页发灰），暗于 `black_at=150` 的像素（正文 + 大部分公式笔画）直接压到纯黑（笔画变实），两者之间平滑过渡（保留抗锯齿边缘、避免笔画发糊或加粗）。默认参数经样本试卷实测标定：公式由中灰压至接近纯黑、与正文一致，白底洁净。仅加深不改版式，对纯文本页几乎无副作用（正文本就 < `black_at`，映射后仍是黑）；只作用于打印副本。验证：样本试卷经 `convert_to_pdf`→`rasterize_pdf_for_print` 后，首页化学式（`CH₃COOH`/`NaOH`/`V₁ mL`/`c₁`/`Ka` 平衡常数/离子式等）目视由明显偏灰加深为接近纯黑、清晰完整，白底无发灰；`backend/tests/smoke_test.py` 新增 `_darken_faint_content` LUT 单元测试（中灰压黑、纯黑保持、接近白不变）。彩色打印时 `rasterize_pdf_for_print(pdf_path, dpi=300, darken=False)` 会跳过这条加深 LUT（只做去 alpha/转不透明 RGB），避免把用户的彩色文件灰度化；整页 300dpi 光栅化重组在彩色、黑白、未指定三种情况下都保留（彩色位图不属于「转黑白」）。

订单创建和 `/api/price` 的 `file_ids` 模式都会拒绝任何 `is_safe=0` 的文件，不要绕过文件表中的安全字段。

### 6.2 预览

入口：`GET /api/files/{file_id}/preview`。

后端返回 PDF `FileResponse`，`Content-Disposition` 为 inline。前端首页点文件行的眼睛图标后，用 shadcn `Dialog`（`DialogScrollContent`）**弹窗内的 `iframe`** 预览 PDF——弹窗居中弹出、标题显示文件名，关闭弹窗（X 按钮 / Esc / 点遮罩）即清空 `previewFile` 并卸载 iframe；移除正在预览的文件时同样会关闭弹窗。后台订单详情则在订单详情 `Dialog` 内点文件行的「预览」按钮加载 `iframe`。缓存被清理后，预览接口会返回 404。

**文件归属校验（安全修复 V-07）**：`/api/files/{file_id}/preview`、`POST /api/check-safety`、`POST /api/price`（file_ids 模式）与 `POST /api/payment/create` 都通过归属检查——已归属登录用户的文件只有属主或管理员可读/可引用（越权一律 404/403，与「不存在」同响应，不泄露他人 file_id 存在性）；匿名访客上传的文件（`files.user_id` 为 NULL）保持公开，以支撑访客打印流程。核心实现在 `routers/files.py` 的 `ensure_file_readable()` 与 `routers/orders.py` 的 `ensure_files_accessible()`，`public.py` 复用后者。iframe 预览不带 Authorization 头，靠登录时种下的 session cookie 回退鉴权。

### 6.3 计价和促销

入口：`POST /api/price`、`GET /api/promotions`，实现于 `backend/app/routers/public.py` 和 `backend/app/services/pricing.py`。

计价模式：

- `standard`：单面按 `page_count * copies * single_price`，双面按 `ceil(page_count / 2) * copies * duplex_price`。
- `coverage_tiered`：按每页黑色覆盖率分档乘以基础价，单面使用 `coverage_single_base_price`，双面使用 `coverage_duplex_base_price`。

合并双面打印（跨文档，2026-10 起**取代**旧的「按份独立双面」功能）：

- 「合并双面打印」的定义是——用户在前台勾选后，本次订单的**全部文档按上传顺序合并为一个双面打印流**：不同文档的页面连续排到纸张正反面，两份单页文档可以打在同一张 A4 纸的正反两面（这正是旧版按份双面做不到的能力）。
- 计价：张数按 `ceil(总页数/2) × 份数` 折算，标准模式整单使用双面价（`duplex_price`）；覆盖率模式仍逐页按覆盖率分档计价（合并不改变每页单价），整单使用双面基础价（`coverage_duplex_base_price`）。合计只有 1 页时按 1 张双面价计（实际只打正面），**不再返回 400**。
- `POST /api/price` 与 `POST /api/payment/create` 都接受布尔 `merge_duplex`（缺省 False=全部单面）。旧的按份字段 `double_sided`/`file_settings`/`use_auto_duplex` 已从 `PrintSettings` 与 `/api/price` 的 file_ids 模式移除（pydantic 忽略未知字段，旧客户端携带也不会报错，只会按单面处理）；`/api/price` 的 page_count 旧模式仍保留 `double_sided` 参数。
- `calculate_files_price_detail(db, files, copies, merge_duplex=False)`：False 时全部文档按单面逐页求和；True 时走合并双面分支（`_merged_duplex_base_amount()`）。返回 detail 额外携带 `merge_duplex` 与 `total_pages`（各文档页数之和）。`resolve_file_double_sided()` 已删除。
- 打印派发：`orders.merge_duplex=1` 时 `dispatch_order_print()`（`services/print_dispatch.py`，经异步派发入口调用，见 6.7）用 `pdf_postprocess.merge_pdfs()` 把全部 `order_items` 的 PDF 按下单顺序合并成一个临时 PDF，作为一个双面任务（`double_sided=True`）调用一次 `print_pdf()`，提交后删除临时文件；合并或打印失败整单置为 `print_failed`。`merge_duplex=0/NULL` 走原有逐份循环（历史订单行为不变）。

折扣规则：

- `bulk_discount_enabled` + `bulk_discount_rules`：按 `sheet_count` 选择命中的最高门槛折扣，默认 10 张 95 折、100 张 90 折、200 张 80 折。
- `daily_limited_offer_*`：每日固定时间窗口内、剩余张数足够时可应用限时折扣。
- 多个折扣同时命中时取最终金额最低的方案。

订单会保存 `sheet_count`、`base_amount`、`discount_amount` 和完整 `pricing_detail`，后台订单列表依赖这些字段展示金额拆分。

### 6.4 下单和支付

入口：`POST /api/payment/create`，实现于 `backend/app/routers/orders.py`。

流程：

1. 校验文件 ID 非空、无重复、文件存在且全部安全；再做**文件归属校验**（安全修复 V-07，`ensure_files_accessible()`）：只能引用自己的文件或匿名访客上传的文件（`user_id` 为 NULL），引用他人文件返回 403「存在不可用的文件，请重新上传后再试」。
2. 解析合并双面：`print_settings.merge_duplex`（布尔，缺省 False）。True 时全部文档合并为一个双面打印流计价与派发，不再有「单页文档 400 拒绝」逻辑。
3. 调用 `calculate_files_price_detail()` 汇总价格；合并双面时 `order_items.is_double_sided` 全部写 1（仅作后台展示），合并派发的真正依据是 `orders.merge_duplex=1`；`orders.is_double_sided` 仍作为「双面订单」的聚合展示标识；`use_color` 写入 `orders.use_color`（None=未指定 / 1=彩色 / 0=黑白）。
4. 联系人姓名和手机号必填。登录用户可从 `users.real_name`、`users.phone` 自动补齐；手机号要求中国大陆 11 位格式。
5. 打印机能力兜底校验（`resolve_order_printer()` 按订单解析目标打印机，未指定则取默认打印机；查不到打印机记录时跳过校验以兼容老部署）：`print_settings.use_color is True` 但该打印机 `is_support_color=0` → 400「该打印机未开启彩色打印，请重新选择打印方式」；勾选了合并双面（`merge_duplex=True`）但该打印机 `is_support_auto_duplex=0` → 400「该打印机未开启自动双面打印，请重新选择打印方式」。前端已按能力条件渲染，这里是防止绕过的兜底。
6. 如果是余额支付：
   - 必须登录。
   - 校验支付后余额不能低于 `min_balance`。
   - 创建订单和支付记录后扣减余额，订单置为 `paid`。
   - 调用 `dispatch_print_files_if_present()`（`backend/app/services/print_dispatch.py`）：生产默认 `ASYNC_DISPATCH=True`，只调度后台派发线程、请求立即返回，订单先停在 `paid`，由后台线程完成派发后转 `printing`/`print_failed`（见 6.7）；`ASYNC_DISPATCH=False` 时在调用方事务内同步派发（冒烟测试用）。
7. 如果是 `alipay` 或 `wxpay`：
   - 创建 `pending` 订单和 `payments` 记录。
   - 返回 `/api/payment/submit/{order_id}`，前端跳转到该地址。

`PaymentCreateRequest.payment_method` 支持别名归一化：`epay/ali` 归一为 `alipay`，`wechat/wx/weixin` 归一为 `wxpay`，也支持 `balance`。

### 6.5 余额充值

入口：`POST /api/user/recharge`，实现于 `backend/app/routers/user.py`。

- 必须登录。
- 充值金额 1 到 2000 元，最多两位小数，充值后余额不能超过 100000 元。
- 仅支持 `alipay` 或 `wxpay`，不允许使用余额充值余额。
- 创建 `order_type='recharge'` 的订单和 `pending` 支付记录。
- 易支付回调成功后 `complete_epay_payment()` 调用 `apply_recharge_balance()`，通过 `balance_applied_at` 防止重复入账。

### 6.6 易支付提交、回调和测试单

相关文件：`backend/app/services/epay.py`、`backend/app/routers/orders.py`、`backend/app/routers/admin.py`。

- `create_epay_request()` 读取 `settings` 表中的 `epay_gateway`、`epay_pid`、`epay_key`、`public_base_url`、`frontend_base_url`，生成易支付参数并做 MD5 签名。
- `normalize_epay_gateway()` 会把旧网关地址（占位示例 `legacy-epay-gateway.example.com`）迁移到当前网关，裸域网关会补 `/submit.php`。
- `GET /api/payment/submit/{order_id}` 返回一个自动提交到易支付网关的 HTML 表单。
- `GET|POST /api/payment/notify` 校验签名、订单存在性、订单状态和金额。
- `GET /api/payment/return/{order_id}` 在同步返回时如果参数完整也会尝试完成支付，然后跳回前端打印订单页或用户中心充值结果。
- 回调是幂等的：已支付、打印中、已完成、打印失败的订单再次回调会直接返回成功状态；`paid` 但尚未派发打印的打印单会补派发。
- 后台 `/api/admin/payment-test` 会创建 `order_type='test'` 的测试单，可打开真实提交页，也可用 `/simulate-success` 构造签名成功回调做本地自测。测试单不会关联文件，也不会触发打印。

修改支付逻辑时必须保留签名校验、金额校验、充值防重复入账和打印派发幂等处理。

### 6.7 打印

相关文件：`backend/app/services/print_dispatch.py`、`backend/app/services/printer.py`、`backend/app/services/print_monitor.py`、`scripts/test_printer.py`。

打印方式完全由运行平台决定（`print_mode` 设置与 `PRINT_MODE` 环境变量已整体移除，没有可选打印模式，也没有 mock 模拟）：

- Linux/macOS：通过 CUPS 命令管理和打印，主要命令包括 `lpstat`、`lpinfo`、`lpadmin`、`lpoptions`、`cupsenable`、`cupsdisable`、`lp`、`cancel`。
- Windows：使用 PowerShell 读取系统已安装打印队列，并用 `config.json` 的 `sumatra_pdf_path` 或 `windows_pdf_print_command` 指向的 SumatraPDF 打印 PDF，未配置时回退系统 `PrintTo`；macOS 额外读取 `system_profiler SPPrintersDataType` 补充队列来源。

`printer.print_pdf()` 不再接收 `print_mode` 参数，签名为 `print_pdf(pdf_path, copies, double_sided, printer_name=None, default_printer=None, use_color: bool | None = None, rasterize: bool | None = None)`；`print_jobs_active(job_ids)` 也不再接收打印模式。

**异步派发**（支付完成后不再让 HTTP 请求等待光栅化与打印提交）：`routers/orders.py` 的余额支付路径与 `epay.complete_epay_payment(dispatch_callback=...)` 都调 `dispatch_print_files_if_present()`（`backend/app/services/print_dispatch.py`）——无 `order_items` 的非打印单（充值/测试单）直接返回；生产默认 `ASYNC_DISPATCH = True`，`schedule_order_dispatch()` 起一个后台守护线程（独立数据库连接）执行真正的 `dispatch_order_print()`，HTTP 请求立即返回，订单先停在 `paid`（前端排队口径本就把 `paid` 与 `printing` 都算作排队中）；`ASYNC_DISPATCH = False` 时回到旧的同步行为（在调用方事务内派发，冒烟测试等需要确定性断言的场景用）。防重与兜底：进程内 `_inflight_orders` 集合对同一订单去重，重复回调/并发调度不会重复打印；后台线程 `_wait_for_paid()` 最多等 ~12 秒（覆盖「先调度、后提交事务」的窗口——订单行尚不可见或仍为 pending 都继续轮询），已处于 `printing`/`completed`/`print_failed` 的订单直接退出；派发线程异常时把仍为 `paid` 的订单写回 `print_failed`（`print_error` 前缀「打印派发异常：」）；进程重启等极端情况遗留的 paid 未派发订单，由支付回调的补派发分支兜底（见 6.6）。

`dispatch_order_print()`（实现于 `print_dispatch.py`）会根据订单的 `printer_name`、settings 中的 `default_printer` 和份数下发打印，并按每个文件的 `files.needs_rasterize` 标记（见 6.1 第 7 步）向 `print_pdf()` 传 `rasterize` 参数。`orders.merge_duplex=1`（合并双面打印单）时，先用 `pdf_postprocess.merge_pdfs()` 把全部 `order_items` 的 PDF 按下单顺序合并成一个临时 PDF，作为单个双面任务调用一次 `print_pdf()`（不同文档的页面连续排到纸张正反面），光栅化标记取全部文件按需标记的「或」，提交后删除临时文件；`merge_duplex=0/NULL`（历史订单）保持逐份读取 `order_items.is_double_sided` 作为该文件的单双面参数分别调用 `print_pdf()`。成功后订单状态更新为 `printing`，失败（含合并失败）则为 `print_failed` 并写入 `print_error`。

`print_pdf()`（CUPS 路径）在用 `lp` 提交前按 `rasterize` 三态决定是否调用 `rasterize_pdf_for_print()`（见 `backend/app/services/pdf_postprocess.py`）：`None`（旧调用方兼容，保持「一律光栅化」）或 `True` 时光栅化，`False` 时跳过——纯净 PDF 与图片转换件直接提交原始矢量文件，省去每页 300dpi 光栅化的几十秒耗时并保留文字矢量。光栅化用 poppler `pdftoppm` 把待打印 PDF 每页渲染成 300dpi 不透明位图并重组为「纯图像 PDF」再提交，远端 CUPS/打印机的 RIP 只需绘制不透明图片，彻底规避老式 OLE 公式/WMF/EMF/透明图元在远端 RIP 上被整块丢弃的「上传打印后化学式消失」问题（详见 6.1）。它仅作用于打印副本、不改动入库/预览的原始 PDF，页数页序不变，光栅化失败会安全降级为直接打印原 PDF；打印任务提交后本地临时图像 PDF 会被删除。光栅化每页还会经 `_darken_faint_content()` 套分段灰度 LUT，把老式公式预览图的中灰笔画压到纯黑、保护白底不发灰，解决「公式打印出来颜色很淡」（详见 6.1）。Windows 走 SumatraPDF/`PrintTo`，本身就是本地整页光栅化，不额外处理。

彩色打印（`use_color` 三态，保证向后兼容）：`None`（历史订单/旧前端未携带）**不下发任何色彩参数**、保留原有加深 LUT，与本次改动前完全一致；`True` 时 CUPS 分支给 `lp` 追加 `-o print-color-mode=color`，并以 `rasterize_pdf_for_print(pdf_path, darken=False)` 光栅化，只去透明、不做加深/灰阶映射，文件按原始色彩提交；`False` 时追加 `-o print-color-mode=monochrome` 并沿用加深逻辑。整页 300dpi 光栅化重组在三种情况下都保留（它是防「公式整块消失」的根治手段，彩色位图不属于转黑白）。`dispatch_order_print()` 读取 `orders.use_color`（NULL→None，否则 bool）作为 `use_color` 传给 `print_pdf()`。Windows（SumatraPDF/`PrintTo`）分支目前只处理打印机与份数，`double_sided` 与 `use_color` 都未生效（与改动前一致）。

`start_print_status_monitor()` 会启动后台线程，按 `config.json` 的 `print_status_check_interval_seconds`（默认 30）检查 `status='printing'` 的订单；该值每轮重新读取，改完配置文件重启或等下一轮即生效。CUPS 能确认任务不在未完成队列时订单置为 `completed`；无法确认且超过 `print_confirm_timeout_seconds`（默认 600 秒）会置为 `print_failed`。Windows 下无法可靠确认队列完成，通常保持人工/后台状态处理。

本系统已移除 mock 模拟模式，所有打印都是真实打印。涉及打印的改动务必先在受控环境（如指向测试用 CUPS 队列或备用打印机）验证，再接入生产打印机。支付回调可能触发真实打印，联调真实支付前要确认 CUPS 地址和默认打印机。

### 6.8 兑换码

相关文件：`backend/app/services/redemption.py`、`backend/app/routers/admin.py`（后台管理接口）、`backend/app/routers/user.py`（用户兑换）、`frontend/src/views/AdminView.vue`、`frontend/src/views/DashboardView.vue`。

- 数据表：`redemption_codes`（`code` 唯一、`amount` 面额、`usable_count` 可兑换次数、`used_count` 已兑换次数、`per_user_max_times` 每个登录用户最大兑换次数、`valid_days` 有效天数、`expires_at` 精确到期时间）和 `redemption_logs`（每次成功兑换记录用户与到账金额，`per_user_max_times` 的「该用户已兑换几次」就统计这张表）。
- **两种有效期方式**（`expiry_mode` 语义，**刻意不新增数据库列**，靠 `(valid_days, expires_at)` 组合区分，`expiry_mode_of(code_row)` 读取）：
  - `days`（默认，按有效天数）：沿用原逻辑，`valid_days>0` 时 `_compute_expires_at(valid_days)` 以 `now + valid_days` 天算出 `expires_at`；`valid_days=0` 表示永久有效（`expires_at=NULL`）。存量数据全是这一种，行为不变。
  - `date`（指定到期日期）：管理员直接选一个日期，`normalize_expire_date(value)` 归一化成**当天 23:59:59** 的 `isoformat(timespec="seconds")` 写入 `expires_at`，同时把 `valid_days` 强制写成 0（保证组合唯一、且「过期判断优先」无需改动即可复用）。`create_code(..., expires_at=...)` 与 `batch_generate_codes(..., expires_at=...)` 的第 7/6 个关键字参数就是入口。日期串非法时 `normalize_expire_date()` 返回 `None`，服务层回退到「按天数」逻辑；写接口的前端侧由 pydantic 校验拦住非法/缺失日期（见下）。
  - 判断顺序不变：`code_status()` 先比 `expires_at`（`datetime.now() >= fromisoformat(expires_at)` → `expired`），再比 `used_count >= usable_count` → `used`，最后 `unused`。
- **两种使用限制模式**（`per_user_max_times` 整数语义，`SCHEMA` 默认 `INTEGER DEFAULT 0`，`SCHEMA_MIGRATIONS["redemption_codes"]["per_user_max_times"] = "INTEGER DEFAULT 0"`，旧库升级后默认关闭、行为不变）：
  - `per_user_max_times=0`（未开启，默认）：保持原有「按总可用次数」逻辑不变——只靠 `usable_count`/`used_count` 判定，同一用户可反复兑换直到次数用尽。
  - `per_user_max_times=N`（N>0，开启「限制每个用户最大兑换次数」）：**双重校验**——既要满足全局 `used_count < usable_count`，又要满足该用户历史兑换次数 `< N`，两者任一不满足都直接拒绝。不同用户各自独立计数。`used_count` 照常累加并参与状态判定，全局用满后 `code_status()` 返回 `used`（**不再有「恒返回 unused」的特例**），过期判断始终优先。
  - 该用户已兑换次数用 `count_user_redemptions(db, code_id, user_id)`（`SELECT COUNT(*) FROM redemption_logs WHERE code_id = ? AND user_id = ?`）统计；`has_redeemed(db, code_id, user_id)` 保留为 `count_user_redemptions(...) > 0` 的便捷包装。读取上限用 `per_user_max_times_of(code_row)`（列缺失或非法一律返回 0）。
- 旧列 `per_user_once`（「每个登录用户仅可使用一次」）已被 `per_user_max_times` 取代，代码不再读写该列。`backend/app/database.py` 的 `migrate_redemption_per_user_limit(connection)` 在 `init_db()` 里于 `executescript(SCHEMA)` + `ensure_columns()` 之后执行一次等价换算：`UPDATE redemption_codes SET per_user_max_times = 1 WHERE per_user_once = 1 AND per_user_max_times = 0`。幂等，且 `PRAGMA table_info` 发现缺 `per_user_once` 或 `per_user_max_times` 任一列就直接跳过（新库无旧列，不做任何换算）。
- 后台「手动新增」走 `POST /api/admin/redemptions`，payload 为 `AdminRedemptionCreate`。**`code` 允许留空**（`code: str = Field(default="", max_length=64)`，没有 `min_length`）：留空、空串、纯空白或不传该字段时，`create_code()` 调 `_random_unique_code()` 自动生成随机码（与批量生成同一字符集，`CODE_ALPHABET` 12 位大写字母数字，查库去重、最多重试 20 次），返回体里的 `code` 即最终码；填写内容则去首尾空白并转大写后使用。前端弹窗提示「自定义兑换码（留空随机生成）」与后端行为一致，表单里兑换码输入框本来就不是必填项。
- 其余字段仍是校验项：`amount` 必须 >0 且 ≤100000，`usable_count` ≥1，`valid_days` ≥0；`per_user_max_times` 为 `int = Field(default=0, ge=0, le=100000)`（缺省即关闭限制）；`expiry_mode: str = Field(default="days")` 与 `expire_date: str | None = Field(default=None, max_length=32)` 控制有效期方式；兑换码重复返回 409「兑换码 X 已存在」。**只有 `code` 一项可以缺省，改校验时不要回退成必填**。`create_code(db, code, amount, usable_count=1, valid_days=0, per_user_max_times=0, expires_at=None)` 是**位置参数**签名（`expires_at` 是第 7 个参数、按关键字传），`backend/app/routers/admin.py` 的 `create_redemption_code()` 必须把 `payload.per_user_max_times` 作为第 6 个位置参数透传，并把 `expires_at=payload.expire_date` 作为关键字参数透传——**漏传前者会让「限制每个用户最大兑换次数」静默失效，漏传后者会让「指定到期日期」静默退化成永久有效**。`AdminRedemptionCreate` 上的 `@model_validator(mode="before")`（`normalize_redemption_payload`）除了把旧前端的 `per_user_once=True` 且没带 `per_user_max_times` 折算为 1（向后兼容，不要删），还负责有效期归一：`expiry_mode != "date"` 时强制改回 `"days"` 并清空 `expire_date`（避免两种方式同时生效），`"date"` 时 `expire_date` 必填且必须能被 `datetime.strptime(text, "%Y-%m-%d")` 解析（否则抛 `ValueError("请选择有效的到期日期（格式 YYYY-MM-DD）")`），并把 `valid_days` 强制归零。`AdminRedemptionBatchCreate` 用同一套 `normalize_expiry` 规则。
- 其它后台接口：`POST /api/admin/redemptions/batch` 批量随机生成（**不写 `per_user_max_times`，默认 0，保持原总次数逻辑**；有效期同样支持 `expiry_mode`/`expire_date`，路由把 `expires_at=payload.expire_date` 传给 `batch_generate_codes(..., expires_at=...)`）、`GET /api/admin/redemptions` 列表（支持 `search` 与分页，序列化输出含 `per_user_max_times` 与 `expiry_mode` 供列表展示，**不再输出 `per_user_once`**）、`GET /api/admin/redemptions/{code_id}/logs` 兑换记录、`DELETE /api/admin/redemptions/{code_id}` 删除。
- 用户侧：`POST /api/user/redeem`（`RedeemRequest.code` 仍必填，个人中心「兑换码充值」不允许空提交），大小写不敏感，依次校验存在/过期/**该用户历史兑换次数是否已达 `per_user_max_times`（仅 `per_user_max_times>0` 的码）**/剩余总次数后加余额并写日志。
- 兑换接口的错误处理：业务失败返回 400，`detail` 为 `{code, message}` 结构（`REDEMPTION_CODE_NOT_FOUND`「兑换码不存在」、`REDEMPTION_CODE_EXPIRED`「兑换码已过期」、`REDEMPTION_CODE_USED_UP`「该兑换码可用次数已用完」、**`REDEMPTION_PER_USER_LIMIT`「您已兑换过该兑换码，每个用户最多可兑换 N 次」（由 `_per_user_limit_message(max_times)` 生成，N 即该码的 `per_user_max_times`；旧的 `REDEMPTION_ALREADY_REDEEMED` 已移除）**、`REDEMPTION_BALANCE_LIMIT`「兑换后余额不能超过 100000 元」、`USER_NOT_FOUND`）；数据库异常或未预期异常返回 500，同样带中文 `message` 并用 `logger.exception` 记录堆栈，**绝不把原始异常或纯文本 500 抛给前端**。前端 `frontend/src/api/client.js` 的 `formatErrorMessage()` 取 `detail.message` 展示在弹窗里（因此新增错误码无需改前端）。
- 入账事务：`redeem()` 里 `db.rollback()`（清掉残留隐式事务）→ `BEGIN IMMEDIATE`（显式写事务，并发兑付串行化）→ **两道校验、一条占用写法**（不再按模式分叉）：
  - **第一重·每用户上限**：写锁内**再次**统计该用户历史兑换次数（`count_user_redemptions(db, code_id, user_id)`，权威判据，防止同一用户并发重复提交绕过预检），达到该码的 `per_user_max_times` 就直接抛 `REDEMPTION_PER_USER_LIMIT`。这一步必须在占用全局次数**之前**判定。
  - **第二重·全局总次数**：统一执行条件 `UPDATE redemption_codes SET used_count = used_count + 1 WHERE id = ? AND used_count < ?` 并校验 `rowcount != 1` → `REDEMPTION_CODE_USED_UP`。**不要**给 `per_user_max_times>0` 的码改成无条件累加——那正是旧版「每用户一次就忽略总次数」的错误语义，会让 `usable_count=1` 时第二个用户也被放行。
  - 后续一致：事务内重读余额做上限校验 → `UPDATE users SET balance = ROUND(balance + ?, 2)` → 写 `redemption_logs` → `db.commit()`；任何一步失败都 `rollback()`，保证「占用次数 + 加余额 + 写日志」要么全成功要么全回滚。**每用户上限的判定必须放在 `BEGIN IMMEDIATE` 之内复查一次**，只靠事务外预检在并发下会重复入账。
- **命名陷阱（历史 500 的根因）**：`backend/app/routers/user.py` 必须用别名引入服务函数（`from ..services.redemption import redeem as redeem_redemption_code`）。若写成 `from ..services.redemption import redeem as redeem_code`，模块级名字 `redeem_code` 会被下面同名的路由函数覆盖，路由就会调用自己（`AttributeError: 'sqlite3.Connection' object has no attribute 'code'`），前端只看到纯文本 `Internal Server Error`。

### 6.9 证照打印（隔离模块 app/cert/ + frontend/src/cert/）

方案依据 `doc/CERT_PRINT_PLAN.md`；实现 100% 集中在 `backend/app/cert/` 与 `frontend/src/cert/` 两个目录，主程序只留预算表内的少量钩子（见下），可整体回滚（删两个 cert 目录 + 还原钩子）。

**硬性隔离约束**：新增文件只进两个 cert 目录（唯一例外 `backend/tests/cert_feature_test.py`）；主程序对 cert 的引用只允许出现在：`main.py`（include_router ×2 + 启动清理线程）、`database.py`（`init_db()` 内 `ensure_schema()`，函数内延迟导入）、`services/pricing.py`（`calculate_files_price_detail()` 末尾 `apply_cert_pricing()`，函数内延迟导入）、`middleware.py`（敏感路径集合 + `/api/cert/generate`）、`requirements.txt`（+ `opencv-python-headless`）、前端 `router/index.js`（引入 `cert/routes.js`）、`AppHeader.vue`（桌面导航项）、`MobileTabbar.vue`（三格扩四格）、`AdminView.vue`（「证件照管理」tab：import + 内嵌 `cert/CertAdminPanel.vue`，位于「配置」下方）、`AuthView.vue`（登录后按 `?redirect=` 站内回跳，只允许 `/` 开头且非 `//` 的路径）。依赖方向 cert → core 允许，core → cert 仅上述注册点。

- **数据表（cert/schema.py 自持）**：`cert_templates`（code 唯一、layout_json 版式 + 门户卡片元数据、price 独立单价 NULL=回退标准价、enabled 启停、sort）与 `cert_docs`（生成件记录：user_id/template_code 冗余/pdf_file_id/page_count/used_manual_crop/status/expires_at）。`ensure_schema()` 幂等：建表 + 播种 3 个内置模板（id_card / hukou / doc2up——doc2up 是两页合一打印的「登记行」，无 slots 版式、layout_json 仅携带门户卡片元数据，用于后台统一启停/独立单价与门户卡片驱动，见 6.10；来自 `templates_seed.py`，P0 版式只随代码发布——每次启动同步 name/layout_json/sort 但**不覆盖**后台改过的 price/enabled，且**清理已从种子里移除的内置模板**）+ 播种设置键 `cert_retention_hours`（默认 24，0=立即到期）与 `cert_daily_generate_limit`（默认 20，0=不限制）。
- **生成管线（cert/render.py + detect.py）**：槽位照片以**内存字节流**直接进管线（EXIF 矫正 → 裁剪 → 增强 → LANCZOS 重采样 → 300dpi A4 合成 → Pillow 存单页 PDF（resolution=300）），原始照片全程不落盘（比临时目录更强）。自动识别是可选增强：`detect.py` 导入 OpenCV 失败自动降级，手动四点裁剪用纯 Pillow `Image.transform(QUAD)`（坐标归一化 0–1，顺序 TL,TR,BR,BL）兜底；照片短边 < 目标像素 60% 或识别置信度不足时按槽位返回 `DETECT_FAILED`（detail 结构 `{code, slots}`），前端仅对失败槽位弹四点裁剪。生成件写 `files` 表（`is_safe=1` 受信产物、`needs_rasterize=0`、`black_coverage/page_coverages` 为 NULL——照片页覆盖率无意义），`uploads/<file_id>/converted.pdf`；身份证槽位 85.6×54mm 1:1 精确缩放；户口本模板是**户主页 + 个人页两个槽位（holder/personal）上下排布排入同一页 A4**（各 95×130mm contain 包围框，y=13.5/153.5、x=57.5 居中同列，与身份证正反面版式一致，正式上线前须实物样张校准）。
- **计价钩子（cert/pricing.py 的 `apply_cert_pricing`）**：在 `calculate_files_price_detail()` 标准计价完成后对 `cert_docs.pdf_file_id` 命中的文件重算——模板 `price` 非空 → 单价 × 页数 × 份数（前端统一「元/页」；证照件 1 页/版，doc2up 按版面数，见 6.10）；为空 → 回退 standard 单面价（按页，与站点定价模式无关）；**doc2up 登记行例外：未设价时不进钩子**，保持主程序标准/覆盖率计价（与登记前一致）；**任何情况下证照件不落入 `coverage_tiered`**。混合订单逐文件分支后求和并重建折扣明细；detail 携带 `cert_files`（模板名/单价/mode）随 `orders.pricing_detail` 入库。与 `services/pricing.py` 互相都不在模块顶层 import 对方（延迟导入防加载环）。
- **清理与隐私**：`cert/cleanup.py` 守护线程每小时清 `expires_at <= now` 的生成件；跳过仍被 `pending/paid` 订单引用的文件；磁盘文件必删（隐私红线），`files` 行仅无订单引用时可删——被历史订单引用时置 `status='expired'` 保留外键完整性（预览自然 404）。用户可 `DELETE /api/cert/docs/{id}` 手动删除（打印队列中的除外）。日志只记 doc_id/模板/用户/结果。
- **前端模块化**：门户 `/cert` 完全由 `GET /api/cert/templates` 驱动（模板停用卡片即时消失、模块页深链显示「已下架」）；一个功能 = 一个模块页文件（`modules/IdCardModule.vue` 等，声明 templateCode/slots/文案），公共骨架 `ModuleShell.vue` 编排「槽位上传 → 生成 → A4 预览 → 下单」，模块间零引用。**模块页路由规则：所有功能模块页（含 doc2up）统一挂在 `/cert/` 下，后缀 = 模板/模块 code 的 kebab-case**（`id_card`→`/cert/id-card`、`hukou`→`/cert/hukou`、`doc2up`→`/cert/doc-2up`），门户 `/cert`。下单闭环不改现有接口：`/api/price`（file_ids 模式，计价钩子内部生效）+ `POST /api/payment/create`（balance，余额一键打印），彩色选项严格跟随 `/api/print-options`。证件照管理已并入后台 AdminView 的「证件照管理」tab（原 `/cert-admin` 独立小页与路由已移除，面板组件 `cert/CertAdminPanel.vue`），列出**全部**模板（含 doc2up），设置项完全统一：启停 + 独立单价（「元/页」）+ 保留期/每日上限（证照件 1 页/版、doc2up 按版面数计）。新增一个证照功能的成本 = 1 个模块页文件 + `cert/routes.js` 一行 + `constants.js` 路由映射一行 + `templates_seed.py` 一条模板数据，主程序零改动。

### 6.10 两页合一打印（隔离模块 app/doc2up/ + frontend/src/doc2up/）

门户卡片（`/cert` 里的「两页合一打印」，由 `cert_templates` 的 doc2up 登记行驱动、随后台「证件照管理」启停显隐，不再是无开关的静态卡）进入模块页 `/cert/doc-2up`：上传文档 → 复用主程序 `POST /api/upload`（转换 PDF + 安全检测）→ `POST /api/doc2up/create {file_id}` 合成 → 预览 → 余额下单。登记行停用或缺失时，模块页深链显示「已下架」（与 cert 模块页行为一致）、`POST /api/doc2up/create` 返回 400「两页合一打印功能已下架」。

- **合成规则（service.py）**：源 PDF 按块（10 页/块）经 pdf2image/pdftoppm 光栅化（峰值内存可控），每页旋转 90° 顺时针后两页拼一页 A4——竖向文档 → A4 竖版上下两栏（每栏 210×148.5mm）；横向文档 → A4 横版左右两栏（每栏 148.5×210mm）；缩放比均为 1/√2。版式方向由**首页**决定、全文档统一旋转（混合方向文档中不匹配页躺放，与实体打印机 2-up 一致）；奇数页最后一页单独占半版；半版交界画浅灰裁切线。输出 300dpi 纯位图 PDF（Pillow `save_all` + 生成器逐版追加，页尺寸自动为 A4）。
- **入库**：写 `files` 表（user_id=请求用户、`原名-两页合一.pdf`、page_count=版面数、is_safe=1 受信产物、needs_rasterize=0、black_coverage/page_coverages 由合成位图实时统计——覆盖率计价模式下按版面覆盖率正确计价）。源文件须存在、`is_safe=1` 且归属当前用户（或匿名访客上传，V-07 同级；非属主与不存在同响应 404）。
- **计价/下单与登记行**：合成时把产物登记进 `cert_docs`（`status='doc2up'`、`template_code='doc2up'`、page_count=版面数、`expires_at` 占位 2999 年）——后台「证件照管理」给模板设置的独立单价经证照计价钩子按 **单价×版面数×份数** 生效；未设价时该登记行不进钩子，保持标准按页/覆盖率计价（页数=版面数，与登记前行为一致）。`status='doc2up'` 与证照件的 `'active'` 区分：**不计入**证照保留期清理与证照每日生成上限（两处查询只统计 `'active'`），文件缓存仍走主程序统一清理。双面勾选映射 `print_settings.merge_duplex`（单文件订单即本文件双面，按 ceil(页数/2)×双面价），前端仅当打印机 `is_support_auto_duplex` 且合计页数≥2 时展示；彩色跟随 `/api/print-options`。
- **前端复用**：模块页 `frontend/src/doc2up/Doc2UpModule.vue` 复用 cert 的 `CertOrderPanel`（该面板已通用化：`template` 可选、`supportDuplex` 开关、`product-name` 展示名；证照模式仍带知情确认声明，文档模式为普通确认勾选）。
- **隔离钩子（超出 cert 预算表的新增行，合计 4 行）**：`main.py`（+1 import、+1 include_router）、`frontend/src/router/index.js`（+1 import、+...doc2upRoutes 展开）；门户卡片由 `cert_templates` 的 doc2up 登记行驱动（`cert/templates_seed.py` 播种、`cert/CertPortal.vue` 模板渲染，均为 cert 模块文件，不算主程序改动）。可回滚：删两个 doc2up 目录 + 还原 4 行钩子（同时从种子里移除 doc2up 登记行）。

## 7. API 路由概览

公开接口：

- `GET /api/health`：健康检查。
- `GET /api/ready`：数据库就绪检查。
- `GET /api/site-settings`：公开站点配置（网页标题 `site_title`、favicon 地址 `site_favicon_url`、ICP 备案号 `site_icp_number`），前端应用启动时拉取一次并全局应用；字段留空表示使用前端默认值。存取逻辑在 `services/site_settings.py`（`settings` 表 key-value）。
- `GET /api/site/favicon`：输出后台上传的站点图标字节流（未设置时 404）；地址带版本戳 `?v=N` 供长缓存。
- `GET /api/promotions`：前台展示当前促销。
- `GET /api/limits`：前台读取生效的上传限制（`max_file_size_mb`、`max_pages`）；优先取后台设置，缺省回退环境变量默认值。首页用它渲染上传提示文案。
- `GET /api/print-options`：前台读取当前（默认）打印机的打印能力，返回 `{"printer_configured", "is_support_color", "is_support_auto_duplex"}`；取 `settings` 表的 `default_printer`，未配置默认打印机或查不到该打印机记录时 `printer_configured=false` 且两项能力均为 false。首页用它做条件渲染，不硬编码。**安全修复（V-10.1）：不再返回 `printer_name`**，避免向匿名访客泄露具体打印机名称。
- `POST /api/price`：按页数或文件列表、份数、单双面计算价格。

认证接口：

- `GET /api/auth/csrf`：创建/读取访客会话和 CSRF token。
- `GET /api/auth/captcha`：生成验证码 PNG。
- `POST /api/auth/register`：用户名/密码/验证码注册，可带邮箱/手机号。
- `POST /api/auth/login`：登录并返回 token（携带签发时的 `token_version`）。
- `POST /api/auth/logout`：**需要登录**（bearer 或 session 均可）；销毁会话、清除 cookie，并把当前用户 `token_version` +1 吊销其全部 bearer token（安全修复 V-05）。
- `GET /api/auth/me`：读取当前用户。

首次部署恢复接口（`/api/setup/restore/*`，路由在 `routers/admin.py` 的 `setup_router`）：`GET /api/setup/restore/status` **安全修复（V-01）**——仅当系统完全未初始化（users/files/orders/payments 全空）时返回 `{"available": true}`（登录页 `AuthView.vue` 的恢复流程依赖它）；系统已有数据时一律 401，不向匿名访客泄露初始化状态。`POST /api/setup/restore/inspect` 与 `POST /api/setup/restore` 由 `services/backup.py` 的 `is_initial_restore_available()` 守门：未初始化时允许匿名（首次部署恢复），已初始化时返回 403 提示走管理员后台。

文件接口：

- `POST /api/upload`：上传、转换、检测并入库。匿名上传保留（访客打印核心流程），但受敏感路径专项限速（默认 10 次/分钟/IP，按 `sensitive_rate_limit_per_minute` 配置）且文件归属上传者（登录用户）或标记为 guest（`user_id` NULL）；畸形/损坏文件转换失败统一返回 400「文件无法解析…」而非 500（安全修复 V-10.2）。响应携带 `formula_warning`（OLE 公式缺预览图）与 `font_warning`/`missing_fonts_warning`（字体自检）提示字段，同时写入后台告警（见 6.1 第 8 步）。
- `GET /api/files/{file_id}/preview`：PDF inline 预览。
- `POST /api/check-safety`：读取某文件安全检测结果。

订单和支付：

- `POST /api/payment/create`：创建打印订单。
- `GET /api/orders/{order_id}`：查询订单，并在必要时刷新打印状态。**匿名/非属主访问只返回状态摘要字段**（`ANONYMOUS_ORDER_FIELDS`：id、order_type、status、total_amount、copies、is_double_sided、use_color、sheet_count、created_at、paid_at、printed_at、print_error + queue），不泄露 user_id、联系人姓名/手机号、支付与计价明细；属主（bearer/session 均可）和管理员拿全量（安全修复 V-03）。支付结果页匿名轮询只消费摘要字段。
- `GET /api/payment/submit/{order_id}`：返回易支付自动提交页。
- `GET|POST /api/payment/notify`：易支付异步回调。
- `GET /api/payment/return/{order_id}`：易支付同步返回并跳回前端。

用户中心：

- `GET /api/user/orders`：当前登录用户订单分页，支持 `limit`（默认 10，1-50）、`offset`（默认 0）。返回 `{items, total, has_more, total_spent}`，`total_spent` 为全量打印消费，供前端「加载更多」与统计使用。
- `PUT /api/user/profile`：绑定/更新真实姓名和手机号。
- `POST /api/user/recharge`：创建余额充值订单。
- `POST /api/user/redeem`：个人中心「兑换码充值」，`code` 必填，校验存在/过期/剩余次数后按面额加余额并写 `redemption_logs`；错误统一返回标准 JSON（`detail` 为 `{code, message}` 的中文提示），不返回纯文本 500。详见 6.8。

证照打印接口（`app/cert/router.py`，见 6.9）：

- `GET /api/cert/templates`：公开只读，返回 `enabled=1` 的模板（槽位摘要、`price_mode`、门户卡片元数据 `card`），门户卡片完全由它驱动。
- `POST /api/cert/generate`：登录 + 敏感路径限速 + 每日上限（超限 429）；multipart 入参 `template_code`、可选 `cut_guides`、每槽位图片 `slot_<key>`、可选手动四点 JSON `quad_<key>`（归一化 0–1，TL,TR,BR,BL）。自动识别失败且无手动四点 → 400 `detail={"code":"DETECT_FAILED","slots":[...]}`。原始照片全程不落盘。成功返回 `{cert_doc_id, file_id, page_count, preview_url, expires_at}`。
- `GET /api/cert/docs`：当前用户生成件分页（limit 1-50 / offset）。
- `GET /api/cert/docs/{id}/preview`：生成件 PDF inline 预览（属主或管理员，非属主与不存在同响应 404）。
- `DELETE /api/cert/docs/{id}`：属主手动删除（被 pending/paid 订单引用时 400）。

两页合一打印接口（`app/doc2up/router.py`，见 6.10）：

- `POST /api/doc2up/create`：登录；入参 `{file_id}`（主程序 `POST /api/upload` 的产物），把已转换好的 PDF 合成为两页合一打印件（每两页旋转 90° 缩排到一页 A4），返回 `{file_id, source_file_id, page_count, preview_url}`（预览复用 `/api/files/{id}/preview`）。受 `cert_templates` 的 doc2up 登记行启停控制：停用后返回 400「两页合一打印功能已下架」。

后台接口均在 `/api/admin` 下，需要管理员 token 或 session，包含：

- `/dashboard`、`/daily-stats`（后台概览「每日数据统计」：`days` 取 1-90、默认 7，按**本地时区**返回每日订单数、收入、打印失败数与失败率，聚合逻辑在 `backend/app/services/stats.py`；**收入只计已支付订单**（`status` ∈ `PAID_STATUSES` = paid/printing/completed/print_failed，常量由 `stats.py` 导出、`/dashboard` 复用）——待支付（pending）订单计入订单数但**不计入销售额**，两处口径一致，不按 `order_type` 过滤）、`/orders`、`/orders/{id}/detail`、`/orders/{id}/mark-complete`、删除单个订单、删除未支付订单、批量删除未支付订单。
- `/file-cache/cleanup`：按时段统计或清理上传缓存，可选择是否包含已关联订单文件。
- `/users`：创建、编辑、启停、删除用户，余额增减或设置；保护最后一个管理员和当前管理员。
- `/redemptions`：手动新增（`code` 可留空，留空由后端自动生成随机码；可传 `per_user_max_times` 设置「每个用户最大兑换次数」，正整数=限制、0 或缺省=不限制；有效期用 `expiry_mode`（`days`/`date`）+ `expire_date` 二选一）、批量随机生成（同样支持 `expiry_mode`/`expire_date`）、列表与搜索、兑换记录、删除；详见 6.8。
- `/settings`：系统价格、促销、阈值、文件大小/页数上限和默认打印机。接口保存后会返回 `notices`，提示哪些键（`cups_*`/`epay_*`）的实际值来自建库时写入的 `config.json` 快照、之后再改 `config.json` 不会覆盖后台设置（库优先）；**后台页面不再展示这些 notices**（否则成功保存也会出现红色提示），保存成功只在页面顶部显示绿色「保存成功」。
- `/site-settings`：站点设置（后台「站点设置」页）。`GET` 回显全部字段（含 `site_favicon_mode`、`site_favicon_effective_url` 生效地址、`login_lock_threshold`/`login_lock_minutes`）；`PUT` 只更新传入的键（`SiteSettingsUpdate` 全字段可选），保存后立即生效并返回最新回显；`POST /site-settings/favicon` 上传 `.ico`/`.png` 图标（≤200KB，按文件头魔数校验），以 data URI 存入 `settings` 表并立即切换为 upload 模式。`site_favicon_mode=upload` 只能由上传接口写入，PUT 直接传会被 400 拒绝。
- `/payment-settings`、`/payment-test`：易支付配置、配置校验、测试单查询和模拟成功。
- 打印机管理（实现于 `backend/app/services/cups_printer.py`）：`/printer-system`（运行环境与 CUPS 连通性诊断）、`/printers`（枚举真实队列）、`/printer-drivers` 与 `/printer-drivers/ppd`（驱动列表与上传 PPD）、`/printer-info`、`/printer-uri/probe`、`/printers/{name}`（查询/编辑/删除）、`/printers/{name}/default`、`/printers/default/clear`、`/printers/{name}/enabled`、`/printers/{name}/test-page`、`/printers/{name}/test-result`、`/printers/{name}/jobs`、`/cups/logs`、`/cups/queues`、`/cups/diagnostics`。打印机配置记录带 `is_support_color`、`is_support_auto_duplex` 两个能力字段，`GET /api/admin/printers`（列表）与 `GET /api/admin/printers/{printer_name}`（详情）都会返回；编辑走 `PATCH|PUT /api/admin/printers/{printer_name}`（payload 为 `PrinterUpdate`，两项能力为可选 `bool | None`，None=不修改），本仓库没有新增打印机的 POST 路由。
- `/alerts/{id}/handle`：处理异常告警。
- 证照打印管理（`app/cert/admin_router.py`，独立于 admin.py；后台 AdminView「证件照管理」tab / `cert/CertAdminPanel.vue` 使用）：`GET|PATCH /api/admin/cert-templates[/{code}]`（列表含停用模板；PATCH 改 `price`（传 null = 清空独立价回退标准页价）与 `enabled`；**全部模板（含 doc2up）设置项统一**——doc2up 设价后经其 cert_docs 登记行按 单价×版面数×份数 生效）、`GET|PUT /api/admin/cert-settings`（`cert_retention_hours` / `cert_daily_generate_limit`，保存即时生效；上限只统计 `status='active'`，doc2up 登记行不计入）。

## 8. 前端结构和页面

`frontend/src/App.vue` 是全局壳：`<a class="sr-only">` 键盘跳转入口（focus 时出现，指向 `#main-content`），`<AppHeader />` 顶栏（品牌 logo 徽标内嵌 lucide Printer 图标 + 文案「PrintHub 云打印」，桌面端 md+ 显示文字导航：打印/模板打印/订单/个人中心/后台，右侧是 `ThemeToggle` 亮暗切换按钮与登录/退出按钮），`<MobileTabbar />` 手机端（< md）底部三格 Tab（首页/订单/我的，admin 路由下不渲染），以及全局 `<Toaster />`（vue-sonner 轻提示）。导航目标与互斥高亮由 `src/composables/useNavTargets.js` 提供（`ordersTarget`/`mineTarget` 带 `?tab=`，`isOrders`/`isMine` 互斥，规避 RouterLink 按路径自动高亮忽略 query 的坑）。应用启动时调用 `auth.loadMe()` 和 `site.load()`（后者拉取 `GET /api/site-settings` 并全局应用网页标题、favicon、备案条——登录页/前台/后台共用，见 `stores/site.js`；favicon 通过替换唯一的 `<link rel="icon">` 生效，未配置时回退 index.html 的内联 SVG 与默认标题）。前台路由在 `<main>` 内 RouterView 之后渲染 `<IcpFooter />`（ICP 备案条：仅当后台填写了备案号才渲染，非固定定位随内容排在页尾，居中小字、`text-muted-foreground`，点击在新窗口打开 `https://beian.miit.gov.cn/`；手机端位于底部 Tab 栏预留 padding 之内侧，不会重叠）；后台路由的备案条由 AdminView 自己在内容底部渲染。**后台路由（/admin）分支**：`main` 在 admin 路由下移除 `max-w-7xl` 限宽与内边距（后台由 AdminView 的 SidebarProvider 全高布局撑满视口；这个分支不能省——否则整个后台被前台居中盒框住，固定定位的侧边栏会与其占位 div 错位）。

亮/暗主题：`frontend/src/stores/theme.js` 维护主题状态（`localStorage['cloud-print-theme']` 优先，未选择过则跟随 `prefers-color-scheme` 并实时监听系统变化），通过**切换 `<html>` 上的 `.dark` 类**生效（shadcn-vue CSS 变量主题方案）。变量层在 `frontend/src/assets/index.css`（`:root` 亮色块 + `.dark` 暗色块，shadcn 全套 token + 品牌 `--primary`/`--chart-1..5`/语义 `--success`/`--warning`/`--brand-*`）；页面与组件一律用 Tailwind 工具类（`bg-card`、`text-muted-foreground` 等，编译后指向 CSS 变量），**禁止写死色值**。`frontend/index.html` 的 `<head>` 内联脚本在样式生效前切换 `.dark` 类防首屏闪烁；`html.theme-ready` 后才开启 0.25s 颜色过渡（尊重 `prefers-reduced-motion`）。详见 `doc/UI_ADAPTATION.md` 第 5.5 节。

路由在 `frontend/src/router/index.js`：

- `/`：`HomeView.vue`，上传、文件列表、促销展示、PDF 弹窗预览（点眼睛图标以 `Dialog` 弹窗居中展示，不再在页面底部展开）、联系人、打印设置、计价和下单。
- `/login`：`AuthView.vue`，登录和注册合并在同一页面，验证码用 Blob URL 渲染。
- `/payment/:orderId`：`PaymentView.vue`，查询并展示订单状态。
- `/user/dashboard`：`DashboardView.vue`，余额、资料绑定、充值、最近订单。
- `/admin`：`AdminView.vue`，后台所有功能集中在一个视图，通过 tab 切换；路由守卫要求管理员。

`frontend/src/api/client.js`：

- `VITE_API_BASE` 可指定后端地址。为空时使用同源请求。
- 自动从 `localStorage.cloud-print-token` 读取 token 并注入 `Authorization: Bearer ...`。
- 非 GET/HEAD/OPTIONS/TRACE 请求会先确保 CSRF cookie，再附带 `X-CSRF-Token`。
- FormData 不设置 JSON Content-Type，其它请求自动 JSON stringify。

`frontend/src/stores/auth.js`：

- 管理当前用户、登录、注册、加载 `/api/auth/me`、更新资料和退出。
- token 存在 localStorage；后端还设置 session cookie，但没有刷新 token 机制。

`HomeView.vue` 的关键行为：

- 多文件逐个上传。
- 只把 `safe` 文件纳入计价和下单。
- 拉取 `/api/promotions` 展示阶梯折扣和限时特价。
- 拉取 `/api/limits` 显示生效的单文件大小与页数上限（取不到时回退为「以系统设置为准」）。
- 拉取 `/api/print-options`（`onMounted` 的 `loadPrintOptions()`，同时加入价格试算 watch 依赖）：只有 `printer_configured` 且 `is_support_color` 为 true 才展示「彩色打印」卡片（黑白/彩色分段选择器，默认黑白）；只有 `printer_configured` 且 `is_support_auto_duplex` 为 true 才展示「合并双面打印」勾选卡片。不支持时对应 UI 完全隐藏。
- 首屏 GET（`/api/promotions`、`/api/limits`、`/api/print-options`）经 `fetchWithRetry()` 做最多 2 次重试（间隔 800ms），上传文件时若 `printOptions`/`uploadLimits` 仍缺失会兜底补拉一次——避免页面打开瞬间恰逢后端重启导致这些请求失败后，双面/彩色选项与上传限制提示整个会话静默消失。失败时前端**不显示任何提示文字**（按产品约定保持界面极简，选项直接隐藏）。
- 「合并双面打印」是侧栏一个极简 `Checkbox` 卡片，只显示「合并双面」文字与勾选框（**不显示任何说明文字或提示**）：勾选后把 `print_settings.merge_duplex` 置 true，全部安全文档按上传顺序合并为一个双面打印流，不同文档的页面连续排到纸张正反面（两份单页文档可打在同一张纸正反面）。合计页数 < 2 时勾选框禁用；文件变化导致不可用时自动取消勾选。价格试算把 `merge_duplex` 传给 `POST /api/price`，预估金额实时反映合并双面的张数与双面价。
- 提交 `POST /api/payment/create` 时，仅在打印机支持对应能力时才在 `print_settings` 中携带 `use_color`（用户是否选彩色）与 `merge_duplex`（用户是否勾选合并双面），不支持时保持与旧版一致的请求结构。
- 余额支付按钮只对登录用户可用。
- 非余额支付创建订单后，跳到后端返回的 `/api/payment/submit/{order_id}`。
- 余额支付创建成功后进入 `/payment/{order_id}` 查看状态。

`DashboardView.vue` 的关键行为：

- 用户可维护真实姓名和 11 位手机号；首页下单可自动使用这些联系人信息。
- 支持支付宝/微信充值，成功创建充值单后跳转到后端支付提交页。
- 从 `recharge_order` query 返回时会刷新用户信息和订单列表。

`AdminView.vue` 是目前最大的前端文件，集中实现后台所有 tab。修改后台时优先复用现有 `runAction()`、`loadTab()`、`showFeedback()` 模式，避免引入不一致的状态管理方式。**桌面端导航**：admin 路由**不渲染全局 AppHeader**（App.vue `v-if="!isAdminRoute"`），由 AdminView 自己的顶栏承担——`h-14` 与侧边栏宽度成比例，左侧 `SidebarTrigger` + 当前 tab 标题（`text-sm font-medium`），右侧 `ThemeToggle` + 退出按钮，避免双顶栏叠加导致固定定位侧边栏与顶栏交叠。侧边栏：shadcn-vue `SidebarProvider/Sidebar`（`collapsible="icon"`，md+ 显示，宽度经 `ui/sidebar/utils.ts` 的 `SIDEBAR_WIDTH = 15rem`（w-60）），`SidebarMenuButton` 统一 `class="h-10 font-medium"`（覆盖默认 h-8），`:is-active` 高亮（`--sidebar-accent` 底 + 主色文字），图标统一 `[&_svg]:size-4` 与文字 gap-2 严格左对齐。内容区**通栏紧凑布局**：无 max-width，卡片间距 `gap-3.5`、内边距 `py-3.5 sm:py-4`，指标卡 `lg:grid-cols-6` 一行排满。**手机端导航**（< md）：后台自己的底部 Tab 栏（5 列）——前 4 格是常用 tab（`MOBILE_PRIMARY_TAB_KEYS = ['dashboard', 'orders', 'users', 'settings']`，来自 `primaryTabs` computed，图标 + 文案），第 5 格是「更多」按钮，其余 5 个 tab（`moreTabs` computed：站点设置/支付/兑换码/备份/打印机）收进 shadcn `Sheet side="bottom"` 底部抽屉（`v-model:open="moreOpen"`，抽屉底部有「返回前台首页」链接，因为手机端顶栏导航文字入口被隐藏）。当前处在「更多」里的 tab 时，第 5 格会显示该 tab 的图标与名称并高亮（`moreCurrent`/`moreActive`）。两端共用同一个 `tab` ref 与文件末尾的 `watch(tab, loadTab)`，底部栏点击走 `selectTab(key)`（只做 `tab.value = key; moreOpen.value = false`），**行为与点桌面侧边栏完全一致，不涉及路由跳转**。`App.vue` 的 `MobileTabbar` 内部用 `route.path.startsWith('/admin')` 自行判断在后台路由不渲染，前台与后台两条底部栏互斥、不会叠加；后台 `SidebarInset` 的内容底部 padding 由壳层 `<main>` 的 `pb-[calc(84px+env(safe-area-inset-bottom))]` 覆盖。弹窗体系：**订单详情用 `Dialog`（`max-h-[85dvh] overflow-y-auto`，字段紧凑栅格 + 文件列表在弹窗内；PDF 预览默认不加载——打开弹窗只展示文件列表，点文件行的「预览」按钮才加载 iframe（按钮变为「收起预览」，再点即卸载 iframe），`loadOrderDetail()`/`closeOrderDetail()`/缓存清理后的详情刷新都会把 `selectedOrderFile` 置空，保证每次打开弹窗都是未预览状态）**，编辑打印机、手动新增/批量生成兑换码用 shadcn `Dialog`，兑换码详情用 `Sheet side="right"`；**删除订单/删除未支付/批量删除未支付的二次确认统一用 `AlertDialog`**（`pendingConfirm` 状态 + `requestConfirm()`，删除请求逻辑不变；备份/兑换码等旧入口仍用 `window.confirm`）。状态反馈：顶部 `Alert`（success/warning 语义类走 `--success`/`--warning` 变量）+ 复制兑换码等瞬时提示走 `toast`（vue-sonner）。

「站点设置」tab（2026-10 新增，key=`site`）：shadcn `Tabs` 分四组——「登录锁定」（连续失败 N 次锁定 + 锁定分钟数，保存即作用于登录接口）、「网页标题」（留空恢复默认「PrintHub 云打印」）、「网站图标」（上传 .ico/.png 或外链 URL 或不设置，三态 `site_favicon_mode`）、「备案号」（留空全站不显示备案条）。数据经 `GET/PUT /api/admin/site-settings` 与 `POST /api/admin/site-settings/favicon` 读写（`siteSettingsForm` + `applySiteSettingsData()` 回显），每组一个保存按钮只提交该组字段；保存/上传成功后除回显外还会调用 `stores/site.js` 的 `site.apply()` 把标题/favicon/备案号**立即应用到全站**（不刷新页面）。网站图标上传框是隐藏 file input（`siteFaviconInput`）+「选择图标文件上传」按钮，前端先做扩展名/200KB 预检，后端再按文件头校验。内容底部渲染 `<IcpFooter />`（后台路由的备案条；前台路由的备案条由 App.vue 在 main 内渲染）。

概览 tab 的 6 个统计卡片下方是「每日数据统计」卡片（`frontend/src/components/DailyStatsCard.vue`，由 `AdminView.vue` 概览 tab 直接 `<DailyStatsCard />` 引入；切回概览会重新挂载并重新拉取数据）。它自带时间范围切换（近 7 天/近 30 天，走 `GET /api/admin/daily-stats?days=`，shadcn Tabs）与三个维度 Tab（订单趋势/收入趋势/打印失败分布，纯前端切换、不重新请求）——两组 Tab **统一规格 `h-9` + `text-sm`**（时间组 px-4、维度组 px-3.5 带图标），选中态为 muted 轨道上的卡片色胶囊（全站 Tabs 统一样式）；维度 TabsList 窄屏可横向滑动、可点击切换显示/隐藏的图例（按「Tab+系列」记忆在 `hiddenSeries`）、Unovis crosshair + 官方 `ChartTooltipContent` 提示框、加载 Skeleton/Spinner 与 shadcn `Empty` 空状态。图表用 **shadcn-vue 官方 Chart 组件（`components/ui/chart/`，底层 unovis）**：柱状走左轴 `--chart-1`、折线走右轴 `--chart-2`（`VisStackedBar` + `VisLine` + 双 `VisAxis`，各自 `yDomain` 由保留的 `axisMax()`/`niceMax()` nice-number 逻辑算出），颜色全部是 CSS 变量、亮暗自动跟随；x 轴刻度用 `numTicks` 均匀抽稀并从数据取标签。宽度自适应由 Unovis/ChartContainer 处理，不再需要手写 ResizeObserver。

打印机 tab 的卡片上展示能力标签（`支持彩色打印`/`仅黑白打印`、`支持自动双面`/`仅单面打印`，Badge + CSS 变量色点）与「编辑打印机」按钮；编辑用 shadcn `Dialog`，弹窗内「打印机能力」区块用两个 `Switch`（分别绑定 `is_support_color`、`is_support_auto_duplex`），保存时随 `PATCH /api/admin/printers/{name}` 一起提交。首页「彩色打印」卡片保持极简：只有标题和 `黑白 / 彩色` Tabs 分段切换（沿用通用 TabsList 样式，不额外加装饰圆点、状态徽标和说明文字）。

兑换码 tab 的列表在桌面端（md+）是 shadcn `Table` 5 列（兑换码 / 兑换面额 / 有效期 / 使用状态 / 操作），手机端（< md）折叠为纵向卡片列表（两套都由同一份 `redemptions` 数据渲染）。其中「有效期」列由 `redemptionExpiryText(code)` 渲染——`expiry_mode === 'date'` 显示「截止 YYYY-MM-DD HH:mm:ss」（即该日 23:59:59），否则按 `valid_days > 0` 显示「N 天」或「永久有效」。生成时间、单用户上限、兑换用户等次要信息不在表格里，点行内「详情」按钮打开右侧 shadcn `Sheet` 抽屉（由 `selectedRedemptionDetail` 控制显隐）：`openRedemptionDetail(code)` 先展示列表项已有的完整信息（完整兑换码、面额、已兑换次数 `used_count / usable_count`、生成时间、有效期类型 `expiry_mode`、有效天数、精确到期、单用户使用上限、使用状态、累计可兑金额 `total_amount`），同时请求 `GET /api/admin/redemptions/{id}/logs` 拉取「已兑换用户」列表（`redemptionDetailLoading` 控制加载态，`redemptionLogs` 复用原记录弹窗的数据）。「有效期」一行在手动新增与批量生成两个 `Dialog` 弹窗里都是：`Tabs`（「按天数」/「指定到期日期」，`v-model` 绑定 `expiry_mode`）+ 当前模式的输入控件（数字输入框或 `<input type="date">`，`v-if/v-else` 二选一渲染，**不会同时出现两个输入框**），提示行由 `redemptionExpiryHint` / `batchRedemptionExpiryHint`（computed，内部走 `redemptionExpiryHintOf(form)`）给出文案；详情抽屉「有效天数」值由 `redemptionDetailValidDays(code)` 渲染，日期模式显示「—（按到期日期）」。「单用户使用限制」是弹窗内一个带边框分组卡片：左侧 `Switch`（绑定 `per_user_limit_enabled`）+ 右侧「最大使用次数」数字输入框（开关关闭时 disabled），底部一行短提示由 `perUserMaxTimesHint` 给出——开启时显示实际填写值、关闭时显示占位 `N`。绑定仍是 `redemptionForm.per_user_limit_enabled` / `per_user_max_times`，提交时关闭则发 0，业务逻辑未变。删除按钮仍在行内直接调用 `deleteRedemption(code)`。

## 9. 本地运行和测试

不再需要 `.env`。默认配置目录是「启动时的当前工作目录」；首次运行会在该目录自动生成 `config.json` 以及 `cloud_print.db`、`uploads/`、`backups/`、`logs/`、`cups-drivers/`。可用 `CONFIG_ROOT` 指定配置目录、用 `CONFIG_CONFIG_FILE` 指定其它配置文件路径。

本地后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py            # 首次启动自动生成 backend/config.json
```

本地前端：

```bash
cd frontend
pnpm install
pnpm run dev
```

配置文件测试（不依赖 pycups/CUPS/网络，Windows 本地也能跑）：

```bash
cd backend
python tests/config_test.py
```

兑换码专项回归测试（不依赖 pycups/CUPS/网络/前端，Windows 本地也能跑，覆盖 `per_user_max_times` 双重校验（每用户上限 + 全局总次数）、错误码、余额与 used_count 不变、旧库缺列兼容与 `per_user_once`→1 迁移；另含有效期二选一用例 `test_expire_date_mode()` / `test_expire_date_schema()`：`normalize_expire_date()` 对 `YYYY-MM-DD`、`date` 对象、带时间 ISO 串的归一化（一律到当天 23:59:59）与非法值返回 `None`、日期模式入库后 `expires_at` 正确且 `valid_days=0`、`expiry_mode_of()` 返回 `"date"`、过期日期码兑换抛 `REDEMPTION_CODE_EXPIRED` 且余额不变、批量生成统一到期时间、`expiry_mode` 随列表返回，以及 `AdminRedemptionCreate`/`AdminRedemptionBatchCreate` 对 `expiry_mode`/`expire_date` 的归一与非法日期拒绝）：

```bash
cd backend
python tests/redemption_per_user_test.py
```

「每日数据统计」本地时区聚合专项测试（不依赖 pycups/CUPS/FastAPI/前端，Windows 本地也能跑，覆盖空库日期序列、**本地时区边界**（东八区下若退化成按 UTC 日期分日必然失败）、两种时间戳格式归日、失败率、7/30 天窗口边界、`days` 归一化、`timezone_label()` 格式与边界时刻往返）：

```bash
cd backend
python tests/daily_stats_test.py
```

后端冒烟测试（用临时配置目录，避免污染真实配置）：

```bash
cd backend
CONFIG_ROOT=/tmp/cloud_print_test .venv/bin/python tests/smoke_test.py
```

冒烟测试 import `app.main` 时会加载打印服务，需要 `pycups` 和可用的 CUPS 环境，因此更适合在容器内跑；它会用临时配置目录/数据库/上传目录和测试易支付参数，并对 `print_pdf` 打桩，订单派发链路无需真实打印机。

证照打印专项回归测试（不依赖 pycups/CUPS/OpenCV/FastAPI 应用，Windows 本地可跑，覆盖 schema 播种幂等与后台数据保留、mm→px 换算与槽位定位（合成位图采样）、手动四点透视、PDF 组装页尺寸、计价钩子三分支（独立价/回退 standard/拒绝 coverage）、每日上限、无 OpenCV 降级下的生成端到端（files/cert_docs 入库 + coverage 为 NULL）、清理任务（跳过 pending/paid 订单、历史订单引用置 expired）、属主校验）：

```bash
cd backend
python tests/cert_feature_test.py
```

两页合一专项回归测试（不依赖 pycups/CUPS/poppler/FastAPI 应用——光栅化函数注入假实现，Windows 本地可跑，覆盖竖向/横向版式与旋转方向角点校验、裁切线、奇数页配对、覆盖率计算、合成服务端到端（files 行字段/输出 PDF 尺寸/命名/属主）、归属与安全校验）：

```bash
cd backend
python tests/doc2up_feature_test.py
```

前端构建：

```bash
pnpm --prefix frontend run build
```

Docker Compose 构建与部署（仓库里没有 `install.sh`/`configure.sh`/`start.sh`/`uninstall.sh`）：

```bash
# 在 docker-compose.yml 所在目录执行，避免挂载到另一个空的 ./config 目录
docker compose up -d --build

# 首次启动后查看生成的配置文件（含随机 app_secret、管理员账号、部署级键）
cat config/config.json

# 查看状态与日志
docker compose ps
docker compose logs -f cloud-print
```

配置改法：编辑 `./config/config.json` 后 `docker compose restart`，或直接在后台页面改业务设置（价格、促销、上传限制、支付、CUPS、默认打印机）。数据库里的业务设置优先于 `config.json`；`cups_*`/`epay_*` 只在首次建库时从 `config.json` 播种进数据库，之后再改配置文件不会覆盖后台已保存的值。备份 = 停止容器后复制整个 `./config` 目录（后台的备份/恢复功能也会把 `config.json` 一起打包）。

容器内 `docker/entrypoint.sh` 会先把 `CONFIG_ROOT` 默认设为 `/app/config`、建好各数据目录并 `chown app:app`，再以 `app` 用户执行 `python3 -m app.bootstrap` 生成配置文件，最后 `exec` 启动 uvicorn。

## 10. 修改注意事项

- 不要把 `AGENTS.md` 当 PRD 维护；PRD 放在 `doc/PRD.md`。本文件应反映代码真实行为。
- 不要随意删除或重命名上传目录中的文件。后台缓存清理和订单删除有专门逻辑，并做了上传根目录校验。
- 修改数据库 schema 时，在 `SCHEMA` 和 `SCHEMA_MIGRATIONS` 中同时考虑新库和旧库；新增设置键要同步 `DEFAULT_SETTINGS`、后台表单、读写逻辑和测试。
- 修改认证时要同时考虑验证码、session cookie、bearer token、登录失败锁定和前端 `auth` store。**Bearer token 依赖 `users.token_version` 做服务端吊销**（登录签发 `ver`、`current_user()` 比对、logout/改密/封禁时 +1，见第 5 节）；新增「使某用户 token 失效」的场景时记得 bump 版本号，而不是只删 session。登录失败提示的剩余次数/锁定分钟数是**结构化 detail**（前端只展示后端给的信息），改 `record_login_failure()`/`login_failure()` 的返回结构时要同步 `AuthView.vue` 的样式分级逻辑（`remaining_attempts === 1` 或 `locked` 时红色警示）与 `backend/tests/smoke_test.py` 的断言。
- 修改站点设置（标题/favicon/备案号/登录锁定策略）时：键值都存 `settings` 表（`services/site_settings.py` 是唯一读写入口，`login_lock_*` 缺键回退 config.json）；`login_lock_threshold`/`login_lock_minutes` 必须同时在 `database.py` 的 `init_db()` 播种（INSERT OR IGNORE，从 config.json 取值）——新部署才有初始值，但绝不能覆盖后台已保存的值；favicon 以 data URI 入库（勿改成落盘 uploads/，会被缓存清理；也不落 config 目录散文件，备份服务不打包任意子目录），`PUT` 不允许直接写 `upload` 模式；前端全局应用统一走 `stores/site.js` 的 `site.apply()`（AdminView 保存后与 App.vue 启动时都调它），备案条组件是 `components/layout/IcpFooter.vue`（前台 App.vue + 后台 AdminView 各渲染一处）。
- 安全修复（2026-10 渗透测试回归）引入的不变量，改相关代码时不要破坏：① 订单详情对匿名/非属主只返回 `ANONYMOUS_ORDER_FIELDS` 摘要（`routers/orders.py`）；② 文件归属校验集中在 `ensure_file_readable()`（files.py）与 `ensure_files_accessible()`（orders.py，public.py 复用），guest 文件（user_id NULL）保持公开以支撑访客流程；③ `/api/setup/restore/status` 已初始化时必须 401；④ 姓名/联系人字段走 `NAME_PATTERN` 白名单（`models/schemas.py`）；⑤ `/docs`/`/redoc`/`/openapi.json` 仅 development 环境开启（`main.py`）。
- 修改支付时，要同步 `epay.py`、`orders.py`、`user.py`、后台支付配置、支付自测和 `backend/tests/smoke_test.py`。
- 修改余额充值时，必须保留 `balance_applied_at` 防重复入账。
- 修改兑换码时，要保持 `AdminRedemptionCreate.code` 可缺省（留空、空串、纯空白或不传都自动生成随机码），用户侧 `RedeemRequest.code` 仍必填；同步 `backend/app/services/redemption.py`、后台兑换码弹窗和个人中心兑换入口。兑换入账的「占用可用次数 + 加余额 + 写 `redemption_logs`」必须在同一事务（`BEGIN IMMEDIATE` + 条件 UPDATE + 失败回滚）内完成；错误要返回带 `{code, message}` 的标准 JSON，不要抛原始异常。**服务函数必须用别名引入**（`from ..services.redemption import redeem as redeem_redemption_code`）：在 `backend/app/routers/user.py` 里若让服务函数与路由函数同名，路由会调用自己并抛 `AttributeError`（前端只显示纯文本 500）。
- 修改计价时，要同步前台 `/api/price`、`/api/promotions`、后台配置表单、订单保存字段和烟测断言。
- 修改兑换码的「限制每个用户最大兑换次数」（`per_user_max_times`）时：该列须在 `SCHEMA` 与 `SCHEMA_MIGRATIONS["redemption_codes"]` 同时存在，且默认值 0（0=不限制，保持原「按总可用次数」逻辑）；`create_code()` 的第 6 个位置参数要在 `backend/app/routers/admin.py` 里透传 `payload.per_user_max_times`（漏传会让这个限制静默失效）。`redeem()` 里**两种模式共用同一条条件 UPDATE**（`WHERE id = ? AND used_count < usable_count`）来占用全局次数；「每个用户最大兑换次数」只是在 `BEGIN IMMEDIATE` 写锁内额外多做一道 `count_user_redemptions() >= per_user_max_times` 判定，**不要**给 `per_user_max_times>0` 的码改成无条件累加 `used_count`（那正是旧版「每用户一次就忽略总次数」的错误语义，会让 `usable_count=1` 时第二个用户也被放行）。旧库的 `per_user_once=1` 由 `migrate_redemption_per_user_limit()` 一次性换算成 `per_user_max_times=1`，代码不再读写旧列。后台兑换码列表已精简为 5 列（兑换码 / 兑换面额 / 有效期 / 使用状态 / 操作），`per_user_max_times`、已兑换次数、生成时间、兑换用户等次要信息不在表格里，全部移入右侧「兑换码详情」Sheet 抽屉中展示，弹窗「手动新增兑换码」是 shadcn `Dialog` + `Switch`/`Input`/`Tabs` 组合（无自定义 CSS，外观来自 `components/ui/*` 官方组件 + Tailwind 工具类）：分组卡片「单用户使用限制」内是 `Switch`（绑定 `redemptionForm.per_user_limit_enabled`）与「最大使用次数」数字输入框（开关关闭时 disabled），底部短提示的 N 由纯展示计算属性 `perUserMaxTimesHint` 给出——开启时显示实际填写值、关闭时显示占位 `N`。绑定仍是 `redemptionForm.per_user_limit_enabled` / `per_user_max_times`，提交时关闭则发 0，业务逻辑未变。桌面表格用 shadcn `Table`（`max-md:hidden`），手机端折叠为卡片列表（`md:hidden`），列数/列宽改动直接改模板里的 Tailwind 类。专项回归测试：`python tests/redemption_per_user_test.py`（Windows 本地可跑，不需 pycups/CUPS）。
- 修改兑换码有效期方式（`expiry_mode` = `days`/`date` 二选一）时：**刻意不加数据库列**，语义完全由 `(valid_days, expires_at)` 组合表达——`expires_at` 非空且 `valid_days=0` 视为 `date`，否则 `days`，读取一律走 `expiry_mode_of(code_row)`，不要新增 `expiry_mode` 列，也不要改动 `code_status()` 的判断顺序（**过期判断必须始终优先于次数判断**）。日期归一化集中在 `backend/app/services/redemption.py` 的 `normalize_expire_date()`（接受 `YYYY-MM-DD`、`date`/`datetime`、带时间 ISO 串，一律落到**当天 23:59:59** 的 `isoformat(timespec="seconds")`；非法值返回 `None`）；服务层遇非法日期回退「按天数」，写接口由 `AdminRedemptionCreate.normalize_redemption_payload` 与 `AdminRedemptionBatchCreate.normalize_expiry` 拦住（报 `请选择有效的到期日期（格式 YYYY-MM-DD）`），并把非 `date` 模式的 `expire_date` 清空、`date` 模式的 `valid_days` 强制归零，避免两种方式同时生效。`create_code()` 新增第 7 个（关键字）参数 `expires_at`、`batch_generate_codes()` 新增第 6 个，`backend/app/routers/admin.py` 必须透传 `expires_at=payload.expire_date`（**漏传会让「指定到期日期」静默退化成永久有效**）。前端手动新增与批量生成两个弹窗的有效期行都是 shadcn `Tabs`（「按天数」/「指定到期日期」，`v-model` 绑定 `expiry_mode`）+ 当前模式输入控件（`v-if/v-else` 二选一渲染，不会同时出现两个输入框），外观全部来自官方组件与 Tailwind 工具类。专项用例：`python tests/redemption_per_user_test.py` 里的 `test_expire_date_mode()` / `test_expire_date_schema()`。
- 修改打印时，注意打印方式完全按运行平台分流（Windows 走系统队列/SumatraPDF，Linux/macOS 走 CUPS 命令），已没有 `print_mode` 配置项，mock 模拟模式也已移除。自动支付回调可能触发真实打印。
- 修改打印派发（`services/print_dispatch.py`）时：保持「请求线程只调度、后台线程派发」的异步语义，不要把 `dispatch_order_print()` 挪回 HTTP 请求内同步执行（大文档光栅化会把支付/回调请求拖到几十秒）；`_inflight_orders` 去重、`_wait_for_paid()` 等待窗口与「已派发订单直接退出」的防重逻辑必须保留；`ASYNC_DISPATCH = False` 仅给冒烟测试等确定性场景用，别在运行时改它；新调用方一律通过 `dispatch_print_files_if_present()` 接入（它会自动跳过无打印文件的非打印单）。按需光栅化由 `files.needs_rasterize`（上传时打标，见 6.1 第 7 步）与 `print_pdf(rasterize=...)` 三态参数配套，改动任意一侧都要保持「缺标记按 1（一律光栅化）」的兜底，宁慢勿丢图。
- 修改彩色打印 / 自动双面能力时，要同步 `database.py` 的 `SCHEMA` 与 `SCHEMA_MIGRATIONS`（`printers.is_support_color`/`is_support_auto_duplex`、`orders.use_color`、`orders.merge_duplex`）、`cups_printer.py` 的 `_save_metadata()` 与打印机输出对象、公开接口 `/api/print-options`、`orders.py` 的能力兜底校验、`print_pdf(use_color=...)` 与 `rasterize_pdf_for_print(darken=...)`、合并双面的 `pdf_postprocess.merge_pdfs()`，以及首页条件渲染和后台编辑弹窗。
- 修改上传或转换时，要保留文件头校验、大小限制、页数限制、覆盖率检测和失败文件入库。
- 修改后台概览的「每日数据统计」时：分日口径集中在 `backend/app/services/stats.py`。库里时间戳**统一是 UTC 文本**（`orders.created_at` 由 SQLite `CURRENT_TIMESTAMP` 生成 `YYYY-MM-DD HH:MM:SS`，而 `paid_at`/`printed_at` 由 `datetime.utcnow().isoformat()` 生成 `YYYY-MM-DDTHH:MM:SS.ffffff`，**同一张表两种格式并存**），所以 SQL 里先用 `datetime(created_at)` 归一化、按 `strftime('%Y-%m-%d %H', ...)` 聚成 UTC 小时桶，再由 Python 用无参 `astimezone()` 折算本地日期——**不要**直接对字符串做 `substr(created_at, 1, 10)` 分日（那是 UTC 日期，东八区下会把本地 0-8 点的订单算到前一天）。窗口边界用「本地日 00:00 → UTC 半开区间」反算，不要在 SQL 里写死时区偏移。接口是 `GET /api/admin/daily-stats`（`days` 1-90、默认 7），路由函数名与 `stats.py` 的 `daily_stats` 同名，所以**必须用别名引入**（`from ..services.stats import daily_stats as build_daily_stats`），否则路由会调用自己。前端图表在 `frontend/src/components/DailyStatsCard.vue`，基于 shadcn-vue Chart（unovis）；颜色一律走 `var(--chart-1)`/`var(--chart-2)` 等 CSS 变量，不要为了「图表好看」写死 hex。专项回归测试：`python tests/daily_stats_test.py`（Windows 本地可跑，不需 pycups/CUPS）。
- 修改前端 API 路径时，注意生产环境前端由后端直接托管，不需要 Nginx 反代。
- 修改主题（亮/暗）时：颜色必须走 `frontend/src/assets/index.css` 定义的 CSS 变量（shadcn token：`--background`/`--card`/`--primary`/`--muted-foreground`/...，以及扩展的 `--success`/`--warning`/`--chart-1..5`/`--brand-*`），页面里用 Tailwind 工具类（`bg-card`、`text-primary` 等）引用，**禁止写死 hex/rgba**；亮色改 `:root` 块、暗色改 `.dark` 块，两块变量集合必须保持一致（PC 与移动端共用同一套亮/暗变量，不再区分设备配色）。主题切换是 `<html class="dark">`（`stores/theme.js` 的 `applyTheme()` 与 `index.html` 内联脚本共用同一规则；localStorage 键仍为 `cloud-print-theme`）。移动端断点统一用 Tailwind 的 `md`（768px）。字体改动只动 `assets/index.css` 顶部的 `@font-face` 与 `@theme` 里的 `--font-sans`/`--font-display` 栈（`assets/fonts/space-grotesk-latin.woff2` 由 Vite 打包，不要删除；它只覆盖拉丁字符与数字，中文自动回退系统字体）。规范见 `doc/UI_ADAPTATION.md` 第 5.5 节。
- `frontend/dist/`、`frontend/node_modules/`、`release/` 和同步冲突副本正常编码不要手动编辑；Docker 构建会在镜像内重新生成前端产物。
- 仓库可能出现 NAS 同步冲突副本。除非明确处理同步冲突，否则不要修改这些副本文件。
- 修改证照打印时（详见 6.9）：遵守隔离铁律——新增文件只进 `backend/app/cert/` 与 `frontend/src/cert/`（唯一例外 `backend/tests/cert_feature_test.py`），主程序改动不得超出 6.9 列出的钩子清单；`cert/schema.py` 与 `services/pricing.py`、`database.py` 互相都用**函数内延迟导入**（顶层互相 import 会成环）；清理任务删 `files` 行前必须检查 `order_items` 引用（FK 强制），被引用时置 `status='expired'` 而不是删行；证照件的 `black_coverage/page_coverages` 必须保持 NULL，计价钩子保证其不落入 `coverage_tiered`；不装 OpenCV 时全流程仍须可用（手动四点裁剪兜底，`detect.py` 的 import 守卫不能删）；改动后跑 `python tests/cert_feature_test.py`。

## 11. 当前实现与原 PRD 的差异

- 独立文档预览页目前未实现；预览以弹窗形式嵌在首页（shadcn `Dialog`）和后台订单详情弹窗内。
- 登录和注册不是两个路由，而是在 `/login` 的同一个视图中切换，并都要求验证码。
- 用户自助充值已经实现，但不是独立充值页面，而是个人中心里的充值模块。
- 后台配置、订单、用户、支付、打印机都集中在 `/admin` 单页 tab 中。
- 当前 Office 转 PDF 依赖系统 LibreOffice，不使用 `python-docx` 或 `python-pptx` 做转换。
- 当前 token 是项目自定义 HMAC token，不是 JWT 库；同时存在 session cookie 作为后备鉴权。
- 当前支付返回的是后端自动提交表单 URL，不是直接二维码图片 URL。
- 后台概览的「每日数据统计」图表已迁移到 **shadcn-vue 官方 Chart 组件**（`frontend/src/components/ui/chart/`，底层 unovis，`@unovis/vue` + `@unovis/ts`；图表颜色跟随 `--chart-1..5` CSS 变量）。此前是手写内联 SVG、零图表依赖；引入依赖的同时已更新 `pnpm-lock.yaml`，Docker 构建仍走 `pnpm install --frozen-lockfile`。
- 当前打印完成状态依赖 CUPS 队列确认；Windows 下无法可靠自动确认完成（mock 模拟模式已移除）。
- 打印派发是后台线程异步执行的（原方案在支付/回调请求内同步派发，大文档会把请求拖到几十秒）：支付接口先返回、订单停在 `paid`，后台线程完成光栅化与 `lp` 提交后转 `printing`/`print_failed`；排队口径把 `paid` 与 `printing` 都算排队中，前端轮询逻辑不变。
- 当前部署方式是 Docker Compose 单容器：FastAPI 直接托管前端静态文件，没有独立 Nginx 前端容器；SQLite、上传缓存、备份、日志和 `config.json` 都在 `./config` 绑定挂载目录里。
- 彩色打印与合并双面打印只在 Linux/macOS 的 CUPS 链路真正生效（`lp -o print-color-mode=color|monochrome`、`lp -o sides=two-sided-long-edge`）；Windows 的 SumatraPDF/`PrintTo` 分支只处理打印机与份数，`double_sided`、`merge_duplex` 与 `use_color` 都不生效（与改动前一致）。合并双面是把全部文档合并成一个双面打印流（跨文档正反面连打），不是整单多份独立双面。

## 12. 快速理解代码链路

访客或注册用户打印链路：

```text
HomeView.vue
  -> GET /api/promotions
  -> GET /api/print-options           # 默认打印机的彩色/自动双面能力，决定首页是否展示对应选项
  -> POST /api/upload
    -> save_upload()
    -> convert_to_pdf()               # LibreOffice 三级降级导出 + flatten_pdf_smask()
    -> page_count()
    -> calculate_black_coverage_details()
    -> needs_rasterize 打标 + audit_converted_fonts() 字体自检
    -> files 表 + alerts 表
  -> POST /api/price
  -> POST /api/payment/create
    -> calculate_files_price_detail()
    -> orders/order_items/payments 表
  -> GET /api/payment/submit/{order_id}
    -> 易支付网关
  -> GET|POST /api/payment/notify
    -> complete_epay_payment(dispatch_callback=dispatch_print_files_if_present)
    -> schedule_order_dispatch()      # 请求立即返回，订单停在 paid
      -> 后台线程 dispatch_order_print()
        -> print_pdf()                # 按 needs_rasterize 决定是否先光栅化
      -> 订单置 printing / print_failed
    -> print_monitor 后台确认 completed 或 print_failed
```

注册用户余额支付链路：

```text
AuthView.vue 登录
  -> token 写入 localStorage，session 写入 cookie
DashboardView.vue 绑定姓名和手机号
HomeView.vue 选择 balance
  -> POST /api/payment/create
    -> 校验余额和最低余额
    -> 扣减 users.balance
    -> 订单置为 paid
    -> dispatch_print_files_if_present()  # 异步调度，请求立即返回；后台线程 dispatch_order_print()
PaymentView.vue
  -> GET /api/orders/{order_id}
```

余额充值链路：

```text
DashboardView.vue
  -> POST /api/user/recharge
    -> order_type = recharge
    -> payments 表 pending
  -> GET /api/payment/submit/{order_id}
  -> GET|POST /api/payment/notify
    -> complete_epay_payment()
    -> apply_recharge_balance()
    -> users.balance 增加，orders.balance_applied_at 写入
```

兑换码充值链路：

```text
AdminView.vue 兑换码 tab
  -> POST /api/admin/redemptions            # code 留空时后端生成随机码（_random_unique_code），可传 per_user_max_times 设置每用户最大兑换次数（0=不限制）
  -> POST /api/admin/redemptions/batch      # 批量随机生成（per_user_max_times 默认 0）
DashboardView.vue 兑换码充值
  -> POST /api/user/redeem
    -> redeem() 校验存在/过期/该用户历史兑换次数是否已达 per_user_max_times（仅 >0 的码）/剩余总次数（错误返回 400 {code, message} 中文提示）
    -> BEGIN IMMEDIATE 事务：写锁内先复查每用户上限（count_user_redemptions()），再走统一条件 UPDATE（used_count < usable_count）占用全局次数；随后 users.balance 增加 + redemption_logs 写入（失败整体回滚）
```

管理员处理异常链路：

```text
文件覆盖率超阈值
  -> alerts 表新增 open 告警
AdminView.vue 概览 tab
  -> GET /api/admin/dashboard
  -> POST /api/admin/alerts/{alert_id}/handle
```

后台概览「每日数据统计」链路：

```text
AdminView.vue 概览 tab
  -> <DailyStatsCard />（frontend/src/components/DailyStatsCard.vue）
    -> GET /api/admin/daily-stats?days=7|30
      -> backend/app/routers/admin.py 的 daily_stats()（别名 build_daily_stats）
        -> backend/app/services/stats.py 的 daily_stats()
          -> SQL 按 UTC 小时桶聚合 orders（datetime() 归一化两种时间戳格式）-> Python 折算本地日期
```

打印机管理与测试链路：

```text
AdminView.vue 打印机 tab
  -> GET  /api/admin/printer-system        # 运行环境与 CUPS 连通性诊断
  -> GET  /api/admin/printers              # cups_printer.list_printers() 枚举真实队列（含 is_support_color / is_support_auto_duplex）
  -> PATCH|PUT /api/admin/printers/{name}  # 编辑队列，保存打印机能力（PrinterUpdate，None=不修改；无新增打印机的 POST）
  -> GET  /api/admin/printer-drivers
  -> POST /api/admin/printer-drivers/ppd   # 上传 PPD 驱动
  -> PUT  /api/admin/printers/{name}/default | /api/admin/printers/default/clear
  -> PUT  /api/admin/printers/{name}/enabled
  -> POST /api/admin/printers/{name}/test-page
  -> POST /api/admin/printers/{name}/test-result
```

## 13. 维护者快速定位索引

按常见改动类型定位代码：

- 登录、验证码、会话、权限：`backend/app/routers/auth.py`、`backend/app/services/auth_session.py`、`backend/app/routers/deps.py`、`backend/app/utils/security.py`、`frontend/src/stores/auth.js`、`frontend/src/views/AuthView.vue`（登录失败剩余次数/锁定提示的样式分级也在这里）。
- 站点设置（标题/favicon/备案号/登录锁定策略）：`backend/app/services/site_settings.py`（唯一读写入口）、`backend/app/routers/admin.py`（`/site-settings` GET/PUT/favicon 上传）、`backend/app/routers/public.py`（`/api/site-settings` 与 `/api/site/favicon`）、`backend/app/models/schemas.py`（`SiteSettingsUpdate`）、`backend/app/database.py`（`login_lock_*` 播种）、`frontend/src/stores/site.js`（全局应用）、`frontend/src/components/layout/IcpFooter.vue`（备案条）、`frontend/src/views/AdminView.vue`（「站点设置」tab）。
- 上传、转换、预览、安全检测：`backend/app/routers/files.py`、`backend/app/services/files.py`（上传校验、LibreOffice 三级降级转换、字体自检）、`backend/app/services/pdf_postprocess.py`（SMask 拍平、遮罩检测、打印光栅化、合并 PDF）、`backend/app/services/safety.py`（覆盖率统计与安全判定）、`frontend/src/views/HomeView.vue`。
- 计价、覆盖率阶梯、促销：`backend/app/services/pricing.py`、`backend/app/routers/public.py`、`backend/app/routers/admin.py`、`frontend/src/views/HomeView.vue`、`frontend/src/views/AdminView.vue`。
- 打印订单、支付、易支付回调：`backend/app/routers/orders.py`、`backend/app/services/epay.py`、`backend/app/services/print_dispatch.py`（异步派发）、`backend/app/services/printer.py`、`frontend/src/views/PaymentView.vue`。
- 用户资料、余额充值、个人中心订单：`backend/app/routers/user.py`、`backend/app/services/epay.py`、`frontend/src/views/DashboardView.vue`。
- 兑换码（后台生成 + 用户兑换，含「每个用户最大兑换次数」`per_user_max_times`）：`backend/app/services/redemption.py`（`redeem()` 双重校验 + `count_user_redemptions()`/`per_user_max_times_of()`/`has_redeemed()`）、`backend/app/routers/admin.py`（`/redemptions`，`create_code()` 必须透传第 6 个位置参数）、`backend/app/routers/user.py`（`POST /api/user/redeem`）、`backend/app/models/schemas.py`（`AdminRedemptionCreate`/`RedeemRequest`）、`backend/app/database.py`（`SCHEMA` + `SCHEMA_MIGRATIONS["redemption_codes"]["per_user_max_times"]` + `migrate_redemption_per_user_limit()`）、`frontend/src/views/AdminView.vue`、`frontend/src/views/DashboardView.vue`、`backend/tests/redemption_per_user_test.py`。
- 打印机管理和真实打印：`backend/app/services/printer.py`、`backend/app/services/print_monitor.py`、`backend/app/routers/admin.py`、`scripts/test_printer.py`。
- 彩色打印、合并双面打印能力（前台条件渲染 + 后端兜底校验 + 合并派发）：`backend/app/routers/public.py`（`GET /api/print-options`）、`backend/app/services/cups_printer.py`（`_save_metadata()` 保存两项能力）、`backend/app/routers/orders.py`（能力兜底 400）、`backend/app/services/print_dispatch.py`（`dispatch_order_print()` 的合并分支与 `rasterize` 传参）、`backend/app/services/pricing.py`（`calculate_files_price_detail(merge_duplex=...)`）、`backend/app/services/pdf_postprocess.py`（`merge_pdfs()` 合并、`rasterize_pdf_for_print(darken=...)`）、`backend/app/services/printer.py`（`use_color` → `lp -o print-color-mode=`）、`frontend/src/views/HomeView.vue`、`frontend/src/views/AdminView.vue`。
- 打印异步派发与按需光栅化：`backend/app/services/print_dispatch.py`（调度/防重/`_wait_for_paid()`/`ASYNC_DISPATCH` 开关）、`backend/app/routers/files.py`（上传时写 `needs_rasterize` 标记）、`backend/app/services/pdf_postprocess.py`（`pdf_has_image_masks()`）、`backend/app/services/printer.py`（`print_pdf(rasterize=...)` 三态）、`backend/app/database.py`（`files.needs_rasterize` 列与迁移）。
- 数据表、默认设置、旧库迁移：`backend/app/database.py`，同时检查后台设置表单和 `backend/tests/smoke_test.py`。
- 后台概览「每日数据统计」（按本地时区分日聚合 + shadcn Chart/unovis 双轴柱线图）：`backend/app/services/stats.py`、`backend/app/routers/admin.py`（`GET /api/admin/daily-stats`，别名引入 `daily_stats` 为 `build_daily_stats`）、`frontend/src/components/DailyStatsCard.vue`、`frontend/src/components/ui/chart/`（shadcn 官方图表组件）、`frontend/src/views/AdminView.vue`（概览 tab）、`backend/tests/daily_stats_test.py`。
- 亮/暗主题（`.dark` 类切换 + CSS 变量）：`frontend/src/assets/index.css`（`:root`/`.dark` 变量块、`@font-face`、`@theme` 映射）、`frontend/src/stores/theme.js`（状态/记忆/跟随系统/切类）、`frontend/src/components/layout/ThemeToggle.vue`（切换按钮）、`frontend/index.html`（favicon、meta/og/theme-color、防闪烁内联脚本）。规范见 `doc/UI_ADAPTATION.md` 第 5.5 节。
- 证照打印（隔离模块，见 6.9）：后端 `backend/app/cert/`（schema/templates_seed/service/render/detect/pricing/router/admin_router/cleanup）+ 钩子在 `main.py`/`database.py`/`services/pricing.py`/`middleware.py`；前端 `frontend/src/cert/`（CertPortal/CertAdminPanel/routes/constants/api/modules/components）+ 钩子在 `router/index.js`/`AppHeader.vue`/`MobileTabbar.vue`/`AdminView.vue`（「证件照管理」tab）/`AuthView.vue`（redirect 回跳）；专项测试 `backend/tests/cert_feature_test.py`。
- 两页合一打印（隔离模块，见 6.10）：后端 `backend/app/doc2up/`（router/service，create 受 cert_templates doc2up 登记行启停控制）+ 钩子在 `main.py`；前端 `frontend/src/doc2up/`（Doc2UpModule/api/routes）+ 钩子在 `router/index.js`，门户卡片由 doc2up 登记行驱动（`cert/CertPortal.vue` 模板渲染、`cert/constants.js` 路由映射），下单面板复用 `cert/components/CertOrderPanel.vue`（`supportDuplex` 开关）；专项测试 `backend/tests/doc2up_feature_test.py`。
- 前端组件体系（Tailwind v4 + shadcn-vue）：`frontend/components.json`（CLI 配置）、`frontend/src/components/ui/*`（官方生成组件，勿手改外观逻辑）、`frontend/src/lib/utils.js`（`cn()`）、`frontend/src/components/layout/*`（AppHeader/MobileTabbar/ThemeToggle）、`frontend/src/composables/useNavTargets.js`（导航目标/高亮）、`frontend/vite.config.js`（`@tailwindcss/vite` + `@` 别名）、`frontend/jsconfig.json`。新增组件：`pnpm dlx shadcn-vue@latest add <component>`。

文档或代码变更后的最低验证建议：

- 只改文档：回读对应章节并检查路径、接口和环境变量名称是否仍与代码一致。
- 改后端业务：优先运行 `backend/tests/smoke_test.py`，并使用临时数据库和临时上传目录。
- 改前端交互：在有 Node 的环境运行 `pnpm --prefix frontend run build`（本机无 Node 时用 `node:22` 容器挂载构建，见 `doc/UI_ADAPTATION.md` 第 7 节），涉及页面布局时再做浏览器检查。
- 改真实打印：先在受控环境（测试用 CUPS 队列或备用打印机）跑通下单和后台测试页，确认无误后再接入生产打印机（`cups` 或 `system`）。

## 14. 版本控制与仓库发布

- 远端仓库：`https://github.com/BakInt/PrintHub`（public），默认分支 `main`，本地 `origin` 指向它。首次发布提交为 `7d96932e4cc7238997763d8af3a632f62f336170`（`chore: initial commit - PrintHub 云打印自助系统`，66 个文件），采用强制推送覆盖了远端原有的占位 `LICENSE`/`README.md`，两条历史线无共同祖先。
- 纳入版本控制的是源码/配置/文档共 66 个文件；`.gitignore` 排除 `frontend/node_modules/`、`frontend/dist/`、`config/`、`storage/`、`logs/`、`backups/`、`*.db`、`__pycache__/`、`.venv/`、`release/`、`.idea/`、`.vscode/` 与 NAS 冲突副本。空目录 `preview/` 不被 git 跟踪，不会出现在远端。
- 提交身份是仓库级配置：`user.name=BakInt`、`user.email=BakInt@users.noreply.github.com`（未改全局/系统配置）。推送凭据由 Git Credential Manager 提供，Windows 凭据管理器里已有 `git:https://github.com`（用户 `BakInt`）条目，因此 `git push` 无需再交互登录。
- 更新代码后的发布流程：`git add -A` → `git commit -m "..."` → `git push origin main`。若远端历史被本地覆盖过（如上），推送需带 `--force`；日常增量提交正常推送即可。
- 不要在仓库里提交 `config/`、数据库、上传文件或 `.env*`；这些都已由 `.gitignore` 排除。若新增其它运行时产物目录，同步补 `.gitignore` 规则。