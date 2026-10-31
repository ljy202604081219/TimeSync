# ③ 后端与云服务 · 接手交接说明

整理日期：2026-10-30（上海时间）。对应 `docs/backend-implementation-roadmap.md` 中 B0–B3，以及 B4/B5 中"代码与配置可交付、账号侧待实际授权"的部分。

**一句话结论**：数据库层已做成 SQLite/PostgreSQL 双后端并带版本化迁移；Web 沙箱会话、设备只读凭据、AI 预算与请求体限制已实现并有测试；Docker/Render 部署文件已就绪。**但没有真实 PostgreSQL 实例、没有 Docker 守护进程、没有 Render/Neon 账号授权，所以"云端实跑"仍是未验证项，不能写成已完成。**

---

## 1. 交付物清单

| 交付物 | 位置 |
|---|---|
| 后端实现（B1 数据库、B2 认证/设备/限额） | `backend/app/` |
| 版本化迁移与云端初始化命令 | `backend/app/migrations.py`、`migrate.py`、`bootstrap.py` |
| 容器与部署配置 | `Dockerfile`、`.dockerignore`、`docker/start.sh`、`render.yaml`、`docker-compose.yml` |
| 环境变量模板 | `.env.example`（全部新增变量都有注释，无真实值） |
| 自动测试（新增 44 项） | `backend/tests/test_db.py`、`test_auth_devices.py`、`test_ai_budget.py`、`test_deploy_config.py` |
| 测试原始输出 | `docs/backend-03-test-output.txt` |
| 部署运行手册（Neon/Render/迁移/备份/回滚） | `docs/deployment.md` |
| ② Web 登录接入说明 | `docs/web-auth-integration.md` |
| ④ 设备接入说明 | `docs/device-integration.md` |
| 契约与合成样例 | `docs/contracts/`（含 4 个新增样例，已脱敏） |

---

## 2. 接手前的现状核对（先检查，再开发）

逐项对照路线图第二节，结论如下：

| 路线图列出的"当前缺口" | 现状 |
|---|---|
| 没有 PostgreSQL 驱动与适配 | **已补**：`psycopg[binary]==3.3.6`；`DATABASE_URL` 自动识别 `postgres://`、`postgresql://`、`postgresql+psycopg2://` 并统一成 `postgresql+psycopg://` |
| 写事务用 SQLite 专用 `BEGIN IMMEDIATE` | **已改**：`db.write_transaction()` 按后端分流，SQLite 保持原语义，PostgreSQL 用事务级 advisory lock |
| 没有版本化迁移，靠 `create_all` | **已补**：`schema_migrations` 版本表 + 两个增量版本；启动只跑"只增不删"的迁移 |
| `/api/demo/accounts` 关闭后无登录入口 | **已补**：`POST /api/sandbox/sessions` 短时沙箱会话（DB 存哈希、到期、撤销） |
| agenda 只有完整用户令牌，无设备 scope/到期/撤销 | **已补**：`device_tokens` 实体 + 管理签发/撤销接口 + `agenda:read` 权限校验 + 每次请求校验到期/撤销 |
| 无公网调用预算、频率/并发限制 | **已补**：`ai_usage` 台账（跨重启保留）+ 全局/单会话日预算 + 单并发预占 |
| 上传保护只在 multipart 解析之后 | **已补**：ASGI 中间件在解析前按 `Content-Length`/流式字节数拒绝 413；原 6 MB 单图校验保留 |
| 依赖安全升级 + 回归证据 | **已补**：见 §6，全量测试通过后锁定版本 |
| Docker/Render 配置不存在 | **已补文件**：Dockerfile、.dockerignore、start.sh、render.yaml；**未在本机构建**（无 Docker） |
| health=ok 不代表数据库正常 | **已补**：`/api/ready` 检查连通性 + schema 版本，失败返回 503 且不回显 DSN |

顺带发现并修掉的两个真实缺陷：

