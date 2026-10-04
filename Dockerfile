# syntax=docker/dockerfile:1

# Stage 1: Build the Vue single-page application.
FROM node:22.18-bookworm-slim AS frontend-build
WORKDIR /src/frontend
RUN npm install -g pnpm@10.15.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

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
    TZ=Asia/Shanghai

# 字体库说明（避免文档转 PDF / 打印乱码）：
#   fonts-noto-cjk / -extra     中文简繁日韩 CJK 字符集
#   fonts-noto-core / -extra    数学符号(∑∫√≠≤≥∈∂∇)、上下标(H₂O 的₂)、大量科学符号
#   fonts-noto-mono             等宽 Noto，兼顾符号
#   fonts-liberation / -2       Times New Roman / Arial / Courier New 度量兼容替代
#   fonts-crosextra-carlito     Calibri 度量兼容替代
#   fonts-crosextra-caladea     Cambria 度量兼容替代
#   fonts-dejavu / -extra       拉丁/希腊/西里尔/大量符号广覆盖兜底
#   fonts-stix                  专业数学/科技公式字体（Cambria Math 类）
#   fonts-noto-color-emoji      Emoji / 彩色符号兜底
#   libwmf-bin                  WMF 图元光栅化后备（老式 MathType/公式3.0 矢量预览图）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cups-client \
        fontconfig \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        fonts-noto-core \
        fonts-noto-extra \
        fonts-noto-mono \
        fonts-liberation \
        fonts-liberation2 \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fonts-dejavu \
        fonts-dejavu-extra \
        fonts-stix \
        fonts-noto-color-emoji \
        libcups2 \
        libcups2-dev \
        libwmf-bin \
        libreoffice \
        locales \
        poppler-utils \
        util-linux \
    && sed -i 's/^# *zh_CN.UTF-8 UTF-8/zh_CN.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

# 部署字体映射/回退配置：把文档里的 Windows/Office 专有字体名映射到镜像内已装字体，
# 并为所有字体追加 CJK + 数学 + 符号兜底回退链，从源头避免转换/打印乱码。
COPY docker/fontconfig/49-cloud-print-aliases.conf /etc/fonts/conf.d/49-cloud-print-aliases.conf
RUN fc-cache -f -v >/dev/null 2>&1 || fc-cache -f

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
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
