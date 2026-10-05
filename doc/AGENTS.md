# PrintHub（云打印系统）- 代码协作说明

这份文件面向后续维护本仓库的编码代理和开发者。它描述当前代码的真实结构、业务逻辑、运行方式和修改注意事项。产品愿景和需求边界可参考 `doc/PRD.md`；本文件以现有代码为准。

## 1. 项目用途

这是一个基于 FastAPI + Vue 3 的在线云打印系统。用户可以上传 PDF、Office 文档或图片，后端保存原文件并转换为 PDF，计算页数和黑色覆盖率，通过安全检测后创建打印订单。订单支持支付宝/微信易支付、注册用户余额支付；注册用户还可以在线充值余额、用兑换码充值。支付成功或余额扣费成功后，系统会把 PDF 下发到打印服务。

后台提供运营概览、异常告警、订单详情、未支付订单清理、文件缓存清理、用户管理、系统价格/阈值/促销设置、易支付配置、支付自测、打印机管理和兑换码管理。

本系统没有「打印模式」配置项（`PRINT_MODE` 环境变量与 `print_mode` 设置已整体移除），打印方式完全由运行平台决定：Linux/macOS 走 CUPS 命令，Windows 读取系统已安装打印队列并优先使用 SumatraPDF 打印 PDF。所有打印都是真实打印，没有 mock 模拟模式。

## 2. 技术栈