1. **读取顺序不稳定**：`plans.rows()`、`schedule_rows()` 没有 `ORDER BY`。SQLite 通常按插入顺序返回，PostgreSQL 不保证。后果是 `snapshot()` 哈希、变更列表、agenda revision 会随读取顺序漂移，进而让 ETag 随机变化、修复预览误报 409。已加 `ORDER BY id` / `ORDER BY start,id`（需①确认，见 §9）。
2. **演示夹具日期写死 2026-11-02**：云端演示若在别的周，会出现"今天暂无日程"。现支持 `anchor` 参数，默认值不变，所以历史测试与截图仍然有效。

---

## 3. 改动文件清单

### 新增

| 文件 | 作用 |
|---|---|
| `backend/app/config.py` | 全部环境开关集中读取（每次访问读环境，便于测试与热改） |
| `backend/app/auth.py` | 令牌解析、三种凭据主体（user/session/device）、依赖注入、管理员门禁 |
| `backend/app/devices.py` | 沙箱会话签发/查询/退出；设备凭据签发/撤销/列表/最近请求时间 |
| `backend/app/ai_budget.py` | AI 每日预算、单会话上限、单并发预占与结算 |
| `backend/app/middleware.py` | 请求体总量限制（解析前生效） |
| `backend/app/migrations.py` | 版本化迁移定义与执行器 |
| `backend/app/migrate.py` | `python -m app.migrate [--status|--check]` |
| `backend/app/bootstrap.py` | `python -m app.bootstrap [--fixtures|--status|--clear-sessions]` 云端初始化 |
| `Dockerfile`、`.dockerignore`、`docker/start.sh`、`render.yaml`、`docker-compose.yml` | 构建与部署 |
| `backend/tests/test_db.py`（13）、`test_auth_devices.py`（9）、`test_ai_budget.py`（9）、`test_deploy_config.py`（13） | 新增 44 项测试 |

### 修改

| 文件 | 改了什么 | 兼容性 |
|---|---|---|
| `backend/app/db.py` | 引擎工厂、连接池、`write_transaction`、`schema_version`、`describe` | 保留 `Base/make_engine/session/SessionLocal` 名称，原有导入不受影响 |
| `backend/app/models.py` | 新增 `SandboxSession`、`DeviceToken`、`AiUsage` 与一个组合索引 | 原有 11 张表零改动 |
| `backend/app/main.py` | 认证依赖替换、`/api/ready`、沙箱/管理/设备/AI 配额路由、`mutation()` 改用跨库事务、AI 端点接入预算 | 原路径、字段、状态语义不变；`GET /api/v1/agenda` 响应体完全不变 |
| `backend/app/plans.py` | 稳定排序（2 处 `order_by`） | 只影响顺序，不影响结果集合 |
| `backend/app/demo.py` | `anchor` 相对日期、`fixtures()` 可重复执行、`tokens=False` 不落盘 | 默认锚点不变，72 项旧测试全过 |
| `backend/app/schemas.py` | 新增 `SandboxLoginInput`、`DeviceIssueInput` | 纯新增 |
| `backend/requirements.txt` / `.lock` | 依赖升级与锁定 | 见 §6 |
| `.env.example` | 新增 30 项说明，全部为空或安全默认值 | 仍是模板，无真实密钥 |
| `run.py` | 新增 `--host`（默认仍 127.0.0.1），供局域网设备联调 | 默认行为不变 |
| `frontend/pnpm-workspace.yaml` | 清掉 `esbuild: set this to true or false` 占位值 | 干净安装 + 生产构建已验证 |
| `backend/export_contracts.py` | 额外导出沙箱/设备样例（令牌已脱敏） | 原有两个样例仍生成 |
| `README.md` | 补充 ③ 章节、实体与接口表 | ① 的原文未删改 |

---

## 4. 新增接口与权限矩阵

### 接口

