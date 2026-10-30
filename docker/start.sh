#!/bin/sh
# 容器启动脚本：显式展开 PORT（Docker 的 exec 数组不会展开 "$PORT"）。
# 单实例、单 worker 是首版验收边界；多 worker 需要另做数据库锁与并发方案。
set -eu

: "${PORT:=8000}"
: "${WEB_CONCURRENCY:=1}"

cd /app/backend

# 迁移是幂等的、只增不删；AUTO_MIGRATE=false 时由发布流程单独执行 python -m app.migrate。
if [ "${AUTO_MIGRATE:-true}" = "true" ]; then
    python -m app.migrate --check >/dev/null 2>&1 || python -m app.migrate
fi

# --proxy-headers 让 Render/反代提供的客户端地址进入 request.client，
# 仅信任平台入口转发的头；不要在校验证书或开放公网端口上做妥协。
exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers "$WEB_CONCURRENCY" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --timeout-keep-alive 15