- 后端：Python 3.12、FastAPI、SQLite、Pydantic Settings、bcrypt、PyPDF2、pdf2image、Pillow。
- 文档转换：系统安装 LibreOffice、Poppler、CUPS client、完整字体库（Noto CJK/CJK-extra、Noto Core/Extra/Mono、Liberation、Carlito、Caladea、DejaVu、STIX、Noto Color Emoji）和 `zh_CN.UTF-8`。字体映射与回退由 `docker/fontconfig/49-cloud-print-aliases.conf` 提供，把 Windows/Office 专有字体名（宋体/黑体/微软雅黑/Times New Roman/Arial/Wingdings 等）映射到已装字体，并为所有字体追加 CJK + 数学符号 + 图案符号兜底，避免转换/打印乱码。
- 打印：CUPS 命令、Windows PowerShell/SumatraPDF 分流（已移除 mock 模拟模式）。
- 前端：Vue 3、Vite、Vue Router、Pinia、lucide-vue-next。
- 部署：Docker Compose 单容器。`Dockerfile` 多阶段构建（Node 构建前端 → Python 运行镜像，FastAPI 同时托管 API 与前端静态文件），`docker-compose.yml` 用 `./config:/app/config` 绑定挂载持久化，`docker/entrypoint.sh` 负责建目录与生成配置文件。仓库里没有 `install.sh`/`configure.sh`/`start.sh`/`uninstall.sh`。
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
│   │   ├── database.py          # SQLite schema、轻量迁移、默认管理员和设置
│   │   ├── middleware.py        # 限流、安全响应头、生产配置校验；CSRF helper 尚未在 main.py 注册
│   │   ├── models/schemas.py    # 请求/响应 Pydantic 模型和支付方式归一化
│   │   ├── routers/             # public/auth/files/orders/user/admin API
│   │   ├── services/            # 文件、支付、计价、安全检测、认证会话、打印、按日统计服务
│   │   │   └── stats.py        # 后台「每日数据统计」：把 UTC 时间戳按**本地时区**聚合成每日订单数/收入/失败数
│   │   └── utils/security.py    # bcrypt 密码哈希和自定义 HMAC token
│   ├── tests/smoke_test.py      # 后端冒烟测试（import app.main 需要 pycups，适合容器内跑）
│   ├── tests/config_test.py     # config.json 生成/热加载/管理员重置测试（不依赖 CUPS，本地可跑）
│   ├── tests/queue_feature_test.py
│   ├── tests/daily_stats_test.py # 「每日数据统计」本地时区分日聚合专项测试（不依赖 CUPS，本地可跑）
│   ├── requirements.txt
│   └── run.py                   # 本地开发入口
├── frontend/
│   ├── src/
│   │   ├── App.vue
│   │   ├── api/client.js        # fetch 封装、token 注入、CSRF token 自动携带
│   │   ├── router/index.js
│   │   ├── stores/auth.js
│   │   ├── stores/theme.js      # 亮/暗主题状态：localStorage 记忆 + 跟随系统 + 视口判定
│   │   ├── views/               # 首页、认证、支付、个人中心、后台
│   │   ├── components/          # 可复用组件：DailyStatsCard.vue（后台概览「每日数据统计」卡片，内联 SVG 图表）
│   │   ├── assets/theme.css     # 主题变量：PC 亮/暗、移动端亮/暗四套独立 palette
│   │   └── assets/styles.css    # 组件样式（颜色一律引用 theme.css 的 var(--cp-*)）
│   ├── index.html               # 含首屏防闪烁内联脚本（样式生效前写入 data-theme）
│   ├── package.json
│   ├── pnpm-lock.yaml           # 包管理器是 pnpm（Dockerfile 用 pnpm@10.15.0 --frozen-lockfile）
│   └── nginx.conf               # 旧的独立 Nginx 配置，仅备用（生产由 FastAPI 托管前端）
├── scripts/test_printer.py      # 命令行测试样张脚本
├── scripts/theme_*.py           # 主题化工具（tokenize/check/audit/class_audit 等），不参与运行
├── Dockerfile                   # 多阶段构建：Node 构建前端 → Python 运行镜像（FastAPI 同时托管前端）
├── docker-compose.yml           # 单容器；./config:/app/config 绑定挂载持久化
├── docker/                      # entrypoint.sh、fontconfig 字体映射、nginx 配置（备用）
├── README.md
└── doc/PRD.md
```

仓库中存在若干带 `BakingdeMini.lan的冲突副本...` 的同步冲突副本。正常维护时以不带冲突副本后缀的正式文件为准，除非用户明确要求从冲突副本恢复内容。`release/` 是打包产物快照，通常不要作为源码修改入口。

仓库根目录的 `.gitattributes` 固定行尾策略：`* text=auto eol=lf` 让全部文本文件以 LF 入库（含 `*.sh`/`*.conf`，保证 Linux 容器内 shebang 可用），Windows 侧 `*.bat`/`*.cmd`/`*.ps1` 保持 CRLF，图片/PDF/DB 标记为 binary。因此在 Windows 上工作区若出现 CRLF，`git add` 时会提示 `CRLF will be replaced by LF`，这是预期行为，不要为了消除警告去改 `.gitattributes`。忽略规则集中在 `.gitignore`（Python 缓存、`.env*`、`config/`、`storage/`、`logs/`、`frontend/node_modules/`、`frontend/dist/`、`release/`、编辑器目录、NAS 冲突副本）。

## 4. 后端入口和生命周期

`backend/app/main.py` 创建 FastAPI 应用：

1. 导入时先调用 `bootstrap()`（`backend/app/bootstrap.py`）：确保配置目录里存在 `config.json`（缺失就按默认值生成、含随机 `app_secret`）并创建数据库/上传/备份/日志/CUPS 驱动目录；随后 `get_settings()` 读取配置并打印配置目录、配置文件、数据库位置。
2. 注册 CORS、限流、TrustedHost 和安全响应头中间件，并注册全局兜底异常处理 `@app.exception_handler(Exception)`：未捕获异常记录堆栈后返回 `{"detail": "服务器内部错误，请稍后重试"}` 的 JSON，避免前端只拿到 FastAPI 默认的纯文本 500 "Internal Server Error"。
3. 启动时先调用 `_warn_data_outside_config_root()`（容器里若数据库/上传等路径跑到配置目录之外会打印警告，提示重建容器会丢数据），再调用 `validate_production_config(settings)`、`init_db()`、`start_print_status_monitor()`、`start_auto_backup_scheduler()`。
4. 注册路由：`public`、`auth`、`files`、`orders`、`admin`、`admin.setup_router`、`user`。
5. 在所有路由之后注册前端静态文件服务（`/assets`、`/static`）和 catch-all 路由。

`backend/app/database.py` 负责：

- 创建 SQLite 表：`users`、`files`、`orders`、`order_items`、`payments`、`settings`、`alerts`、`printers`、`auth_sessions`、`login_failures`、`redemption_codes`、`redemption_logs`。
- 通过 `SCHEMA_MIGRATIONS` 给旧库补列，新增表通过 `CREATE TABLE IF NOT EXISTS` 创建。
- 打印机能力列：`printers.is_support_color INTEGER DEFAULT 0`（是否支持彩色打印）、`printers.is_support_auto_duplex INTEGER DEFAULT 1`（是否支持自动双面打印）；`SCHEMA_MIGRATIONS["printers"]` 同步补 `"is_support_color": "INTEGER DEFAULT 0"`、`"is_support_auto_duplex": "INTEGER DEFAULT 1"`。旧库升级后彩色默认关闭（保持「旧版不展示彩色」）、自动双面默认开启（保持升级后旧行为不变）。
- 订单彩色列：`orders.use_color INTEGER`（**故意不带 DEFAULT**），`SCHEMA_MIGRATIONS["orders"]` 补 `"use_color": "INTEGER"`。语义：NULL=旧数据/旧前端未指定（完全走原有黑白流程）、1=用户选择彩色、0=用户选择黑白。
- 写入默认设置：计价模式、单双面价格、按覆盖率计价基础价、阶梯折扣、每日限时特价、最低余额、安全覆盖率阈值、文件大小限制、最大页数、支付配置、默认打印机。
- 初始化时删除旧库遗留的 `print_mode` 设置键（打印模式配置已整体移除，避免它在后台设置接口里回显）。
- 初始化管理员账号。用户名/密码取 `config.json` 的 `admin_username` / `admin_password`（默认 `admin` / `admin123456`）；`reset_admin_password=true` 时下次启动会把已有管理员密码强制改回该值并自动写回 `false`。

注意：`get_settings()` 不再用 `@lru_cache`，而是按 `config.json` 的 `mtime`/`size` 指纹热加载——改完配置文件无需重启即生效（`reload_settings()` 可强制重读）。优先级仍是「环境变量 > config.json > 内建默认值」，所以测试里改环境变量仍要在导入 `app.main` 之前设置。

`config.json` 里的部署级键：`environment`、`app_secret`、`database_path`、`upload_dir`、`backup_dir`、`log_dir`、`cups_driver_dir`、`trusted_hosts`、`cors_origins`、`session_cookie_secure`、限流与会话有效期、`admin_username`/`admin_password`/`reset_admin_password`、`cups_job_timeout_seconds`、`printer_probe_timeout_seconds`、`print_status_check_interval_seconds`、`print_confirm_timeout_seconds`。相对路径按配置目录归一，整个目录搬家后配置依然有效。业务配置（价格、促销、阈值、上传限制、支付、CUPS、默认打印机）不在这个文件里，它们在 SQLite 的 `settings` 表、以后台页面为准；`cups_*`/`epay_*` 只在首次建库时从 `config.json` 播种进数据库。

## 5. 认证和会话

相关文件：`backend/app/routers/auth.py`、`backend/app/services/auth_session.py`、`backend/app/routers/deps.py`、`backend/app/utils/security.py`、`frontend/src/api/client.js`。

- 密码新存储格式是 `bcrypt$...`；旧 `pbkdf2_sha256` 密码登录成功后会自动 rehash 为 bcrypt。
- 登录和注册都需要验证码。验证码通过 `GET /api/auth/captcha` 返回 PNG，答案写入 `auth_sessions` 并在验证后一次性清空。
- `GET /api/auth/csrf` 会创建访客会话并返回 CSRF token；前端非安全方法会自动携带 `X-CSRF-Token`。
- 当前 `main.py` 没有注册 `csrf_middleware`，所以 CSRF token 目前是前端兼容性准备，不是已启用的后端强制校验。
- 登录成功会同时设置 HTTP-only session cookie 和返回自定义 HMAC bearer token。`current_user()` 优先解析 `Authorization: Bearer ...`，没有 token 时回退到 session cookie。
- 登录失败按 IP + 用户名累计，达到 `LOGIN_LOCK_THRESHOLD` 后在 `LOGIN_LOCK_SECONDS` 内仍返回统一错误“用户名或密码错误”。
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
   - Office 文件调用 LibreOffice headless 转成 `converted.pdf`。转换使用带参数的 PDF 导出过滤器（`writer_pdf_Export` 开启 `EmbedStandardFonts`/`UseTaggedPDF`），强制把用到的字体子集嵌入 PDF，确保下游打印不再依赖打印机字体、避免乱码。转换成功后立即调用 `flatten_pdf_smask()`（见 `backend/app/services/pdf_postprocess.py`）拍平图像软遮罩，避免公式/透明图在 CUPS 光栅化时被整块丢弃。
4. `page_count()` 用 PyPDF2 读取页数，并校验最大页数；上限取后台「系统设置」的「最大页数」（数据库 `settings` 表的 `max_pages`），环境变量 `MAX_PAGES` 只在设置缺失或非法时作为兜底默认值。
5. `calculate_black_coverage_details()` 用 pdf2image/Poppler 把 PDF 每页转图片，统计灰度 `< 128` 的深色像素比例，保存平均覆盖率和逐页覆盖率。
6. `safety_result()` 按覆盖率阈值判断是否安全；阈值取后台「系统设置」的「覆盖率阈值」（数据库 `settings` 表的 `safety_coverage_limit`），环境变量 `SAFETY_COVERAGE_LIMIT` 只在设置缺失或非法时作为兜底默认值。因此后台改阈值后，之后新上传的文件立即按新阈值判定；已入库文件保留其上传时的 `is_safe` 结果，不会追溯重算。
7. 文件入库。转换或检测失败的文件也会以 `status='failed'`、`is_safe=0` 记录；安全失败会写入 `alerts`。

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

后端返回 PDF `FileResponse`，`Content-Disposition` 为 inline。前端首页和后台订单详情都用 `iframe` 预览 PDF。缓存被清理后，预览接口会返回 404。

### 6.3 计价和促销

入口：`POST /api/price`、`GET /api/promotions`，实现于 `backend/app/routers/public.py` 和 `backend/app/services/pricing.py`。

计价模式：

- `standard`：单面按 `page_count * copies * single_price`，双面按 `ceil(page_count / 2) * copies * duplex_price`。
- `coverage_tiered`：按每页黑色覆盖率分档乘以基础价，单面使用 `coverage_single_base_price`，双面使用 `coverage_duplex_base_price`。

自动双面（按份独立）：

- 「自动双面」的定义是——批量上传多份文档时，用户为每份文档单独选择是否双面。启用后仅把该份多页文档的内容打印在同一张纸的正反两面。
- 双面不会跨文档合并：两份单页文档不会被合并到同一张 A4 纸的正反面；每份单页文档只能单面。
- `POST /api/price` 与 `POST /api/payment/create` 都接受按份设置 `file_settings`（`[{file_id, double_sided}]`）；未在其中出现的文件回退到全局 `double_sided`（历史兼容）。
- `PrintSettings.use_auto_duplex`（`bool | None`）是全局双面回退值：非 None 时取代全局 `double_sided` 作为未单独设置文档的回退值，逐份 `file_settings.double_sided` 仍然优先；None 表示旧前端未携带，完全沿用原逻辑。
- `calculate_files_price_detail()` 逐份文档按自身页数与自身单/双面折算张数与金额后求和；`resolve_file_double_sided()` 对页数 < 2 的文档强制单面。
- 若请求为某份页数 < 2 的文档启用双面，`create_order` 返回 400。

折扣规则：

- `bulk_discount_enabled` + `bulk_discount_rules`：按 `sheet_count` 选择命中的最高门槛折扣，默认 10 张 95 折、100 张 90 折、200 张 80 折。
- `daily_limited_offer_*`：每日固定时间窗口内、剩余张数足够时可应用限时折扣。
- 多个折扣同时命中时取最终金额最低的方案。

订单会保存 `sheet_count`、`base_amount`、`discount_amount` 和完整 `pricing_detail`，后台订单列表依赖这些字段展示金额拆分。

### 6.4 下单和支付

入口：`POST /api/payment/create`，实现于 `backend/app/routers/orders.py`。

流程：

1. 校验文件 ID 非空、无重复、文件存在且全部安全。
2. 解析按份双面：`file_settings` 中指定的文件用其独立设置，其余回退全局 `double_sided`（`print_settings.use_auto_duplex` 非 None 时改以它作为回退值，逐份设置仍优先）；对任一被请求双面但页数 < 2 的文档返回 400，文案为「双面打印仅适用于自身页数不少于 2 页的文档，单页文档只能单面打印」。
3. 调用 `calculate_files_price_detail()` 逐份汇总价格；每份文档的生效双面值写入 `order_items.is_double_sided`，`orders.is_double_sided` 作为「是否含双面文档」的聚合标识；`use_color` 写入 `orders.use_color`（None=未指定 / 1=彩色 / 0=黑白）。
4. 联系人姓名和手机号必填。登录用户可从 `users.real_name`、`users.phone` 自动补齐；手机号要求中国大陆 11 位格式。
5. 打印机能力兜底校验（`resolve_order_printer()` 按订单解析目标打印机，未指定则取默认打印机；查不到打印机记录时跳过校验以兼容老部署）：`print_settings.use_color is True` 但该打印机 `is_support_color=0` → 400「该打印机未开启彩色打印，请重新选择打印方式」；订单含双面但该打印机 `is_support_auto_duplex=0` → 400「该打印机未开启自动双面打印，请重新选择打印方式」。前端已按能力条件渲染，这里是防止绕过的兜底。
6. 如果是余额支付：
   - 必须登录。
   - 校验支付后余额不能低于 `min_balance`。
   - 创建订单和支付记录后扣减余额，订单置为 `paid`。
   - 立即调用 `dispatch_order_print()`。
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

相关文件：`backend/app/services/printer.py`、`backend/app/services/print_monitor.py`、`scripts/test_printer.py`。

打印方式完全由运行平台决定（`print_mode` 设置与 `PRINT_MODE` 环境变量已整体移除，没有可选打印模式，也没有 mock 模拟）：

- Linux/macOS：通过 CUPS 命令管理和打印，主要命令包括 `lpstat`、`lpinfo`、`lpadmin`、`lpoptions`、`cupsenable`、`cupsdisable`、`lp`、`cancel`。
- Windows：使用 PowerShell 读取系统已安装打印队列，并用 `config.json` 的 `sumatra_pdf_path` 或 `windows_pdf_print_command` 指向的 SumatraPDF 打印 PDF，未配置时回退系统 `PrintTo`；macOS 额外读取 `system_profiler SPPrintersDataType` 补充队列来源。

`printer.print_pdf()` 不再接收 `print_mode` 参数，签名为 `print_pdf(pdf_path, copies, double_sided, printer_name=None, default_printer=None, use_color: bool | None = None)`；`print_jobs_active(job_ids)` 也不再接收打印模式。

`dispatch_order_print()` 会根据订单的 `printer_name`、settings 中的 `default_printer` 和份数，并逐份读取 `order_items.is_double_sided` 作为该文件的单双面参数调用 `print_pdf()`。成功后订单状态更新为 `printing`，失败则为 `print_failed` 并写入 `print_error`。

`print_pdf()`（CUPS 路径）在用 `lp` 提交前会调用 `rasterize_pdf_for_print()`（见 `backend/app/services/pdf_postprocess.py`），用 poppler `pdftoppm` 把待打印 PDF 每页光栅化成 300dpi 不透明位图并重组为「纯图像 PDF」再提交。这样远端 CUPS/打印机的 RIP 只需绘制不透明图片，彻底规避老式 OLE 公式/WMF/EMF/透明图元在远端 RIP 上被整块丢弃的「上传打印后化学式消失」问题（详见 6.1）。它仅作用于打印副本、不改动入库/预览的原始 PDF，页数页序不变，光栅化失败会安全降级为直接打印原 PDF；打印任务提交后本地临时图像 PDF 会被删除。光栅化每页还会经 `_darken_faint_content()` 套分段灰度 LUT，把老式公式预览图的中灰笔画压到纯黑、保护白底不发灰，解决「公式打印出来颜色很淡」（详见 6.1）。Windows 走 SumatraPDF/`PrintTo`，本身就是本地整页光栅化，不额外处理。

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

## 7. API 路由概览

公开接口：

- `GET /api/health`：健康检查。
- `GET /api/ready`：数据库就绪检查。
- `GET /api/promotions`：前台展示当前促销。
- `GET /api/limits`：前台读取生效的上传限制（`max_file_size_mb`、`max_pages`）；优先取后台设置，缺省回退环境变量默认值。首页用它渲染上传提示文案。
- `GET /api/print-options`：前台读取当前（默认）打印机的打印能力，返回 `{"printer_name", "printer_configured", "is_support_color", "is_support_auto_duplex"}`；取 `settings` 表的 `default_printer`，未配置默认打印机或查不到该打印机记录时 `printer_configured=false` 且两项能力均为 false。首页用它做条件渲染，不硬编码。
- `POST /api/price`：按页数或文件列表、份数、单双面计算价格。

认证接口：

- `GET /api/auth/csrf`：创建/读取访客会话和 CSRF token。
- `GET /api/auth/captcha`：生成验证码 PNG。
- `POST /api/auth/register`：用户名/密码/验证码注册，可带邮箱/手机号。
- `POST /api/auth/login`：登录并返回 token。
- `POST /api/auth/logout`：销毁会话并清除 cookie。
- `GET /api/auth/me`：读取当前用户。

文件接口：

- `POST /api/upload`：上传、转换、检测并入库。
- `GET /api/files/{file_id}/preview`：PDF inline 预览。
- `POST /api/check-safety`：读取某文件安全检测结果。

订单和支付：

- `POST /api/payment/create`：创建打印订单。
- `GET /api/orders/{order_id}`：查询订单，并在必要时刷新打印状态。
- `GET /api/payment/submit/{order_id}`：返回易支付自动提交页。
- `GET|POST /api/payment/notify`：易支付异步回调。
- `GET /api/payment/return/{order_id}`：易支付同步返回并跳回前端。

用户中心：

- `GET /api/user/orders`：当前登录用户订单分页，支持 `limit`（默认 10，1-50）、`offset`（默认 0）。返回 `{items, total, has_more, total_spent}`，`total_spent` 为全量打印消费，供前端「加载更多」与统计使用。
- `PUT /api/user/profile`：绑定/更新真实姓名和手机号。
- `POST /api/user/recharge`：创建余额充值订单。
- `POST /api/user/redeem`：个人中心「兑换码充值」，`code` 必填，校验存在/过期/剩余次数后按面额加余额并写 `redemption_logs`；错误统一返回标准 JSON（`detail` 为 `{code, message}` 的中文提示），不返回纯文本 500。详见 6.8。

后台接口均在 `/api/admin` 下，需要管理员 token 或 session，包含：

- `/dashboard`、`/daily-stats`（后台概览「每日数据统计」：`days` 取 1-90、默认 7，按**本地时区**返回每日订单数、收入、打印失败数与失败率，聚合逻辑在 `backend/app/services/stats.py`；收入口径与 `/dashboard` 一致——统计 `orders` 全表、不按 `order_type` 过滤）、`/orders`、`/orders/{id}/detail`、`/orders/{id}/mark-complete`、删除单个订单、删除未支付订单、批量删除未支付订单。
- `/file-cache/cleanup`：按时段统计或清理上传缓存，可选择是否包含已关联订单文件。
- `/users`：创建、编辑、启停、删除用户，余额增减或设置；保护最后一个管理员和当前管理员。
- `/redemptions`：手动新增（`code` 可留空，留空由后端自动生成随机码；可传 `per_user_max_times` 设置「每个用户最大兑换次数」，正整数=限制、0 或缺省=不限制；有效期用 `expiry_mode`（`days`/`date`）+ `expire_date` 二选一）、批量随机生成（同样支持 `expiry_mode`/`expire_date`）、列表与搜索、兑换记录、删除；详见 6.8。
- `/settings`：系统价格、促销、阈值、文件大小/页数上限和默认打印机。接口保存后会返回 `notices`，提示哪些键（`cups_*`/`epay_*`）的实际值来自建库时写入的 `config.json` 快照、之后再改 `config.json` 不会覆盖后台设置（库优先）；**后台页面不再展示这些 notices**（否则成功保存也会出现红色提示），保存成功只在页面顶部显示绿色「保存成功」。
- `/payment-settings`、`/payment-test`：易支付配置、配置校验、测试单查询和模拟成功。
- 打印机管理（实现于 `backend/app/services/cups_printer.py`）：`/printer-system`（运行环境与 CUPS 连通性诊断）、`/printers`（枚举真实队列）、`/printer-drivers` 与 `/printer-drivers/ppd`（驱动列表与上传 PPD）、`/printer-info`、`/printer-uri/probe`、`/printers/{name}`（查询/编辑/删除）、`/printers/{name}/default`、`/printers/default/clear`、`/printers/{name}/enabled`、`/printers/{name}/test-page`、`/printers/{name}/test-result`、`/printers/{name}/jobs`、`/cups/logs`、`/cups/queues`、`/cups/diagnostics`。打印机配置记录带 `is_support_color`、`is_support_auto_duplex` 两个能力字段，`GET /api/admin/printers`（列表）与 `GET /api/admin/printers/{printer_name}`（详情）都会返回；编辑走 `PATCH|PUT /api/admin/printers/{printer_name}`（payload 为 `PrinterUpdate`，两项能力为可选 `bool | None`，None=不修改），本仓库没有新增打印机的 POST 路由。
- `/alerts/{id}/handle`：处理异常告警。

## 8. 前端结构和页面

`frontend/src/App.vue` 是全局壳，顶部导航根据 `auth.user` 显示个人中心、后台和退出按钮（「后台」链接与「退出」之间是亮/暗主题切换按钮 `.theme-toggle`，点击调用 `theme.toggleTheme()`）。应用启动时调用 `auth.loadMe()`。

亮/暗主题：`frontend/src/stores/theme.js` 维护主题状态（`localStorage['cloud-print-theme']` 优先，未选择过则跟随 `prefers-color-scheme` 并实时监听系统变化；同时用 `matchMedia('(max-width: 767px)')` 判定手机端），把结果写到 `documentElement` 的 `data-theme`。变量层在 `frontend/src/assets/theme.css`，**PC 电脑端与移动手机端各有独立的亮/暗两套 palette，不共用一套 CSS 控制两端**；组件样式只引用 `var(--cp-*)`。`frontend/index.html` 的 `<head>` 内联脚本在样式生效前写入 `data-theme` 防首屏闪烁。详见 `doc/UI_ADAPTATION.md` 第 5.5 节。

路由在 `frontend/src/router/index.js`：

- `/`：`HomeView.vue`，上传、文件列表、促销展示、PDF 预览、联系人、打印设置、计价和下单。
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
- 拉取 `/api/print-options`（`onMounted` 的 `loadPrintOptions()`，同时加入价格试算 watch 依赖）：只有 `is_support_color` 为 true 才展示「彩色打印」卡片（黑白/彩色分段选择器，默认黑白）；只有 `is_support_auto_duplex` 为 true 才展示「自动双面」卡片、文件行内的「自动双面（本份文档正反面）」勾选框与底部说明。不支持时对应 UI 完全隐藏，且不会向请求里带该能力（`file_settings.double_sided` 一律为 false）。
- 提交 `POST /api/payment/create` 时，仅在打印机支持对应能力时才在 `print_settings` 中携带 `use_color`（用户是否选彩色）与 `use_auto_duplex`（用户是否选择了自动双面），不支持时保持与旧版一致的请求结构。
- 余额支付按钮只对登录用户可用。
- 非余额支付创建订单后，跳到后端返回的 `/api/payment/submit/{order_id}`。
- 余额支付创建成功后进入 `/payment/{order_id}` 查看状态。

`DashboardView.vue` 的关键行为：

- 用户可维护真实姓名和 11 位手机号；首页下单可自动使用这些联系人信息。
- 支持支付宝/微信充值，成功创建充值单后跳转到后端支付提交页。
- 从 `recharge_order` query 返回时会刷新用户信息和订单列表。

`AdminView.vue` 是目前最大的前端文件，集中实现后台所有 tab。修改后台时优先复用现有 `runAction()`、`loadTab()`、`showFeedback()` 模式，避免引入不一致的状态管理方式。**手机端导航**：后台共 8 个 tab，窄屏底部放不下，因此在桌面侧边栏 `</aside>` 之后、`.panel.admin-panel` 之前加了后台自己的底部 Tab 栏 `<nav class="admin-tabbar">`（`grid-template-columns: repeat(5, 1fr)`）：前 4 格是常用 tab（`MOBILE_PRIMARY_TAB_KEYS = ['dashboard', 'orders', 'users', 'settings']`，来自 `primaryTabs` computed，图标 22px + 文案），第 5 格是「更多」按钮，其余 4 个 tab（`moreTabs` computed：支付/兑换码/备份/打印机）收进从底部浮出的「更多」面板（`.admin-more-mask` 遮罩 + `.admin-more-sheet` 抽屉，`v-if="moreOpen"`，遮罩 `@click.self="moreOpen = false"` 关闭，面板底部有 `.admin-more-back` → `/` 返回前台，因为手机端顶栏导航文字入口被隐藏）。当前处在「更多」里的 tab 时，第 5 格会显示该 tab 的图标与名称并高亮（`moreCurrent`/`moreActive`）。两端共用同一个 `tab` ref 与文件末尾的 `watch(tab, loadTab)`，底部栏点击走 `selectTab(key)`（只做 `tab.value = key; moreOpen.value = false`），**行为与点桌面 `.admin-menu` 完全一致，不涉及路由跳转**。样式规则：`.admin-tabbar` 与 `.admin-more-mask` 基础层是 `display: none`（桌面零变化），仅 `@media (max-width: 767px)` 内显示，同断点下 `.admin-menu { display: none }`；层级为 Tab 栏 `z-index: 40`、「更多」遮罩 `39`（低于 Tab 栏，遮罩不挡 Tab 栏）、`.mobile-submit-bar` `30`、兑换码抽屉 `.redemption-drawer-overlay` `110`；Tab 栏高度 `calc(60px + env(safe-area-inset-bottom))`，与前台 `.mobile-tabbar` 同高，所以 `main` 既有的底部 padding 预留无需改动。`App.vue` 给外壳加了 `:class="{ 'app-shell-admin': isAdminRoute }"`（`isAdminRoute = route.path.startsWith('/admin')`），配合 `styles.css` 767px 内的 `.app-shell-admin .mobile-tabbar { display: none }` 隐藏前台「首页/订单/我的」底部栏，避免两条底部栏叠加。

概览 tab 的 6 个统计卡片下方是「每日数据统计」卡片（`frontend/src/components/DailyStatsCard.vue`，`components/` 目录里目前唯一的组件，由 `AdminView.vue` 概览 tab 直接 `<DailyStatsCard />` 引入；切回概览会重新挂载并重新拉取数据）。它自带时间范围切换（近 7 天/近 30 天，走 `GET /api/admin/daily-stats?days=`）、三个维度 Tab（订单趋势/收入趋势/打印失败分布，纯前端切换、不重新请求）、可点击切换显示/隐藏的图例、hover 提示框与空状态。图表是**手写内联 SVG**，没有引入任何图表库：柱子走左轴用 `--cp-brand`，折线走右轴用 `--cp-swatch-cyan`（因为 PC 暗色 palette 里 `--cp-brand` 与 `--cp-brand-hi` 取值相同、无法区分两条系列），`AXIS_TITLES` 里 `count` 对应「数量」。宽度由 `ResizeObserver` 实测 `.daily-stats-chart` 得到，`viewBox` 与 SVG 用户坐标一一对应 CSS 像素，所以 767px 以下只降低高度（`theme.isMobile ? 216 : 264`）而不缩放字体。样式（`.daily-stats-*` 一整套）追加在 `frontend/src/assets/styles.css` 末尾，含独立的 `@media (max-width: 767px)` 与 `@media (max-width: 420px)` 段。

打印机 tab 的卡片上展示能力标签（`支持彩色打印`/`仅黑白打印`、`支持自动双面`/`仅单面打印`）与「编辑打印机」按钮（此前编辑弹窗没有入口，本次已修复可达性）；编辑弹窗内新增「打印机能力」区块，两个复选框分别对应 `is_support_color`、`is_support_auto_duplex`，保存时随 `PATCH /api/admin/printers/{name}` 一起提交。本次新增样式（后台的 `.cap-tag`/`.capability-*`/`.swatch`，首页的 `.color-control`/`.color-methods`）都写在 `frontend/src/assets/styles.css`，桌面与手机端（media query）各有一套。首页「彩色打印」卡片保持极简：只有标题和 `黑白 / 彩色` 分段按钮，选项按钮直接复用通用 `.segmented` 样式，不额外加装饰圆点、状态徽标和说明文字。

兑换码 tab 的列表已精简为 5 列（兑换码 / 兑换面额 / 有效期 / 使用状态 / 操作），其中「有效期」列由 `redemptionExpiryText(code)` 渲染——`expiry_mode === 'date'` 显示「截止 YYYY-MM-DD HH:mm:ss」（即该日 23:59:59），否则按 `valid_days > 0` 显示「N 天」或「永久有效」。表格外层是 `.redemption-table-scroll`（`overflow-x: auto`），表格本体 `.redemption-table` 设了 `min-width: 560px`，让操作列 `.redemption-cell-actions` 能用 `position: sticky; right: 0` 吸附在右侧、始终可见（`min-width` 必须大于滚动容器宽度，否则 sticky 没有可移动空间；≤767px 时 `min-width` 归 0 且 sticky 取消）。生成时间、单用户上限、兑换用户等次要信息不在表格里，点行内「详情」按钮打开右侧抽屉 `.redemption-drawer`（由 `selectedRedemptionDetail` 控制显隐，遮罩 `.redemption-drawer-overlay` 点击空白处关闭）：`openRedemptionDetail(code)` 先展示列表项已有的完整信息（完整兑换码、面额、已兑换次数 `used_count / usable_count`、生成时间、有效期类型 `expiry_mode`、有效天数、精确到期、单用户使用上限、使用状态、累计可兑金额 `total_amount`），同时请求 `GET /api/admin/redemptions/{id}/logs` 拉取「已兑换用户」列表（`redemptionDetailLoading` 控制加载态，`redemptionLogs` 复用原记录弹窗的数据）。「有效期」一行在手动新增与批量生成两个弹窗里都是`.form-row.expiry-row`：标签右侧 `.expiry-control` 是**单行 flex 布局**——左侧 `.expiry-mode` 分段按钮（复用通用 `.segmented` 规范、改为 `display: inline-flex` 收缩到内容宽度，按钮「按天数」/「指定到期日期」），右侧紧跟当前模式的输入控件，两模式用 `v-if/v-else` 二选一渲染数字输入框或 `<input type="date">`（**不会同时出现两个输入框**，切换只替换右侧控件、整行不换行），提示 `.expiry-hint` 用 `flex: 1 1 100%` 独占下一行，由 `redemptionExpiryHint` / `batchRedemptionExpiryHint`（computed，内部走 `redemptionExpiryHintOf(form)`）给出文案；详情抽屉「有效天数」值由 `redemptionDetailValidDays(code)` 渲染，日期模式显示「—（按到期日期）」。抽屉样式在 `frontend/src/assets/styles.css` 末尾，含独立的 `@media (max-width: 767px)` 段（抽屉占满宽度、详情网格改单列）；`.expiry-control`/`.expiry-mode`/`.expiry-hint` 也写在 `styles.css`（`.expiry-control` 为 `display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px`，`.expiry-control .input` 把全局 `.input { width: 100% }` 覆盖为 `width: auto; min-width: 0`，数字框 `flex: 0 1 160px`、日期框 `flex: 1 1 150px; max-width: 220px` 自适应收缩，桌面按钮 38px 高 / 提示 12px；767px 下按钮与输入框同为 46px 高、按钮内边距压到 `0 10px` 以保持单行，`flex-wrap` 只作极窄屏兜底），同样按类名作用域化、不新增全局规则。删除按钮仍在行内直接调用 `deleteRedemption(code)`。

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
- 修改认证时要同时考虑验证码、session cookie、bearer token、登录失败锁定和前端 `auth` store。
- 修改支付时，要同步 `epay.py`、`orders.py`、`user.py`、后台支付配置、支付自测和 `backend/tests/smoke_test.py`。
- 修改余额充值时，必须保留 `balance_applied_at` 防重复入账。
- 修改兑换码时，要保持 `AdminRedemptionCreate.code` 可缺省（留空、空串、纯空白或不传都自动生成随机码），用户侧 `RedeemRequest.code` 仍必填；同步 `backend/app/services/redemption.py`、后台兑换码弹窗和个人中心兑换入口。兑换入账的「占用可用次数 + 加余额 + 写 `redemption_logs`」必须在同一事务（`BEGIN IMMEDIATE` + 条件 UPDATE + 失败回滚）内完成；错误要返回带 `{code, message}` 的标准 JSON，不要抛原始异常。**服务函数必须用别名引入**（`from ..services.redemption import redeem as redeem_redemption_code`）：在 `backend/app/routers/user.py` 里若让服务函数与路由函数同名，路由会调用自己并抛 `AttributeError`（前端只显示纯文本 500）。
- 修改计价时，要同步前台 `/api/price`、`/api/promotions`、后台配置表单、订单保存字段和烟测断言。
- 修改兑换码的「限制每个用户最大兑换次数」（`per_user_max_times`）时：该列须在 `SCHEMA` 与 `SCHEMA_MIGRATIONS["redemption_codes"]` 同时存在，且默认值 0（0=不限制，保持原「按总可用次数」逻辑）；`create_code()` 的第 6 个位置参数要在 `backend/app/routers/admin.py` 里透传 `payload.per_user_max_times`（漏传会让这个限制静默失效）。`redeem()` 里**两种模式共用同一条条件 UPDATE**（`WHERE id = ? AND used_count < usable_count`）来占用全局次数；「每个用户最大兑换次数」只是在 `BEGIN IMMEDIATE` 写锁内额外多做一道 `count_user_redemptions() >= per_user_max_times` 判定，**不要**给 `per_user_max_times>0` 的码改成无条件累加 `used_count`（那正是旧版「每用户一次就忽略总次数」的错误语义，会让 `usable_count=1` 时第二个用户也被放行）。旧库的 `per_user_once=1` 由 `migrate_redemption_per_user_limit()` 一次性换算成 `per_user_max_times=1`，代码不再读写旧列。后台兑换码列表已精简为 5 列（兑换码 / 兑换面额 / 有效期 / 使用状态 / 操作），`per_user_max_times`、已兑换次数、生成时间、兑换用户等次要信息不在表格里，全部移入右侧「兑换码详情」抽屉中展示，弹窗「手动新增兑换码」的样式全部写在 `frontend/src/assets/styles.css` 并**按类名作用域化、不新增全局规则**（不污染打印机弹窗共用的 `.form-row`/`.modal-content`）：卡片 `.redemption-modal`（底 `--cp-surface-glass` 半透明 + `backdrop-filter: blur(12px)`、边框 `--cp-brand-border`，深色主题下即「深色深蓝半透明卡片」，浅色主题自动降级为半透明白）、标题居中 `.redemption-modal-header`（关闭按钮绝对定位在右侧）、表单 `.redemption-form .form-row`（标签居左 / 输入框居右两列，输入框边框 `--cp-border-input`、聚焦 `--cp-brand`，≤767px 媒体查询里改为一列上下排布）、带边框分组卡片 `.per-user-card`（边框 `--cp-brand-border`、底 `--cp-soft`：左侧开关 `.toggle-switch`「开启单用户次数限制」、右侧 `.per-user-limit-input` 的「最大使用次数」数字输入框，开关关闭时 `disabled` 置灰，分组底部只有一行短提示「开启后，同一用户最多可使用该兑换码 N 次。」，N 由纯展示计算属性 `perUserMaxTimesHint` 给出——开启时显示实际填写值、关闭时显示占位 `N`）。绑定仍是 `redemptionForm.per_user_limit_enabled` / `per_user_max_times`，提交时关闭则发 0，业务逻辑未变。表格列数/列宽改动要同步 `frontend/src/assets/styles.css` 的 `.redemption-table-head, .redemption-row` 的 `grid-template-columns`（现为 5 列），并注意 `.redemption-table` 的 `min-width` 是操作列 `position: sticky` 能生效的前提（表格必须宽于滚动容器才有可移动空间），≤767px 时要把它降回 0 并取消 `.redemption-cell-actions` 的 sticky。专项回归测试：`python tests/redemption_per_user_test.py`（Windows 本地可跑，不需 pycups/CUPS）。
- 修改兑换码有效期方式（`expiry_mode` = `days`/`date` 二选一）时：**刻意不加数据库列**，语义完全由 `(valid_days, expires_at)` 组合表达——`expires_at` 非空且 `valid_days=0` 视为 `date`，否则 `days`，读取一律走 `expiry_mode_of(code_row)`，不要新增 `expiry_mode` 列，也不要改动 `code_status()` 的判断顺序（**过期判断必须始终优先于次数判断**）。日期归一化集中在 `backend/app/services/redemption.py` 的 `normalize_expire_date()`（接受 `YYYY-MM-DD`、`date`/`datetime`、带时间 ISO 串，一律落到**当天 23:59:59** 的 `isoformat(timespec="seconds")`；非法值返回 `None`）；服务层遇非法日期回退「按天数」，写接口由 `AdminRedemptionCreate.normalize_redemption_payload` 与 `AdminRedemptionBatchCreate.normalize_expiry` 拦住（报 `请选择有效的到期日期（格式 YYYY-MM-DD）`），并把非 `date` 模式的 `expire_date` 清空、`date` 模式的 `valid_days` 强制归零，避免两种方式同时生效。`create_code()` 新增第 7 个（关键字）参数 `expires_at`、`batch_generate_codes()` 新增第 6 个，`backend/app/routers/admin.py` 必须透传 `expires_at=payload.expire_date`（**漏传会让「指定到期日期」静默退化成永久有效**）。前端手动新增与批量生成两个弹窗的有效期行都是 `.form-row.expiry-row` + `.expiry-control` 内的 `.expiry-mode` 分段按钮二选一渲染（`v-if/v-else`，不会同时出现两个输入框），新增样式追加在 `frontend/src/assets/styles.css` 并**按类名作用域化、不新增全局规则**。专项用例：`python tests/redemption_per_user_test.py` 里的 `test_expire_date_mode()` / `test_expire_date_schema()`。
- 修改打印时，注意打印方式完全按运行平台分流（Windows 走系统队列/SumatraPDF，Linux/macOS 走 CUPS 命令），已没有 `print_mode` 配置项，mock 模拟模式也已移除。自动支付回调可能触发真实打印。
- 修改彩色打印 / 自动双面能力时，要同步 `database.py` 的 `SCHEMA` 与 `SCHEMA_MIGRATIONS`（`printers.is_support_color`/`is_support_auto_duplex`、`orders.use_color`）、`cups_printer.py` 的 `_save_metadata()` 与打印机输出对象、公开接口 `/api/print-options`、`orders.py` 的能力兜底校验、`print_pdf(use_color=...)` 与 `rasterize_pdf_for_print(darken=...)`，以及首页条件渲染和后台编辑弹窗。
- 修改上传或转换时，要保留文件头校验、大小限制、页数限制、覆盖率检测和失败文件入库。
- 修改后台概览的「每日数据统计」时：分日口径集中在 `backend/app/services/stats.py`。库里时间戳**统一是 UTC 文本**（`orders.created_at` 由 SQLite `CURRENT_TIMESTAMP` 生成 `YYYY-MM-DD HH:MM:SS`，而 `paid_at`/`printed_at` 由 `datetime.utcnow().isoformat()` 生成 `YYYY-MM-DDTHH:MM:SS.ffffff`，**同一张表两种格式并存**），所以 SQL 里先用 `datetime(created_at)` 归一化、按 `strftime('%Y-%m-%d %H', ...)` 聚成 UTC 小时桶，再由 Python 用无参 `astimezone()` 折算本地日期——**不要**直接对字符串做 `substr(created_at, 1, 10)` 分日（那是 UTC 日期，东八区下会把本地 0-8 点的订单算到前一天）。窗口边界用「本地日 00:00 → UTC 半开区间」反算，不要在 SQL 里写死时区偏移。接口是 `GET /api/admin/daily-stats`（`days` 1-90、默认 7），路由函数名与 `stats.py` 的 `daily_stats` 同名，所以**必须用别名引入**（`from ..services.stats import daily_stats as build_daily_stats`），否则路由会调用自己。前端图表在 `frontend/src/components/DailyStatsCard.vue`，调整样式要同步 `frontend/src/assets/styles.css` 的 `.daily-stats-*` 段；颜色一律走 `var(--cp-*)`，不要为了「图表好看」写死 hex。专项回归测试：`python tests/daily_stats_test.py`（Windows 本地可跑，不需 pycups/CUPS）。
- 修改前端 API 路径时，注意生产环境前端由后端直接托管，不需要 Nginx 反代。
- 修改主题（亮/暗）时：颜色必须走 `frontend/src/assets/theme.css` 的 `var(--cp-*)`，不要在 `styles.css` 里写死 hex/rgba；新增变量要在**四个 palette 块**（PC 亮、PC 暗、`@media (max-width: 767px)` 下的移动亮、移动暗）里同时补齐，缺一个就会在对应场景下取到空值。手机端判定宽度必须与 `stores/theme.js` 的 `MOBILE_QUERY = '(max-width: 767px)'` 一致。PC 与移动端是两套独立配色，不要用一套变量同时控制两端。
- `frontend/dist/`、`frontend/node_modules/`、`release/` 和同步冲突副本正常编码不要手动编辑；Docker 构建会在镜像内重新生成前端产物。
- 仓库可能出现 NAS 同步冲突副本。除非明确处理同步冲突，否则不要修改这些副本文件。

## 11. 当前实现与原 PRD 的差异

- 独立文档预览页目前未实现；预览嵌在首页和后台订单详情。
- 登录和注册不是两个路由，而是在 `/login` 的同一个视图中切换，并都要求验证码。
- 用户自助充值已经实现，但不是独立充值页面，而是个人中心里的充值模块。
- 后台配置、订单、用户、支付、打印机都集中在 `/admin` 单页 tab 中。
- 当前 Office 转 PDF 依赖系统 LibreOffice，不使用 `python-docx` 或 `python-pptx` 做转换。
- 当前 token 是项目自定义 HMAC token，不是 JWT 库；同时存在 session cookie 作为后备鉴权。
- 当前支付返回的是后端自动提交表单 URL，不是直接二维码图片 URL。
- 后台概览的「每日数据统计」图表是**手写内联 SVG**（`frontend/src/components/DailyStatsCard.vue`），项目没有引入 ECharts/Recharts 或任何其它图表库，`package.json`/`pnpm-lock.yaml` 也未新增依赖；原因是前端栈是 Vue 3（Recharts 只支持 React），且 Docker 构建走 `pnpm install --frozen-lockfile`，新增依赖必须同时更新锁文件。
- 当前打印完成状态依赖 CUPS 队列确认；Windows 下无法可靠自动确认完成（mock 模拟模式已移除）。
- 当前部署方式是 Docker Compose 单容器：FastAPI 直接托管前端静态文件，没有独立 Nginx 前端容器；SQLite、上传缓存、备份、日志和 `config.json` 都在 `./config` 绑定挂载目录里。
- 彩色打印与自动双面只在 Linux/macOS 的 CUPS 链路真正生效（`lp -o print-color-mode=color|monochrome`）；Windows 的 SumatraPDF/`PrintTo` 分支只处理打印机与份数，`double_sided` 与 `use_color` 都不生效（与改动前一致）。自动双面也不是「整单双面」，而是按份文档设置。

## 12. 快速理解代码链路

访客或注册用户打印链路：

```text
HomeView.vue
  -> GET /api/promotions
  -> GET /api/print-options           # 默认打印机的彩色/自动双面能力，决定首页是否展示对应选项
  -> POST /api/upload
    -> save_upload()
    -> convert_to_pdf()
    -> page_count()
    -> calculate_black_coverage_details()
    -> files 表 + alerts 表
  -> POST /api/price
  -> POST /api/payment/create
    -> calculate_files_price_detail()
    -> orders/order_items/payments 表
  -> GET /api/payment/submit/{order_id}
    -> 易支付网关
  -> GET|POST /api/payment/notify
    -> complete_epay_payment()
    -> dispatch_order_print()
    -> print_pdf()
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
    -> dispatch_order_print()
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

