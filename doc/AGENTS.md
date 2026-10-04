# PrintHub（云打印系统）- 代码协作说明

这份文件面向后续维护本仓库的编码代理和开发者。它描述当前代码的真实结构、业务逻辑、运行方式和修改注意事项。产品愿景和需求边界可参考 `doc/PRD.md`；本文件以现有代码为准。

## 1. 项目用途

这是一个基于 FastAPI + Vue 3 的在线云打印系统。用户可以上传 PDF、Office 文档或图片，后端保存原文件并转换为 PDF，计算页数和黑色覆盖率，通过安全检测后创建打印订单。订单支持支付宝/微信易支付、注册用户余额支付；注册用户还可以在线充值余额。支付成功或余额扣费成功后，系统会把 PDF 下发到打印服务。

后台提供运营概览、异常告警、订单详情、未支付订单清理、文件缓存清理、用户管理、系统价格/阈值/促销设置、易支付配置、支付自测和打印机管理。

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
│   │   ├── services/            # 文件、支付、计价、安全检测、认证会话、打印服务
│   │   └── utils/security.py    # bcrypt 密码哈希和自定义 HMAC token
│   ├── tests/smoke_test.py      # 后端冒烟测试（import app.main 需要 pycups，适合容器内跑）
│   ├── tests/config_test.py     # config.json 生成/热加载/管理员重置测试（不依赖 CUPS，本地可跑）
│   ├── tests/queue_feature_test.py
│   ├── requirements.txt
│   └── run.py                   # 本地开发入口
├── frontend/
│   ├── src/
│   │   ├── App.vue
│   │   ├── api/client.js        # fetch 封装、token 注入、CSRF token 自动携带
│   │   ├── router/index.js
│   │   ├── stores/auth.js
│   │   ├── views/               # 首页、认证、支付、个人中心、后台
│   │   └── assets/styles.css
│   ├── package.json
│   ├── pnpm-lock.yaml           # 包管理器是 pnpm（Dockerfile 用 pnpm@10.15.0 --frozen-lockfile）
│   └── nginx.conf               # 旧的独立 Nginx 配置，仅备用（生产由 FastAPI 托管前端）
├── scripts/test_printer.py      # 命令行测试样张脚本
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
2. 注册 CORS、限流、TrustedHost 和安全响应头中间件。
3. 启动时先调用 `_warn_data_outside_config_root()`（容器里若数据库/上传等路径跑到配置目录之外会打印警告，提示重建容器会丢数据），再调用 `validate_production_config(settings)`、`init_db()`、`start_print_status_monitor()`、`start_auto_backup_scheduler()`。
4. 注册路由：`public`、`auth`、`files`、`orders`、`admin`、`admin.setup_router`、`user`。
5. 在所有路由之后注册前端静态文件服务（`/assets`、`/static`）和 catch-all 路由。

`backend/app/database.py` 负责：

- 创建 SQLite 表：`users`、`files`、`orders`、`order_items`、`payments`、`settings`、`alerts`、`printers`、`auth_sessions`、`login_failures`。
- 通过 `SCHEMA_MIGRATIONS` 给旧库补列，新增表通过 `CREATE TABLE IF NOT EXISTS` 创建。
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
- 光栅化时加深偏灰笔画（解决「公式打印出来颜色很淡」，`rasterize_pdf_for_print()` 调用 `_darken_faint_content()`）：老式 OLE/WMF/EMF 公式预览图被 LibreOffice 光栅化后，笔画常呈中等灰度而非纯黑（样本试卷 300dpi 光栅化实测：公式笔画灰度铺满 80-180 区间，约占全部深色像素的 1/3），而正文是纯黑。打印机把中灰如实打成浅灰，于是「正文正常、公式颜色很淡」。因此在整页光栅化重组 PDF 前，对每页套一条分段灰度查找表（LUT）：亮于 `white_keep=235` 的像素判为背景/留白保持不变（避免整页发灰），暗于 `black_at=150` 的像素（正文 + 大部分公式笔画）直接压到纯黑（笔画变实），两者之间平滑过渡（保留抗锯齿边缘、避免笔画发糊或加粗）。默认参数经样本试卷实测标定：公式由中灰压至接近纯黑、与正文一致，白底洁净。仅加深不改版式，对纯文本页几乎无副作用（正文本就 < `black_at`，映射后仍是黑）；只作用于打印副本。验证：样本试卷经 `convert_to_pdf`→`rasterize_pdf_for_print` 后，首页化学式（`CH₃COOH`/`NaOH`/`V₁ mL`/`c₁`/`Ka` 平衡常数/离子式等）目视由明显偏灰加深为接近纯黑、清晰完整，白底无发灰；`backend/tests/smoke_test.py` 新增 `_darken_faint_content` LUT 单元测试（中灰压黑、纯黑保持、接近白不变）。

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
2. 解析按份双面：`file_settings` 中指定的文件用其独立设置，其余回退全局 `double_sided`；对任一被请求双面但页数 < 2 的文档返回 400。
3. 调用 `calculate_files_price_detail()` 逐份汇总价格；每份文档的生效双面值写入 `order_items.is_double_sided`，`orders.is_double_sided` 作为「是否含双面文档」的聚合标识。
4. 联系人姓名和手机号必填。登录用户可从 `users.real_name`、`users.phone` 自动补齐；手机号要求中国大陆 11 位格式。
5. 如果是余额支付：
   - 必须登录。
   - 校验支付后余额不能低于 `min_balance`。
   - 创建订单和支付记录后扣减余额，订单置为 `paid`。
   - 立即调用 `dispatch_order_print()`。