| 接口 | 权限 | 说明 |
|---|---|---|
| `POST /api/sandbox/sessions` | 无（需 `SANDBOX_MODE=true`） | 请求 `{"member":"A"}`，返回一次性明文令牌、到期时间、范围与"共享沙箱"提示 |
| `GET /api/sandbox/session` | 沙箱会话 | 返回剩余分钟数，供②显示倒计时 |
| `DELETE /api/sandbox/session` | 沙箱会话 | 立即撤销当前会话 |
| `POST /api/admin/device-tokens` | `ADMIN_TOKEN` | 签发绑定 owner 的只读凭据，明文令牌仅在响应中出现一次 |
| `GET /api/admin/device-tokens` | `ADMIN_TOKEN` | 运维用：列出凭据元数据（可按 owner 过滤） |
| `DELETE /api/admin/device-tokens/{id}` | `ADMIN_TOKEN` | 撤销，下一次读取立即失败 |
| `GET /api/devices` | 完整用户/沙箱会话 | 只返回本人设备的脱敏元数据，绝不返回 token/hash |
| `GET /api/ai/quota` | 完整用户/沙箱会话 | 当日全局/本人用量与重置秒数，供②提示 |
| `GET /api/ready` | 无 | 数据库连通 + schema 版本；落后或不可用返回 503 |
| `GET /api/me`（增强） | 完整用户/沙箱会话 | 增加 `credential`、`scope`、`expires_at`；**设备凭据调用返回 403** |

### 权限矩阵（实测）

| 调用者 \ 接口 | agenda | tasks/meetings/plans | AI 提取/设置 | 管理接口 | `/api/me` |
|---|---|---|---|---|---|
| 演示用户令牌（`DEMO_MODE=true`） | ✅ | ✅ | ✅（本机设置另有限制） | ❌ 需 ADMIN_TOKEN | ✅ |
| 沙箱会话 | ✅ | ✅ | ✅（提取）/❌ 设置 | ❌ | ✅ |
| 设备凭据 `agenda:read` | ✅ | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |

设备凭据**只**能读 agenda；到期/撤销在鉴权阶段判断，早于 ETag/304 决策。

---

## 5. 数据库与迁移

**两种后端都支持的最小适配**（`docs/backend-implementation-roadmap.md` §5）：

1. 驱动与连接串：`postgresql+psycopg://`，支持托管面板给的 `postgres://` 写法；`DB_SSLMODE` 在 URL 缺少时补 `sslmode`。
2. 事务：`write_transaction(db, scope)`。SQLite 走 `WRITE_LOCK` + `BEGIN IMMEDIATE`（原行为不变）；PostgreSQL 走 `pg_advisory_xact_lock(hashtext(scope))`，随事务提交/回滚自动释放，因此两个 worker 也不会对同一幂等键"都以为没用过"。
3. 幂等语义完全保留：同键同内容返回原响应（`db.rollback()` 后返回旧记录），同键不同内容 409，失败事务不留半条任务/会议/计划。
4. 连接池：`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_TIMEOUT`/`DB_POOL_RECYCLE` + `pool_pre_ping`，适应 Neon 空闲断连。
5. 时间仍是规范化 ISO8601 字符串（未重写时间字段）；JSON 列在两种后端都可用（未改 JSONB，保持与①的代码一致）。
6. 排序稳定性：见 §2 缺陷 1。
7. 迁移：`schema_migrations(version, name, applied_at)`；版本 1 = 原有 11 张表，版本 2 = 3 张新表。没有 `drop_all()`、没有启动重置。已有 SQLite 库只补新表（有测试覆盖，含"保留旧数据"断言）。

**命令**

```bash
cd backend
python -m app.migrate --status      # 查看版本与待应用项
python -m app.migrate               # 应用（幂等）
python -m app.migrate --check       # CI 用：落后则退出码 1
python -m app.bootstrap --fixtures  # 云端：建四个合成身份 + 本周演示夹具
python -m app.bootstrap --clear-sessions   # 演示前清空所有沙箱会话
```

`bootstrap` 不打印、不写盘任何令牌：云端登录只能走沙箱会话或管理员签发的设备凭据，`backend/.demo-tokens.json` 只在 SQLite 本机路径生成。

---

## 6. 依赖、密钥与限额

**依赖升级（有回归证据后才锁定）**

