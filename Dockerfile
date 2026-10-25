# syntax=docker/dockerfile:1

# Stage 1: Build the Vue single-page application.
# pnpm 版本与 frontend/package.json 的 packageManager 字段保持一致（corepack 严格校验）。
# pnpm-workspace.yaml 必须随 package.json 一起先拷入：install 的供应链策略
# （minimumReleaseAge）等配置就读在它里面，晚拷会让 --frozen-lockfile 落回默认策略。
FROM node:22.18-bookworm-slim AS frontend-build
WORKDIR /src/frontend
RUN npm install -g pnpm@12.11.2
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

# Stage 1b: Build the pycups wheel. pycups has no prebuilt wheel and needs a C
# compiler + cups headers; compiling happens in this throwaway stage so the
# runtime image never carries the build toolchain.
# 注意：版本号必须与 backend/requirements.txt 的 pycups 一致——不一致时运行阶段
# pip 找不到匹配 wheel 会回退源码编译并因缺少编译链而失败。
FROM python:3.12-slim-bookworm AS pycups-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libcups2-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels pycups==2.0.4

# Stage 2: Runtime image — FastAPI serves both the API and frontend static files,
# plus the native programs required for document conversion, coverage detection,
# and optional remote CUPS printing.
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=zh_CN.UTF-8 \
    LC_ALL=zh_CN.UTF-8 \
    TZ=Asia/Shanghai \
    # glibc 内存池上限：uvicorn/后台线程 + LibreOffice 子进程都是多线程 glibc 程序，
    # 默认按 CPU 核数开 arena 会长尾膨胀堆内存，压到 2 降低常驻内存。
    MALLOC_ARENA_MAX=2

# 字体库说明（避免文档转 PDF / 打印乱码）：
#   fonts-noto-cjk / -extra     中文简繁日韩 CJK 全部字重（含中文粗体，删了会假粗体）
#   fonts-noto-core             数学符号(∑∫√≠≤≥∈∂∇)、上下标(H₂O 的₂)、科学符号、
#                               Symbols/Symbols2(图案符号兜底) + 拉丁 Regular/Bold/Italic
#   fonts-noto-mono             等宽 Noto，兼顾符号
#   fonts-liberation / -2       Times New Roman / Arial / Courier New 度量兼容替代
#   fonts-crosextra-carlito     Calibri 度量兼容替代
#   fonts-crosextra-caladea     Cambria 度量兼容替代
#   fonts-dejavu                拉丁/希腊/西里尔/符号广覆盖兜底
#   fonts-stix                  专业数学/科技公式字体（Cambria Math 类）
#   fonts-noto-color-emoji      Emoji / 彩色符号兜底
#   libwmf-bin                  WMF 图元光栅化后备（老式 MathType/公式3.0 矢量预览图）
# （fonts-noto-extra / fonts-dejavu-extra 只提供多余字重/极少用字形，合计 330MB+，
#   已移除：fontconfig 回退链引用的字体全部在上列包内，见 docker/fontconfig/。）
#
# LibreOffice 不装 `libreoffice` 元包（会连带 libreoffice-base/draw 等本系统用不到的
# 组件）：上传支持的 Office 类型只有 doc(x)/xls(x)/ppt(x)，按需装 core+writer+calc+
# impress+math（math 渲染 docx 内嵌公式必须保留），--no-install-recommends 也不会引入 Java。
#
# 运行时镜像不装任何编译工具链：pycups 的 wheel 在 Stage 1b 编好，pip 通过
# --find-links 优先取本地 wheel（版本仍以 requirements.txt 为准）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        cups-client \
        fontconfig \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        fonts-noto-core \
        fonts-noto-mono \
        fonts-liberation \
        fonts-liberation2 \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fonts-dejavu \
        fonts-stix \
        fonts-noto-color-emoji \
        libcups2 \
        libwmf-bin \
        libreoffice-core \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-math \
        locales \
        poppler-utils \
        util-linux \
    && sed -i 's/^# *zh_CN.UTF-8 UTF-8/zh_CN.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && (fc-cache -f >/dev/null 2>&1 || fc-cache -f) \
    && rm -rf /var/lib/apt/lists/*

# 部署字体映射/回退配置：把文档里的 Windows/Office 专有字体名映射到镜像内已装字体，
# 并为所有字体追加 CJK + 数学 + 符号兜底回退链，从源头避免转换/打印乱码。
COPY docker/fontconfig/49-cloud-print-aliases.conf /etc/fonts/conf.d/49-cloud-print-aliases.conf
RUN fc-cache -f -v >/dev/null 2>&1 || fc-cache -f

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
COPY --from=pycups-build /wheels /wheels
RUN pip install --upgrade pip \
    && pip install -r requirements.txt --find-links=/wheels \
    && rm -rf /wheels \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home app

COPY backend/app ./app
# Copy frontend build output so FastAPI can serve it directly (no separate Nginx).
COPY --from=frontend-build /src/frontend/dist ./frontend-dist
COPY docker/entrypoint.sh /usr/local/bin/cloud-print-entrypoint
RUN chmod 0755 /usr/local/bin/cloud-print-entrypoint \
    && mkdir -p /app/config \
    && chown -R app:app /app

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/cloud-print-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