6. 如果是 `alipay` 或 `wxpay`：
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

`printer.print_pdf()` 不再接收 `print_mode` 参数，签名为 `print_pdf(pdf_path, copies, double_sided, printer_name=None, default_printer=None)`；`print_jobs_active(job_ids)` 也不再接收打印模式。

`dispatch_order_print()` 会根据订单的 `printer_name`、settings 中的 `default_printer` 和份数，并逐份读取 `order_items.is_double_sided` 作为该文件的单双面参数调用 `print_pdf()`。成功后订单状态更新为 `printing`，失败则为 `print_failed` 并写入 `print_error`。

`print_pdf()`（CUPS 路径）在用 `lp` 提交前会调用 `rasterize_pdf_for_print()`（见 `backend/app/services/pdf_postprocess.py`），用 poppler `pdftoppm` 把待打印 PDF 每页光栅化成 300dpi 不透明位图并重组为「纯图像 PDF」再提交。这样远端 CUPS/打印机的 RIP 只需绘制不透明图片，彻底规避老式 OLE 公式/WMF/EMF/透明图元在远端 RIP 上被整块丢弃的「上传打印后化学式消失」问题（详见 6.1）。它仅作用于打印副本、不改动入库/预览的原始 PDF，页数页序不变，光栅化失败会安全降级为直接打印原 PDF；打印任务提交后本地临时图像 PDF 会被删除。光栅化每页还会经 `_darken_faint_content()` 套分段灰度 LUT，把老式公式预览图的中灰笔画压到纯黑、保护白底不发灰，解决「公式打印出来颜色很淡」（详见 6.1）。Windows 走 SumatraPDF/`PrintTo`，本身就是本地整页光栅化，不额外处理。

`start_print_status_monitor()` 会启动后台线程，按 `config.json` 的 `print_status_check_interval_seconds`（默认 30）检查 `status='printing'` 的订单；该值每轮重新读取，改完配置文件重启或等下一轮即生效。CUPS 能确认任务不在未完成队列时订单置为 `completed`；无法确认且超过 `print_confirm_timeout_seconds`（默认 600 秒）会置为 `print_failed`。Windows 下无法可靠确认队列完成，通常保持人工/后台状态处理。

本系统已移除 mock 模拟模式，所有打印都是真实打印。涉及打印的改动务必先在受控环境（如指向测试用 CUPS 队列或备用打印机）验证，再接入生产打印机。支付回调可能触发真实打印，联调真实支付前要确认 CUPS 地址和默认打印机。

## 7. API 路由概览

公开接口：

- `GET /api/health`：健康检查。
- `GET /api/ready`：数据库就绪检查。
- `GET /api/promotions`：前台展示当前促销。
- `GET /api/limits`：前台读取生效的上传限制（`max_file_size_mb`、`max_pages`）；优先取后台设置，缺省回退环境变量默认值。首页用它渲染上传提示文案。
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

后台接口均在 `/api/admin` 下，需要管理员 token 或 session，包含：