| 包 | 原 | 现 | 说明 |
|---|---|---|---|
| fastapi | 0.119.1 | 0.162.0 | 原 0.119.1 与 Starlette 0.48.0 组合存在既有安全审计项 |
| starlette | 0.48.0（传递依赖） | 0.52.1（显式锁定） | 不锁会被解析到未来版本，干净安装不可复现 |
| python-multipart | 0.0.20 | 0.0.32 | 上传解析相关 |
| SQLAlchemy | 2.0.44 | 2.0.55 | 保持 2.0.x，不跨 2.1 |
| uvicorn | 0.38.0 | 0.54.0 | |
| psycopg | — | 3.3.6（`[binary]`） | 新增 PostgreSQL 驱动 |

升级后全量测试与前端生产构建通过才写入 `requirements.txt`/`.lock`。**没有做渗透测试，也没有审计报告。**

**密钥**：沿用 `DATABASE_URL`、`DEMO_MODE`、`AI_PROVIDER/AI_BASE_URL/AI_MODEL/AI_API_KEY`；新增 `ADMIN_TOKEN`、沙箱/设备 TTL、预算与体积开关。`ADMIN_TOKEN` 短于 16 字符时管理接口直接 503（不会"空令牌等于无鉴权"）。MiMo Key 只在服务端，不进入响应、日志或固件。

**限额**：全局日预算默认 20 次、单会话 5 次、单并发 1；按"尝试次数"计（失败也计数，避免重试用预算空转）；预占 10 分钟过期，进程崩溃不会永久占额；额度不足返回 429 + `Retry-After`。规则演示模式（无 Key）不消耗预算、不落台账。

**体积**：整包 8 MB（`MAX_REQUEST_BYTES`），在 multipart 解析前拒绝；单张截图 6 MB 与 MIME 嗅探保留。

---

## 7. 构建与部署

- `Dockerfile`：`node:22-bookworm-slim` 构建前端（`pnpm install --frozen-lockfile`）→ `python:3.12-slim` 运行；非 root（uid 10001）；`HEALTHCHECK` 打 `/api/health`；`ENTRYPOINT` 走 `docker/start.sh`。
- `docker/start.sh`：显式展开 `PORT`，`--host 0.0.0.0`、`--workers 1`、`--proxy-headers`；启动前跑一次 `app.migrate`（`AUTO_MIGRATE=false` 可交给发布流程）。
- `render.yaml`：free、docker、`healthCheckPath=/api/health`，`DEMO_MODE=false`、`LEGACY_TOKEN_AUTH=false`、`SANDBOX_MODE=true`，`DATABASE_URL`/`AI_API_KEY` 为 `sync: false`（人工粘贴），`ADMIN_TOKEN` 由平台生成后到控制台查看。
- `docker-compose.yml`：本地 PostgreSQL 17，供 B1 真库验收使用。

**未验证（务必按此表述）**：本机无 Docker 守护进程、无本地 PostgreSQL、无 Render/Neon 账号授权，因此没有执行过镜像构建、容器启动、真实 PostgreSQL 运行、HTTPS 访问、持久化重启与冷启动演练。上述只能由持有账号的人按 `docs/deployment.md` 执行并记录。

---

## 8. 测试结果

环境：Windows，Python 3.13.14，Node 22.22.2，SQLite 3；PostgreSQL 未安装，Docker 未安装。

```text
116 passed, 1 warning in 34.08s
```

原始输出：`docs/backend-03-test-output.txt`（1 条 warning 是 Starlette TestClient 关于 `anyio.abc.BlockingPortal` 的弃用提示，非本项目代码）。

