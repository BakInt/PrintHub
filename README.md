# PrintHub

An open-source cloud printing solution for upload, pricing, payment and print. / ✨ 一个开源云打印方案，上传·计价·支付·打印，一站式搞定 🖨️

[![Docker](https://img.shields.io/badge/docker-baklnt%2Fprinthub-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/baklnt/printhub)
[![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)

## 项目简介 / Overview

PrintHub 是一套可自托管的在线云打印系统。用户上传 PDF、Office 文档或图片，后端自动转成 PDF、统计页数与黑色覆盖率并做安全检测，随后在线计价、支付（支付宝 / 微信 / 余额），支付成功后自动把文件下发到打印机——用一个 Docker 容器替代「把文件拷给打印店」的全流程。

## 主要特性 / Key Features

- **多格式上传 / Multi-format upload** — PDF、Office（doc/docx/xls/xlsx/ppt/pptx）、图片（png/jpg/jpeg），由 LibreOffice + Poppler 统一转为 PDF。
- **打印质量修复 / Print-quality fixes** — 内置 `/SMask` 软遮罩拍平、打印前 300dpi 整页光栅化、偏灰笔画压黑，解决「公式/化学式预览正常但打印后消失或发灰」。
- **页数与覆盖率计价 / Pricing by pages or coverage** — `standard`（按页数 + 单/双面）与 `coverage_tiered`（按黑色覆盖率分档）两种模式。
- **促销与折扣 / Promotions & discounts** — 阶梯折扣（默认 10 张 95 折 / 100 张 90 折 / 200 张 80 折）+ 每日限时特价，多方案自动取最低价。
- **在线支付 / Online payment** — 支付宝与微信（易支付网关），注册用户可用余额支付并在线充值；回调带签名校验、幂等处理与防重复入账。
- **安全检测 / Safety detection** — 按黑色覆盖率阈值自动拦截高风险文件下单，并在后台生成告警。
- **自动双面（按份独立）/ Per-file duplex** — 批量上传时可对每份文档单独选择单面或双面，不跨文档合并。
- **真实打印 / Real printing** — Linux/macOS 走 CUPS 命令，Windows 走系统打印队列 + SumatraPDF；无 mock 模拟模式。
- **完整后台 / Full admin console** — 运营概览与告警、订单管理、未支付订单与上传缓存清理、用户与余额管理、价格/促销/阈值/上传限制设置、易支付配置与支付自测、CUPS 打印机管理与测试页。
- **单容器部署 / Single-container deployment** — FastAPI 同时托管 API 与前端静态文件，无需独立 Nginx 容器；唯一持久化目录为 `./config`。

## 环境依赖 / Requirements

### 部署 / Deployment（推荐 recommended）

| 依赖 / Dependency            | 版本 / Version                                                   |
| ---------------------------- | ---------------------------------------------------------------- |
| Docker Engine                | 20.10+                                                           |
| Docker Compose               | v2（`docker compose`）                                           |
| 打印机服务 / Printer service | 可选。Linux/macOS 需可访问的 CUPS 服务；Windows 需已安装打印队列 |

镜像内已内置 LibreOffice、Poppler、`pdftoppm`、CUPS client、`libwmf-bin`、中文字体与数学符号字体，**宿主机无需安装任何转换工具**。
The image already bundles LibreOffice, Poppler, `pdftoppm`, CUPS client, `libwmf-bin`, CJK and math fonts — **no conversion tooling is required on the host**.

### 本地开发 / Local development

| 依赖 / Dependency       | 版本 / Version                                                                                                         |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Python                  | 3.12（后端 / backend）                                                                                                 |
| Node.js                 | 22.18+（前端 / frontend）                                                                                              |
| pnpm                    | 10.15.0                                                                                                                |
| 系统程序 / System tools | LibreOffice、Poppler（`pdftoppm` / `pdfinfo`）、`libcups2-dev`（`pycups` 编译所需）；Windows 本地跑配置测试可不装 CUPS |

后端依赖（`backend/requirements.txt`）：FastAPI 0.116.1、uvicorn[standard] 0.35.0、python-multipart 0.0.20、pydantic-settings 2.10.1、PyPDF2 3.0.1、pdf2image 1.17.0、Pillow 11.3.0、httpx 0.28.1、bcrypt 5.0.0、pycups 2.0.4。

前端 / Frontend：Vue 3、Vite、Vue Router、Pinia、lucide-vue-next。

## 快速安装 & 上手 / Quick Start

### 方式一：Docker 镜像部署（推荐） / Option 1 — Docker Image Deployment (Recommended)

镜像发布在 Docker Hub：[`baklnt/printhub`](https://hub.docker.com/r/baklnt/printhub)。**无需克隆源码、无需本地构建**，拉取即用。

```bash
# 1. 创建部署目录
mkdir -p printhub/config && cd printhub

# 2. 把下方官方 docker-compose.yml 保存为当前目录的 docker-compose.yml
#    （该文件同时也是仓库根目录的官方 compose 文件，可直接复制使用）

# 3. 拉取官方镜像并启动
docker compose pull
docker compose up -d

# 4. 查看启动状态与日志
docker compose ps
docker compose logs -f cloud-print

# 5. 查看首次启动自动生成的配置（含随机 app_secret 与管理员账号）
cat config/config.json
```

官方 `docker-compose.yml`（保存为工作目录下的同名文件后即可 `docker compose up -d`）：

```yaml
services:
  cloud-print:
    image: baklnt/printhub:latest
    container_name: cloud-print
    restart: unless-stopped
    ports:
      - '5978:8000'
    volumes:
      # 唯一持久化挂载点：数据库、上传件、备份、日志、CUPS 驱动和 config.json 全在这里
      - ./config:/app/config
    environment:
      - TZ=Asia/Shanghai
      # 允许任意 IP/域名访问（局域网内其它机器用本机 IP 访问必需），
      # 否则 TrustedHostMiddleware 会返回 "Invalid host header"
      - TRUSTED_HOSTS=${TRUSTED_HOSTS:-*}
```

也可以完全不用 Compose，直接用 `docker run` 启动官方镜像：

```bash
docker run -d \
  --name cloud-print \
  --restart unless-stopped \
  -p 5978:8000 \
  -e TZ=Asia/Shanghai \
  -e TRUSTED_HOSTS='*' \
  -v "$PWD/config:/app/config" \
  baklnt/printhub:v1.4
```

启动后访问 `http://<服务器IP>:5978`，用 `config.json` 里的管理员账号登录后台：

```text
用户名 / Username：admin
密码  / Password：admin123456      # 首次登录后请立即修改 / change it right after first login
```

升级到新版本：

```bash
docker compose pull && docker compose up -d     # 数据都在 ./config，不会丢失
```

### 方式二：从源码构建

```bash
# 1. 克隆仓库（<your-repo-url> 替换为实际仓库地址）
git clone <your-repo-url> printhub
cd printhub

# 2. 构建并启动（必须在 docker-compose.yml 所在目录执行）
docker compose up -d --build

# 3. 查看状态与配置
docker compose ps
cat config/config.json
```

### 方式三：本地开发

```bash
# 后端 / Backend
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py                        # 首次运行在 backend/ 生成 config.json 与数据目录

# 前端 / Frontend（另开一个终端 / in another terminal）
cd frontend
pnpm install
pnpm run dev                         # 默认 http://localhost:5173
```

### 测试 / Tests

```bash
cd backend

# 配置生成 / 热加载 / 管理员重置测试：不依赖 CUPS，本地可跑
python tests/config_test.py

# 后端冒烟测试：需要 pycups/CUPS 环境，建议在容器内跑
CONFIG_ROOT=/tmp/cloud_print_test .venv/bin/python tests/smoke_test.py
```

## 使用示例

### 1. 用户打印流程 / End-user printing flow

1. 打开首页 `http://<服务器IP>:5978`，拖入一个或多个文档；
2. 等待上传完成——后端自动转 PDF、统计页数与黑色覆盖率并做安全检测，不安全文件会被标红且不能下单；
3. 用内置预览确认排版，按份勾选「双面」；
4. 填写联系人姓名与 11 位手机号，选择份数；
5. 点击计价查看金额（阶梯折扣、限时特价会自动生效）；
6. 选择支付宝 / 微信支付，或登录后使用余额支付；
7. 支付成功后系统自动把 PDF 下发到打印机，可在订单页查看打印状态。

<sub>Upload documents → auto-convert, count pages and coverage, safety-check → preview and choose per-file duplex → price → pay (Alipay / WeChat / balance) → automatic dispatch to the printer → track status on the order page.</sub>

### 2. 后台配置打印机（首次部署必做）/ Configure a printer (first-run must-do)

进入「后台 → 打印机」：

1. 在「系统设置 / 支付设置」中填入 CUPS 地址（默认示例 `192.168.1.100:631`，格式 `host:port`）；
2. 打开「打印机」tab 的连通性诊断，确认 CUPS 可访问；
3. 从真实队列中选一台设为默认打印机；
4. 点击「打印测试页」验证链路，再上线真实订单。

### 3. 后台配置支付 / Configure payment

进入「后台 → 支付设置」，填写网关地址、`pid`、`key` 与公网地址（`public_base_url`）。保存后可用「支付自测」创建 `order_type='test'` 测试单，或调用 `/simulate-success` 构造签名成功回调做本地自测；测试单不关联文件、不触发打印。

### 4. 命令行工具 / CLI tools

```bash
# 打印样张
python scripts/test_printer.py

# 诊断 docx 中的老式 OLE 公式风险等级
python scripts/fix_docx_formula.py --check 你的文档.docx

# 修复：把公式的 WMF/EMF 预览图转成 PNG 并降级为 DrawingML 内联图片
python scripts/fix_docx_formula.py 你的文档.docx
```

> 正常上传无需先跑修复脚本：系统会在转换后自动拍平 `/SMask`，并在打印前整页光栅化。

### 5. API 速查 / API quick reference

| 方法与路径 / Method & path                                                   | 说明 / Description                                           |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `GET /api/health` · `GET /api/ready`                                         | 健康检查 / 数据库就绪                                        |
| `POST /api/upload`                                                           | 上传、转换、检测并入库                                       |
| `GET /api/files/{file_id}/preview`                                           | PDF inline 预览                                              |
| `POST /api/price` · `GET /api/promotions` · `GET /api/limits`                | 计价、促销、生效上传限制                                     |
| `POST /api/payment/create`                                                   | 创建打印订单                                                 |
| `GET /api/payment/submit/{order_id}`                                         | 易支付自动提交页                                             |
| `GET\|POST /api/payment/notify`                                              | 易支付异步回调                                               |
| `GET /api/orders/{order_id}`                                                 | 查询订单并刷新打印状态                                       |
| `POST /api/auth/register` · `/login` · `/logout` · `GET /api/auth/me`        | 认证与会话                                                   |
| `POST /api/user/recharge` · `PUT /api/user/profile` · `GET /api/user/orders` | 用户中心                                                     |
| `GET /api/admin/*`                                                           | 后台（需管理员）：概览、订单、用户、设置、支付、打印机、告警 |

## 配置说明 / Configuration

本项目**不使用 `.env` 文件**，只有两处配置来源。

### 1. `config/config.json`（部署级配置 / deployment-level）

首次启动自动生成（含随机 `app_secret`），之后只补齐缺失键，**绝不覆盖已有值**。优先级：**环境变量 > `config.json` > 代码内建默认值**。相对路径按配置目录解析，整个 `config` 目录可整体搬家。

| 键 / Key                                                                      | 说明 / Description                                                          |
| ----------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `environment`                                                                 | `development` / `production`；`production` 启动时执行严格校验               |
| `app_secret`                                                                  | 随机生成的签名密钥，勿泄露                                                  |
| `database_path` / `upload_dir` / `backup_dir` / `log_dir` / `cups_driver_dir` | 各数据目录位置                                                              |
| `trusted_hosts`                                                               | 允许的 Host 列表，默认 `*`（便于局域网 IP 访问），公网建议收紧              |
| `cors_origins`                                                                | 允许的跨域来源                                                              |
| `session_cookie_secure`                                                       | HTTPS 时设 `true`；HTTP 时保持 `false`，否则登录失效                        |
| `admin_username` / `admin_password`                                           | 初始管理员账号，默认 `admin` / `admin123456`                                |
| `reset_admin_password`                                                        | 置 `true` 并重启即把管理员密码重置为 `admin_password`，之后自动写回 `false` |
| `print_status_check_interval_seconds`                                         | 打印状态检查间隔，默认 30                                                   |
| `print_confirm_timeout_seconds`                                               | 打印确认超时，默认 600 秒                                                   |
| `printer_probe_timeout_seconds` / `cups_job_timeout_seconds`                  | 打印机探测与 CUPS 任务超时                                                  |
| `sumatra_pdf_path` / `windows_pdf_print_command`                              | 仅 Windows：SumatraPDF 或自定义打印命令，未配置回退系统 `PrintTo`           |

**忘记管理员密码**：把 `reset_admin_password` 改为 `true`，重启容器即可。

### 2. 后台页面（业务配置 / business settings，存在 SQLite `settings` 表）

价格、促销、覆盖率阈值、上传大小与页数上限、易支付商户信息、CUPS 地址、默认打印机都在后台「系统设置 / 支付设置 / 打印机」中修改，**以数据库为准**。其中 `cups_*` / `epay_*` 只在**首次建库**时从 `config.json` 播种，之后改 `config.json` 不会覆盖后台已保存的值。

### 3. 环境变量 / Environment variables

仅用于临时覆盖，日常请改 `config.json`：

| 变量 / Variable                                            | 说明 / Description                         |
| ---------------------------------------------------------- | ------------------------------------------ |
| `CONFIG_ROOT`                                              | 配置目录，容器内默认 `/app/config`         |
| `CONFIG_CONFIG_FILE`                                       | 指定其它配置文件路径                       |
| `TRUSTED_HOSTS`                                            | 覆盖 `trusted_hosts`（compose 中默认 `*`） |
| `TZ`                                                       | 时区，compose 中为 `Asia/Shanghai`         |
| `MAX_FILE_SIZE_MB` / `MAX_PAGES` / `SAFETY_COVERAGE_LIMIT` | 只在数据库设置缺失或非法时作为兜底默认值   |

### 数据持久化与备份 / Data & backup

唯一持久化目录是宿主机 `./config`（挂载到容器 `/app/config`）：

| 路径 / Path                 | 内容 / Content                               |
| --------------------------- | -------------------------------------------- |
| `config/config.json`        | 唯一部署配置文件                             |
| `config/cloud_print.db`     | SQLite：用户、订单、文件、支付记录、业务设置 |
| `config/uploads/<file_id>/` | 上传原文件与转换后的 PDF                     |
| `config/backups/`           | 后台生成的备份包                             |
| `config/logs/`              | 运行日志                                     |
| `config/cups-drivers/`      | 后台上传的 PPD 打印驱动                      |

**备份 / Backup**：停止容器后整体复制 `./config` 目录即可。
**恢复 / Restore**：停止容器 → 用备份覆盖 `./config` → 启动容器。

## 许可证 / License

本项目基于 [GNU General Public License v3.0](LICENSE)（GPL-3.0）许可发布，可任意选用更高版本（GPL-3.0-or-later）。
Released under the [GNU General Public License v3.0](LICENSE) (GPL-3.0), or (at your option) any later version.

> 这意味着：你可以自由使用、修改和再分发本软件，包括商用；但**分发修改后的版本时必须同样以 GPL-3.0 开源并附上完整源码**。若你通过网络向用户提供本软件的服务，请注意 GPL-3.0 本身不要求公开源码（那是 AGPL-3.0 的要求），但分发软件二进制或源码副本时必须履行上述义务。
>
> In short: you may use, modify and redistribute this software, including commercially; but **if you distribute modified versions you must keep them under GPL-3.0 and provide the complete source**. GPL-3.0 (unlike AGPL-3.0) does not by itself require publishing source for network-only use.

```text
PrintHub - An open-source cloud printing solution for upload, pricing, payment and print.
Copyright (C) 2025 PrintHub contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
```
