#!/bin/sh
set -eu

# 所有持久化数据都在 /app/config（数据库、上传件、备份、日志、CUPS 驱动），
# 该目录由 docker-compose 绑定挂载到宿主机 ./config。备份 = 复制这个目录。
export CONFIG_ROOT="${CONFIG_ROOT:-/app/config}"

# 建目录并交给 app 用户；驱动目录必须提前存在，否则绑定挂载会以 root 身份创建它。
mkdir -p "${CONFIG_ROOT}" "${CONFIG_ROOT}/uploads" "${CONFIG_ROOT}/backups" "${CONFIG_ROOT}/logs" "${CONFIG_ROOT}/cups-drivers"
chown -R app:app "${CONFIG_ROOT}"

# 首次部署时生成 ${CONFIG_ROOT}/config.json（全部键 + 随机 app_secret）。
# 这是唯一的配置文件，不再读取 .env；之后所有配置改这个文件或后台页面。
# bootstrap 只写缺失的键，已有配置和数据库里的值都不会被覆盖。
cd /app
runuser -u app -- python3 -m app.bootstrap

exec runuser -u app -- "$@"