| 分组 | 数量 | 覆盖 |
|---|---|---|
| 原两轮测试（未削弱，仅 1 处随认证结构调整） | 72 | 排程、DDL、会议状态机、幂等、agenda/ETag、边界 |
| `test_db.py` | 13 | URL 归一化、SSL 参数、连接池、SQLite PRAGMA、`BEGIN IMMEDIATE` 分支、advisory lock 分支、失败回滚、迁移幂等、旧库升级保数据、PostgreSQL DDL 静态编译、`describe` 不泄露凭据、稳定排序 |
| `test_auth_devices.py` | 9 | 沙箱开关、会话建立/过期/撤销、关闭演示入口后永久令牌失效、管理员凭据三种失败态、设备只能读 agenda 且 ETag 与 Web 一致、到期/撤销即时生效、设备列表 owner 隔离且不泄露 token、未知令牌 |
| `test_ai_budget.py` | 9 | 全局额度 429+Retry-After、跨会话不可绕过、失败尝试计数、并发预占、演示模式零消耗、配额状态、台账跨"重启"持久、超体积 413（有/无令牌） |
| `test_deploy_config.py` | 13 | `/api/ready` 正常/落后/数据库异常/health 不碰库、Dockerfile 多阶段与非 root、start.sh 展开 PORT 与单 worker、.dockerignore 排除密钥与数据、render.yaml 无明文密钥、环境变量模板与代码一致、模板无真实密钥、pnpm 占位值已清、依赖锁定、compose 指向一次性库 |

前端：`tsc -b` 与 `vite build` 通过，产物哈希与仓库内 `dist/` 一致（说明锁文件可复现）。

另有一轮本机手工冒烟（真实 HTTP、真实进程重启），结果见 §12。

**PostgreSQL 真库用例尚未执行**。已就绪的条件：`docker-compose.yml` 起库后 `TIMESYNC_TEST_DATABASE_URL=... python -m pytest -q` 会把同一套 116 项测试跑在 PostgreSQL 上（`tests/conftest.py` 支持该变量，且会在该库上 drop/create 项目表——只能指向一次性测试库）。

---

## 9. 未完成项、阻塞与责任划分

| 项 | 状态 | 阻塞/归属 |
|---|---|---|
| PostgreSQL 真库运行验证（含并发同键、失败回滚） | **未执行** | 需③拿到 Neon/本地 PG 后执行；测试与脚本已备 |
| Docker 镜像构建与容器启动 | **未执行** | 本机无 Docker 守护进程；文件已备，需在 Linux/CI 上验证 |
| Render + Neon 实际部署、HTTPS 子域名、冷启动与持久化重启 | **未执行** | 需账号授权；步骤见 `docs/deployment.md` |
| 备份恢复演练 | **未执行** | 需真实库；方案见 `docs/deployment.md` §6 |
| ② 前端登录改造（改用沙箱会话、401 重新进入、倒计时提示） | **只给接口与说明** | 归②，见 `docs/web-auth-integration.md`；当前 `DEMO_MODE=true` 本机仍可用旧入口 |
| ④ 设备端接入（凭据写入、校时、缓存、失联） | **只给接口与说明** | 归④，见 `docs/device-integration.md`；实物与模拟请求需分别记录 |
| `plans.py` 稳定排序 | **已改，待①确认** | 归①评审：只加 `ORDER BY`，不改业务语义；若①另有排序约定请覆盖 |
| 生产级用户体系（注册/密码/SSO/找回） | **未实现**，且不在首版范围 | 竞赛沙箱只面向四个合成身份 |
| 多人隔离体验空间、推送、OTA、触摸 | **未实现** | 不得在答辩材料中写成已完成 |
| 依赖 CVE 全量扫描 | **未做** | 只做了本次组合的回归；建议在 CI 加 `pip-audit` |

---

## 10. 回滚与备份

- **代码回滚**：本次改动在 Git 上有 5 个分阶段提交（B0 基线 → B1 → B2 → B3 → 文档），可逐段 revert；`main.py`/`models.py` 的改动集中在一处，不牵动①的算法文件。
- **schema 回滚**：版本 1/2 只新增表，业务表零改动，因此"回滚代码"不需要回滚数据库——旧代码会忽略新表。若要清理：`DROP TABLE sandbox_sessions, device_tokens, ai_usage` 并删除 `schema_migrations` 中对应版本（先备份）。
- **数据备份**：SQLite 用 `python -m app.seed_demo --reset` 前会自动备份；云端用 `pg_dump`（见 `docs/deployment.md` §6），恢复演练必须在隔离库做，不覆盖线上。
- **配置回滚**：`DEMO_MODE=true` + `SANDBOX_MODE=false` 可退回本机演示登录；`ADMIN_TOKEN` 置空即关闭管理接口。

---

