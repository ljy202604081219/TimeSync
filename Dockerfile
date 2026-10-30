# TimeSync 时聚 — 多阶段构建：Node 构建前端，Python 运行 FastAPI。
# 目标平台是 Render 免费 Web Service（Docker），也适用于任何支持 Dockerfile 的托管。
# 不使用 Alpine/musl：OR-Tools 的预编译依赖按 Debian/glibc 验证。

# ---------- 1. 前端构建 ----------
FROM node:22-bookworm-slim AS web
WORKDIR /src/frontend
# 只复制锁文件相关文件，最大化利用层缓存。
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
# corepack 提供与锁文件一致的 pnpm，避免运行时联网解析版本。
RUN corepack enable && corepack prepare pnpm@10.18.3 --activate \
    && pnpm install --frozen-lockfile
COPY frontend/ ./
# 构建阶段完成 TypeScript 与 Vite，运行阶段不再安装前端依赖、不再联网重建。
RUN node node_modules/typescript/bin/tsc -b \
    && node node_modules/vite/bin/vite.js build

# ---------- 2. 运行时 ----------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    PORT=8000
WORKDIR /app

# 先装依赖再复制源码，代码改动不会让依赖层失效。
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=web /src/frontend/dist ./frontend/dist
COPY docker/start.sh /app/docker/start.sh

# 非 root 运行；/app 需要可写以便容器内 SQLite 回退路径和迁移日志。
RUN useradd --create-home --uid 10001 timesync \
    && chmod +x /app/docker/start.sh \
    && chown -R timesync:timesync /app
USER timesync

EXPOSE 8000
# 存活检查不访问数据库：冷启动或数据库抖动时不应反复重启容器。
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health',timeout=4)"

WORKDIR /app/backend
ENTRYPOINT ["/bin/sh", "/app/docker/start.sh"]