- 登录、验证码、会话、权限：`backend/app/routers/auth.py`、`backend/app/services/auth_session.py`、`backend/app/routers/deps.py`、`backend/app/utils/security.py`、`frontend/src/stores/auth.js`、`frontend/src/views/AuthView.vue`。
- 上传、转换、预览、安全检测：`backend/app/routers/files.py`、`backend/app/services/files.py`、`backend/app/services/safety.py`、`frontend/src/views/HomeView.vue`。
- 计价、覆盖率阶梯、促销：`backend/app/services/pricing.py`、`backend/app/routers/public.py`、`backend/app/routers/admin.py`、`frontend/src/views/HomeView.vue`、`frontend/src/views/AdminView.vue`。
- 打印订单、支付、易支付回调：`backend/app/routers/orders.py`、`backend/app/services/epay.py`、`backend/app/services/printer.py`、`frontend/src/views/PaymentView.vue`。
- 用户资料、余额充值、个人中心订单：`backend/app/routers/user.py`、`backend/app/services/epay.py`、`frontend/src/views/DashboardView.vue`。
- 兑换码（后台生成 + 用户兑换，含「每个用户最大兑换次数」`per_user_max_times`）：`backend/app/services/redemption.py`（`redeem()` 双重校验 + `count_user_redemptions()`/`per_user_max_times_of()`/`has_redeemed()`）、`backend/app/routers/admin.py`（`/redemptions`，`create_code()` 必须透传第 6 个位置参数）、`backend/app/routers/user.py`（`POST /api/user/redeem`）、`backend/app/models/schemas.py`（`AdminRedemptionCreate`/`RedeemRequest`）、`backend/app/database.py`（`SCHEMA` + `SCHEMA_MIGRATIONS["redemption_codes"]["per_user_max_times"]` + `migrate_redemption_per_user_limit()`）、`frontend/src/views/AdminView.vue`、`frontend/src/views/DashboardView.vue`、`backend/tests/redemption_per_user_test.py`。
- 打印机管理和真实打印：`backend/app/services/printer.py`、`backend/app/services/print_monitor.py`、`backend/app/routers/admin.py`、`scripts/test_printer.py`。
- 彩色打印、自动双面能力（前台条件渲染 + 后端兜底校验）：`backend/app/routers/public.py`（`GET /api/print-options`）、`backend/app/services/cups_printer.py`（`_save_metadata()` 保存两项能力）、`backend/app/routers/orders.py`（能力兜底 400）、`backend/app/services/printer.py`（`use_color` → `lp -o print-color-mode=`）、`backend/app/services/pdf_postprocess.py`（`rasterize_pdf_for_print(darken=...)`）、`frontend/src/views/HomeView.vue`、`frontend/src/views/AdminView.vue`。
- 数据表、默认设置、旧库迁移：`backend/app/database.py`，同时检查后台设置表单和 `backend/tests/smoke_test.py`。
- 后台概览「每日数据统计」（按本地时区分日聚合 + 手写 SVG 图表）：`backend/app/services/stats.py`、`backend/app/routers/admin.py`（`GET /api/admin/daily-stats`，别名引入 `daily_stats` 为 `build_daily_stats`）、`frontend/src/components/DailyStatsCard.vue`、`frontend/src/views/AdminView.vue`（概览 tab）、`frontend/src/assets/styles.css`（`.daily-stats-*`）、`backend/tests/daily_stats_test.py`。
- 亮/暗主题（PC 与移动端两套独立配色）：`frontend/src/assets/theme.css`（四套 palette）、`frontend/src/stores/theme.js`（状态/记忆/跟随系统/视口判定）、`frontend/src/assets/styles.css`（`var(--cp-*)` 与深色专项段）、`frontend/src/App.vue`（`.theme-toggle`）、`frontend/index.html`（防闪烁内联脚本）。规范见 `doc/UI_ADAPTATION.md` 第 5.5 节。