## 11. 交回给①的内容

1. 分阶段提交与本文档；
2. 锁定依赖、可重复构建配置、环境变量模板、迁移与初始化命令；
3. 新增接口清单、权限矩阵、脱敏样例（`docs/contracts/`）；
4. 测试原始输出、未完成与阻塞清单；
5. 建议①评审：`plans.py` 排序、`demo.py` 夹具锚点、`main.py` 认证依赖替换是否影响①后续改动节奏。

真实 HTTPS 地址、管理员凭据、设备凭据的交付方式：**本次没有**（未部署）。拿到后按"私聊/密码管理器单独交付，文档只写存放位置"的规则处理，不写进任何 md 或聊天记录。

---

## 12. 本机手工冒烟验收（2026-10-30，SQLite，非云端）

不是替代 PostgreSQL/云端验收，只是证明"命令 + HTTP 链路"真的能跑通。环境：`DEMO_MODE=false`、`SANDBOX_MODE=true`、`ADMIN_TOKEN` 已配置、`DATABASE_URL=sqlite:///../smoke.db`。

| 步骤 | 命令/请求 | 结果 |
|---|---|---|
| 迁移 | `python -m app.migrate` | `applied_now=[1,2]`，`pending=[]` |
| 初始化 | `python -m app.bootstrap --fixtures --anchor 2026-11-02` | 建 4 个身份、12 条任务，未打印任何令牌 |
| 存活 | `GET /api/health` | 200 `{"status":"ok"}` |
| 就绪 | `GET /api/ready` | 200，`schema_version=2`、`expected_schema_version=2`，不含 DSN |
| 旧入口关闭 | `GET /api/demo/accounts` | 404 |
| 沙箱登录 | `POST /api/sandbox/sessions {"member":"A"}` | 200，令牌 43 字符，TTL 10800 秒，含"共享沙箱"提示 |
| 身份 | `GET /api/me`（会话） | 200，`credential=session`，`scope` 四项 |
| 日程 | `GET /api/v1/agenda`（会话） | 200，含 `course`/`task`，带 `ETag: W/"…"` |
| 缓存 | 同上 + `If-None-Match` | 304，`size_download=0` |
| 签发设备凭据 | `POST /api/admin/device-tokens {"owner_id":"A"}` | 200，令牌只在响应出现一次 |
| 设备读取 | agenda + 设备凭据 | 200，`user_id=A` |
| 设备越权 | `POST /api/tasks`、`GET /api/devices`（设备凭据） | 403、403 |
| 撤销 | `DELETE /api/admin/device-tokens/{id}` | `revoked=true` |
| 撤销生效 | 同一设备凭据读 agenda | **401**（立即失败） |
| 重启持久化 | 停进程→重启→复用原设备凭据/会话 | 均 200，`/api/ready` 仍 ok，数据与凭据都在 |
| 幂等 | 同键同内容两次 `POST /api/tasks` | 同一条记录（id=13） |
| 幂等冲突 | 同键不同内容 | 409 |
| 排程 | `POST /api/plans` | `status=optimal`，4 项已排 |
| 体积 | 9 MB 请求体 `POST /api/extract` | **413**（解析前拒绝） |

未覆盖：真实 PostgreSQL、Docker 容器、HTTPS、Render 冷启动与重新部署、Neon 额度与连接池实测、真实 MiMo 调用。

---

## 13. 第四轮（B4 · 联调修复，2026-10-30 深夜）

针对 ① 审查意见的三项修复。安全加固按 ① 要求暂缓，本轮只动与联调直接相关的部分。

### 13.1 PostgreSQL 业务并发锁（修复"全员已接受、会议仍 pending"）

