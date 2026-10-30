# ③ 交付说明（后端与云服务）

本次交付 = 前两轮代码 + ③ 的数据库适配、认证与设备凭据、限额与体积保护、容器与部署配置。

## 先读这三份

1. `docs/backend-03-handoff.md` —— 改了什么、测试结果、未完成与阻塞、回滚方式（**入口**）
2. `docs/deployment.md` —— Render + Neon 部署/迁移/备份/恢复步骤与检查清单
3. `docs/backend-implementation-roadmap.md` —— ① 给的原始路线图（验收门槛以它为准）

## 快速验证（不用云账号）

```bash
# 依赖（Python 3.12/3.13）
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt   # Linux/macOS 用 .venv/bin/python

# 全量测试：116 项
cd backend && ../.venv/Scripts/python -m pytest -q

# 本地起服务（默认 DEMO_MODE=true，沿用原演示登录）
cd .. && python run.py
```

## 一键体验"云端形态"（本机 SQLite）

```bash
cd backend
export DATABASE_URL="sqlite:///../demo.db" DEMO_MODE=false SANDBOX_MODE=true ADMIN_TOKEN="换成你自己的32位随机串"
python -m app.migrate
python -m app.bootstrap --fixtures
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 另开终端：进入演示沙箱
curl -X POST http://127.0.0.1:8000/api/sandbox/sessions -H 'Content-Type: application/json' -d '{"member":"A"}'
# 签发设备只读凭据
curl -X POST http://127.0.0.1:8000/api/admin/device-tokens -H "X-Admin-Token: $ADMIN_TOKEN" \
     -H 'Content-Type: application/json' -d '{"owner_id":"A","label":"宿舍只读屏"}'
```

## 明确未验证（不要写成已完成）

Docker 镜像构建、真实 PostgreSQL 运行、Render/Neon 实际部署、HTTPS 访问、云端持久化重启与冷启动、真实 MiMo 调用。
本机没有 Docker、没有 PostgreSQL、没有云账号授权；对应步骤与记录表见 `docs/deployment.md` §9。

## 分支

仓库按阶段提交：`B0 baseline` → `B1 数据库` → `B2 认证/设备/限额` → `B3 构建部署` → `Docs`。可逐段评审或回退。