文档或代码变更后的最低验证建议：

- 只改文档：回读对应章节并检查路径、接口和环境变量名称是否仍与代码一致。
- 改后端业务：优先运行 `backend/tests/smoke_test.py`，并使用临时数据库和临时上传目录。
- 改前端交互：运行 `npm --prefix frontend run build`，涉及页面布局时再启动前端做浏览器检查。
- 改真实打印：先在受控环境（测试用 CUPS 队列或备用打印机）跑通下单和后台测试页，确认无误后再接入生产打印机（`cups` 或 `system`）。

## 14. 版本控制与仓库发布

- 远端仓库：`https://github.com/BakInt/PrintHub`（public），默认分支 `main`，本地 `origin` 指向它。首次发布提交为 `7d96932e4cc7238997763d8af3a632f62f336170`（`chore: initial commit - PrintHub 云打印自助系统`，66 个文件），采用强制推送覆盖了远端原有的占位 `LICENSE`/`README.md`，两条历史线无共同祖先。
- 纳入版本控制的是源码/配置/文档共 66 个文件；`.gitignore` 排除 `frontend/node_modules/`、`frontend/dist/`、`config/`、`storage/`、`logs/`、`backups/`、`*.db`、`__pycache__/`、`.venv/`、`release/`、`.idea/`、`.vscode/` 与 NAS 冲突副本。空目录 `preview/` 不被 git 跟踪，不会出现在远端。
- 提交身份是仓库级配置：`user.name=BakInt`、`user.email=BakInt@users.noreply.github.com`（未改全局/系统配置）。推送凭据由 Git Credential Manager 提供，Windows 凭据管理器里已有 `git:https://github.com`（用户 `BakInt`）条目，因此 `git push` 无需再交互登录。
- 更新代码后的发布流程：`git add -A` → `git commit -m "..."` → `git push origin main`。若远端历史被本地覆盖过（如上），推送需带 `--force`；日常增量提交正常推送即可。
- 不要在仓库里提交 `config/`、数据库、上传文件或 `.env*`；这些都已由 `.gitignore` 排除。若新增其它运行时产物目录，同步补 `.gitignore` 规则。