- `/dashboard`、`/orders`、`/orders/{id}/detail`、`/orders/{id}/mark-complete`、删除单个订单、删除未支付订单、批量删除未支付订单。
- `/file-cache/cleanup`：按时段统计或清理上传缓存，可选择是否包含已关联订单文件。
- `/users`：创建、编辑、启停、删除用户，余额增减或设置；保护最后一个管理员和当前管理员。
- `/settings`：系统价格、促销、阈值、文件大小/页数上限和默认打印机。接口保存后会返回 `notices`，提示哪些键（`cups_*`/`epay_*`）的实际值来自建库时写入的 `config.json` 快照、之后再改 `config.json` 不会覆盖后台设置（库优先）；**后台页面不再展示这些 notices**（否则成功保存也会出现红色提示），保存成功只在页面顶部显示绿色「保存成功」。
- `/payment-settings`、`/payment-test`：易支付配置、配置校验、测试单查询和模拟成功。
- 打印机管理（实现于 `backend/app/services/cups_printer.py`）：`/printer-system`（运行环境与 CUPS 连通性诊断）、`/printers`（枚举真实队列）、`/printer-drivers` 与 `/printer-drivers/ppd`（驱动列表与上传 PPD）、`/printer-info`、`/printer-uri/probe`、`/printers/{name}`（查询/编辑/删除）、`/printers/{name}/default`、`/printers/default/clear`、`/printers/{name}/enabled`、`/printers/{name}/test-page`、`/printers/{name}/test-result`、`/printers/{name}/jobs`、`/cups/logs`、`/cups/queues`、`/cups/diagnostics`。
- `/alerts/{id}/handle`：处理异常告警。

## 8. 前端结构和页面

`frontend/src/App.vue` 是全局壳，顶部导航根据 `auth.user` 显示个人中心、后台和退出按钮。应用启动时调用 `auth.loadMe()`。

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
- 余额支付按钮只对登录用户可用。
- 非余额支付创建订单后，跳到后端返回的 `/api/payment/submit/{order_id}`。
- 余额支付创建成功后进入 `/payment/{order_id}` 查看状态。

`DashboardView.vue` 的关键行为：

- 用户可维护真实姓名和 11 位手机号；首页下单可自动使用这些联系人信息。
- 支持支付宝/微信充值，成功创建充值单后跳转到后端支付提交页。
- 从 `recharge_order` query 返回时会刷新用户信息和订单列表。

`AdminView.vue` 是目前最大的前端文件，集中实现后台所有 tab。修改后台时优先复用现有 `runAction()`、`loadTab()`、`showFeedback()` 模式，避免引入不一致的状态管理方式。

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
- 修改计价时，要同步前台 `/api/price`、`/api/promotions`、后台配置表单、订单保存字段和烟测断言。
- 修改打印时，注意打印方式完全按运行平台分流（Windows 走系统队列/SumatraPDF，Linux/macOS 走 CUPS 命令），已没有 `print_mode` 配置项，mock 模拟模式也已移除。自动支付回调可能触发真实打印。
- 修改上传或转换时，要保留文件头校验、大小限制、页数限制、覆盖率检测和失败文件入库。
- 修改前端 API 路径时，注意生产环境前端由后端直接托管，不需要 Nginx 反代。
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
- 当前打印完成状态依赖 CUPS 队列确认；Windows 下无法可靠自动确认完成（mock 模拟模式已移除）。
- 当前部署方式是 Docker Compose 单容器：FastAPI 直接托管前端静态文件，没有独立 Nginx 前端容器；SQLite、上传缓存、备份、日志和 `config.json` 都在 `./config` 绑定挂载目录里。

## 12. 快速理解代码链路

访客或注册用户打印链路：

```text
HomeView.vue
  -> GET /api/promotions
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

管理员处理异常链路：

```text
文件覆盖率超阈值
  -> alerts 表新增 open 告警
AdminView.vue 概览 tab
  -> GET /api/admin/dashboard
  -> POST /api/admin/alerts/{alert_id}/handle
```

打印机管理与测试链路：

```text
AdminView.vue 打印机 tab
  -> GET  /api/admin/printer-system        # 运行环境与 CUPS 连通性诊断
  -> GET  /api/admin/printers              # cups_printer.list_printers() 枚举真实队列
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
- 打印机管理和真实打印：`backend/app/services/printer.py`、`backend/app/services/print_monitor.py`、`backend/app/routers/admin.py`、`scripts/test_printer.py`。
- 数据表、默认设置、旧库迁移：`backend/app/database.py`，同时检查后台设置表单和 `backend/tests/smoke_test.py`。

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