- **根因**：写锁按 `owner:Idempotency-Key` 取 advisory lock。两个成员确认同一会议持不同键，两个事务都能读到"对方还没答复"，各自提交后所有邀请为 accepted、会议仍是 pending。
- **修复**：`db.write_transaction()` 改为**单一全局业务写锁**——PostgreSQL 用 `pg_advisory_xact_lock(0x54534E43)`（事务级，commit/rollback 自动释放），SQLite 仍为进程锁 + `BEGIN IMMEDIATE`。幂等键检查保持在锁内，原语义不变。
- 新增 `DB_LOCK_TIMEOUT_MS`（默认 15000）：锁等待超限返回 `503 {"code":"busy"}` + `Retry-After`，不会无限挂起。
- **代价（首版明确接受）**：业务写全部串行，确认会议时的 CP-SAT 计算会阻塞其他写请求数秒。四人演示规模无碍；扩容方向是按 meeting 行锁 / `SELECT FOR UPDATE`，已记入未完成项。

真实 PostgreSQL 并发测试（`tests/test_pg_concurrency.py`，7 项，需 `TIMESYNC_TEST_DATABASE_URL` 指向真实 PG）：

| 测试 | 证明 |
|---|---|
| 全局锁常量唯一 | 所有写者争同一把锁 |
| 不同键的两个写者不重叠 | 计数器读-改-写无丢失更新，事务区间不相交 |
| **旧按键加锁必然复现缺陷**（特征化测试） | 同样三个请求，换回旧锁策略 → 全部 200、全部 accepted、会议仍 pending |
| 三人同时接受 → 恰好确认一次 | 数据库终态 confirmed、linkage 3 条、邀请全部 accepted |
| decline 与 accept 并发 | 会议终态 declined，绝不会被并发接受翻转成 confirmed |
| 同幂等键并发两次 | 只建 1 条任务、1 条 RequestRecord，无 500 |
| 确认中抛错 → 完整回滚 | 邀请状态/会议状态/RequestRecord/PlanVersion 全部无残留，锁释放后同键重试成功 |

测试环境：本机从 `pgserver` wheel 中解出的 **PostgreSQL 16.2**（127.0.0.1:55432，非 Docker）。全套 135 项测试在该实例上通过（见 13.4）。注：`test_writers_with_different_keys_never_overlap` 在加固诊断信息前出现过一次偶发失败（约 1/20），加 5ms 提交边界容差后连续 15+ 次全绿；如再遇到请附窗口数据。

### 13.2 沙箱登录闭环（配合 ②）

- 新增 `GET /api/auth/config`（公开）：UI 据此决定登录方式，不再猜测。云端返回 `sandbox_mode=true` + 4 个成员（仅 id/name）+ TTL + login/logout 路径；本地返回 demo 模式。
- 所有 401/403/429/413/503 带稳定 `code`（`session_expired`、`session_revoked`、`auth_invalid`、`device_forbidden`、`sandbox_full`、`payload_too_large`、`busy` 等），401 附 `WWW-Authenticate: Bearer`。`detail` 中文文案原样保留，旧前端不受影响。
- **前端参考实现**：新增 `frontend/src/auth.ts`，`App.tsx` 接入——登录页按 config 渲染沙箱成员按钮（→ `POST /api/sandbox/sessions`），401 自动清凭据回登录页，侧边栏"退出登录"调 `DELETE /api/sandbox/session`，并显示"会话剩余 N 分钟"（30 秒刷新）。localStorage 键 `timesync-auth`，与旧键 `timesync-token` 双写兼容。
- 契约文档：`docs/contracts/auth-flow.md`（错误码表 + 浏览器验收清单）。`tsc -b` + `vite build` 通过。
- 本机 HTTP 全流程实测（云端形态）：config → 登录 → me/state/meetings 全 200 → 退出 → 原令牌立即 401 `session_revoked` → 首页静态资源 200。

### 13.3 Windows 首次安装 GBK 编码修复

- **复现**：cp936 代码页 + 关闭 UTF-8 模式时，`open('backend/requirements.txt')` 直接 `UnicodeDecodeError: 'gbk' codec can't decode byte 0xac`（探针脚本 `tools/encoding_probe.py` 留档）。pip 26 自身已免疫，但任何走系统区域编码的组件（旧版 pip、ensurepip、日志打印）都会踩中。
- **修复（三层）**：
  1. `requirements.txt` 改为纯 ASCII，中文说明移到本文件——彻底消除该类问题；
  2. `run.py` 在 Windows 上强制 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8`，pip/uvicorn 子进程一律加 `-X utf8`；
  3. `start.cmd` 开头 `chcp 65001` + 设置同样环境变量 + `python -X utf8 run.py %*`（支持参数透传，如 `start.cmd --check`）；`start.ps1` 同步处理；python 不存在时提示安装并回退 `py -3`。末尾改为**失败才 `pause`**——双击运行时错误信息仍会留在窗口，而自动化（CI、`start.cmd --check`）不会再卡在按键等待。
- 干净环境验证：新建空 venv（不删旧环境），在 cp936 代码页下执行 `start.cmd --python .venv-verify\Scripts\python.exe --check`，走真实首次安装→构建→测试全链路（结果见 13.4）。

### 13.4 本轮验证记录

- SQLite 全套：135 项（128 passed + 7 项 PG 专属跳过）。
- 真实 PostgreSQL 16.2 全套：135 项全部通过（116 旧 + 19 新），迁移在 PG 上自动建到 schema_version=2。
- 干净安装（cp936 代码页、清空 `PYTHONUTF8`/`PYTHONIOENCODING`、全新空 venv Python 3.13.14、stdin 关闭）：
  `pip` 解析 `requirements.txt` 无任何解码错误 → 装完全部依赖 → `tsc -b` + `vite build` → 前端 node 测试 4 项通过 → 后端 `128 passed, 7 skipped` → `EXIT=0`，耗时 1m55s。
  完整原始日志：`docs/backend-03-clean-install.log`（154 行，`UnicodeDecodeError` 出现 0 次）。

- 30 秒轮询额度实测（`tools/poll_quota_probe.py`，跑在**真实 PostgreSQL** 实例上的服务，设备只读凭据，6 次 × 30 秒）：

| 指标 | 实测值 | 说明 |
|---|---|---|
| agenda 状态序列 | `200,304,200,304,200,304,200,304,200,304,200,304` | 每次先取 200，再带 `If-None-Match` 得 304，无失败 |
| revision 种类 | 1（`f2a533c7…`） | 纯轮询不产生新版本，不会误报冲突 |
| ETag 种类 | 1（与 revision 同值） | 内容不变时 ETag 稳定，304 才有意义 |
| 304 命中 | 6 / 6 | 每次都命中缓存 |
| `last_request_at` 写入次数 | 3（6 次轮询耗时 2.5 分钟） | 服务端 60 秒节流精确生效，读操作不放大写压力 |
| AI 额度消耗 | 0（只留下当天日期键） | 轮询不触发任何模型调用 |

- PostgreSQL 重启持久化（`tools/persistence_probe.py`）：写会话+设备凭据+任务 → **杀进程重启** → 会话 200、设备 200、任务仍在。
- 登录闭环活体复测（PG 实例，最新代码）：`/api/auth/config` 200（`sandbox_mode=true`、4 成员、`session_ttl_minutes=180`）→ 登录 200 → `/api/me`、`/api/users/B/state` 200 → agenda 200 + 304 → 退出 200 → 原令牌立即 `401 session_revoked` 且带 `WWW-Authenticate` → 设备凭据读 agenda 200、写任务 `403 device_forbidden`。
- 全程未在文档/输出中记录任何明文凭据。

### 13.5 本轮后仍未完成（需要账号/网络，代码侧已就绪）

| 事项 | 状态 | 需要什么 |
|---|---|---|
| 部署后 HTTPS 地址 | 未完成（本机无 Render/Neon 账号） | 按 deployment.md 创建服务；或提供 Render API Key 由 ③ 代部署 |
| 真实测试设备令牌 | 未签发（无公网服务可绑） | 部署完成后 `POST /api/admin/device-tokens`，令牌私下交付 |
| 部署环境 200/304/401/403 复测 | 未执行 | 拿到 HTTPS 地址后运行 `tools/deployment_check.py` |
| Docker 镜像构建 / Render 持久化 | 未执行（本机无 Docker） | 任何一台有 Docker 的机器跑 `docker compose up` |
| 大规模并发下的锁吞吐 | 首版接受串行 | 数据量或人数增长后改行锁 |
