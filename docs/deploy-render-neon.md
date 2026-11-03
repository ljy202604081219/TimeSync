# 从零上线：GitHub → Neon → Render（约 30–40 分钟）

本文件是 `docs/deployment.md` 的"照做版"，面向第一次部署的人。每一步都写清"点哪里、填什么、看到什么算成功"。
命令都在仓库根目录（`TimeSync/`）执行。

**前置账号**：GitHub（私有仓库）、Render、Neon。三者免费档都不需要信用卡。
**免费档的限制（2026-10 官方文档，会变，用前确认一次）**：Render 免费 Web Service 15 分钟无请求即休眠、冷启动约 40–60 秒、每月 750 实例小时；自带免费 Postgres **创建 30 天后删除**。Neon 免费档 0.5 GB 存储 / 100 CU 小时每月，无请求 5 分钟后缩容、下次查询几百毫秒唤醒，不删库。所以**数据库用 Neon，别用 Render 自带库**。

---

## 0. 先在本机预演一遍（3 分钟，不需要账号）

确认代码在"云端形态 + 空库"下的行为，避免部署后才发现问题：

```bash
cd backend
DATABASE_URL="sqlite:///../firstboot.db" DEMO_MODE=false SANDBOX_MODE=true \
  ADMIN_TOKEN="rehearsal-admin-token-0123456789" BOOTSTRAP_FIXTURES=true \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8126
```

另开一个终端：

```bash
TIMESYNC_BASE_URL=http://127.0.0.1:8126 ADMIN_TOKEN="rehearsal-admin-token-0123456789" \
  python tools/deployment_check.py
```

预期最后一行是 `12/12 checks passed`。停掉服务、再启动一次，`/api/auth/config` 仍是 4 个成员且数据条数不变（首次启动初始化只在空库执行一次）。

---

## 1. 把代码推到 GitHub

1. github.com → **New repository** → 名字 `timesync` → 选 **Private** → 不要勾选任何初始化文件 → Create。
2. 在本地仓库执行（把 `<你>` 换成账号）：

```bash
git remote add origin https://github.com/<你>/timesync.git
git push -u origin master
```

成功标志：`git status` 干净；刷新 GitHub 能看到 13+ 次提交和 `render.yaml`。

推之前自检，确认没有把密钥和数据推上去：

```bash
git ls-files | grep -E "^\.env$|\.db$|demo-tokens" ; echo "exit=$?"
```

应该没有任何输出（`exit=1`）。`.env`、`.venv*`、`node_modules`、`*.db`、`frontend/dist` 都已被 `.gitignore` 排除。

---

## 2. Neon 建库（5 分钟）

1. console.neon.tech → **New Project**。
2. **Region 选 Singapore**（离中国大陆最近；Render 的新加坡节点也在同一区域）。
3. 项目建好后打开 **Connect**，复制 **Connection string**。有两种：

| 选项 | 长什么样 | 推荐 |
|---|---|---|
| Direct（直连） | `...@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require` | ✅ 本项目自带连接池（5 条），直连最简单 |
| Pooled（连接池） | `...@ep-xxx-pooler.ap-southeast-1.aws.neon.tech/...` | 也可用：代码检测到 `-pooler` 会自动关闭预处理语句缓存 |

**两处必须保留**：URL 末尾的 `?sslmode=require`，以及不要手动改 `postgresql://` 前缀（代码会自动换成 `postgresql+psycopg://`）。

---

## 3. Render 部署（10 分钟，含构建等待）

1. dashboard.render.com → **New +** → **Blueprint**。
2. 第一次会让你连 GitHub，授权后选中 `timesync` 仓库 → **Connect**。
3. Render 读到 `render.yaml`，显示一个服务 `timesync`（Docker、free、singapore、health check `/api/health`）。
4. 它要求填两个 `sync: false` 的变量：
   - `DATABASE_URL`：粘贴第 2 步的 Neon 连接串（**唯一必填项**）
   - `AI_API_KEY`：没有就先留空。留空时截图提取类接口返回 503，其余功能全部正常。
5. **Apply / Create**。首次构建 3–6 分钟（Node 构建前端 + pip 装 OR-Tools）。

成功后看两处：

- **Logs** 里应有 `TimeSync: bootstrapped 4 synthetic identities and fixtures for 4 members.`（说明空库自动建了演示身份）和 `Uvicorn running on http://0.0.0.0:10000`。
- 页面顶部出现 `https://timesync-xxxx.onrender.com`，直接打开应看到登录页，列出 4 个成员。

`ADMIN_TOKEN` 由 Render 自动生成。到 **Environment** 页复制它，**只存进密码管理器**，不要写进文档、群聊或提交到仓库。

---

## 4. 部署后验收（2 分钟）

在本机仓库根目录：

```bash
set TIMESYNC_BASE_URL=https://timesync-xxxx.onrender.com     # Windows
set ADMIN_TOKEN=<第 3 步复制的值>
python tools/deployment_check.py
```

（bash 用 `export`。）脚本会逐项打印，预期 `12/12 checks passed`：

| 检查 | 证明什么 |
|---|---|
| health 200 / ready 200 + schema v2 | 服务活着，迁移已跑到版本 2 |
| auth/config advertises sandbox | 登录方式由服务端下发，不是前端硬编码 |
| legacy demo entry closed | 旧的永久演示令牌入口在云上已关闭 |
| sandbox login 200 | 成员能登录拿到短时会话 |
| web agenda 200 + ETag / 304 | 日程读取与缓存协商正常 |
| device agenda 200, same ETag | 设备凭据能读，且与网页看到同一版本 |
| device write rejected 403 | 设备凭据写不了业务数据 |
| unknown token 401 / revoked 401 / logged-out 401 | 无效、已撤销、已退出的凭据立即失效 |

脚本打印的 `W/"..."` 就是 ETag 前缀，304 说明协商缓存生效——这是 30 秒轮询不浪费流量的前提。

---

## 5. 签发真实设备令牌（1 分钟）

```bash
curl -X POST https://timesync-xxxx.onrender.com/api/admin/device-tokens \
  -H "X-Admin-Token: <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d "{\"owner_id\":\"A\",\"label\":\"宿舍只读屏\",\"ttl_days\":7}"
```

响应里的 `token` **只出现这一次**（数据库只存哈希）：立刻存进密码管理器，然后把 `token` 字段从终端回滚记录里清掉。设备端按 `docs/device-integration.md` 接入，只需 `GET /api/v1/agenda` 与 `If-None-Match`。

---

## 6. 演示期保活与费用

免费实例 15 分钟无请求就休眠，冷启动 40–60 秒——**这会打断 30 秒轮询，也会让评委/队友打开链接时先等一分钟**。三个选择：

| 方案 | 做法 | 代价 |
|---|---|---|
| A 升级实例 | Render 服务 Settings → Instance Type 改 **Starter** | $7/月，不休眠，最稳 |
| B 外部保活 | cron-job.org 每 10 分钟 GET `https://.../api/health`（无需鉴权，别把 ADMIN_TOKEN 放进去） | ¥0，但 750 小时/月是上限，常驻一个月刚好用满 |
| C 演示前预热 | 上课/演示前 5 分钟先打开一次首页，让容器起来 | ¥0，只需记住 |

数据库侧不用管：Neon 缩容不影响数据，下次查询自动唤醒。

---

## 7. 常见故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 首次打开 502 / 等很久 | 免费实例冷启动 | 等 40–60 秒再刷新；长期方案见第 6 节 |
| `prepared statement "s_1" already exists` | 直连 PgBouncer 池但没关预处理缓存 | 用 Direct 串，或确认代码是最新版（检测 `-pooler` 自动关闭） |
| `password authentication failed` | 连接串密码含特殊字符被截断 | 在 Neon 重置密码，用 URL 编码后的串 |
| `SSL connection is required` | 串里漏了 `sslmode=require` | 补上，或在 Render 设 `DB_SSLMODE=require` |
| `/api/ready` 返回 503 | 迁移没跑成功 | 看 Logs 里的 traceback；确认 `DATABASE_URL` 指向 Neon 且库为空或已迁移 |
| 登录页没有成员 | `BOOTSTRAP_FIXTURES` 未开，或库里已有其它用户 | 设 `BOOTSTRAP_FIXTURES=true` 后重启；或手动 `python -m app.bootstrap --fixtures` |
| 构建报 pnpm 相关错误 | `corepack prepare pnpm@10.18.3` 失败 | 重试一次构建；仍失败把 Logs 前 50 行贴出来 |
| 提取功能 503 | `AI_API_KEY` 留空 / 额度用尽（全局 20 次/天） | 填 Key，或换天再试 |

---

## 8. 回滚与清理

- **回滚代码**：Render → 服务 → **Deploys** → 选上一个成功的部署 → **Rollback**。数据库迁移只增不删，回滚代码不会破坏已有数据。
- **停掉服务**：Settings → **Suspend**（不产生费用）；彻底不用就 Delete Service，再去 Neon 删项目。
- **换库重来**：Neon 新建项目、改 `DATABASE_URL`、重启即可；首次启动会自动重新建 4 个合成身份。

---

## 9. 完成后要回填的信息

把这三项交给 ③（或写进 `docs/deployment.md` §9 的部署记录表）：

1. `https://` 地址
2. 部署时间与当时的提交号（`git rev-parse --short HEAD`）
3. `tools/deployment_check.py` 的 12/12 输出（可直接粘贴）

设备令牌不进文档，只私下交付。

---

## 10. 首次真实部署记录（2026-10-31）

| 项目 | 值 |
| --- | --- |
| 服务地址 | `https://timesync-9fe1.onrender.com` |
| Render 服务 | `srv-dbj0vnu7bikc73e411a0`（timesync，free，singapore，docker） |
| 部署提交 | `23b840c`（`main`） |
| 数据库 | Neon，PostgreSQL 18.6，schema v2 |
| 创建方式 | 控制台 Blueprint（`render.yaml`） |
| 首次构建 | 15:57:22Z 开始 → 15:58:52Z live，约 90 秒 |

**实测结论**

- `tools/deployment_check.py` 对公网地址：**12/12 通过**（健康、就绪、沙箱登录、ETag/304、设备只读、越权 403、未知令牌 401、退出即失效）。
- 设备凭据签发成功（owner=A），读日程 200 且 `revision` 与网页端一致；写 `/api/tasks` 返回 `403 device_forbidden`。
- 云端重启（`server_restarted` 15:06:43Z）后再次读取：`revision` 完全不变，`/api/ready` 显示 `postgresql+psycopg`、`expected_schema_version=2`，证明数据全部来自 Neon，容器本地文件无依赖。
- `AI_API_KEY` 未配置：截图/课表提取类接口按设计返回 503，其余功能正常。

**踩过的坑（写下来避免重复）**

1. **Render API 创建服务返回 402**：即使 `plan=free`，新账号通过 API 创建也要先绑定付款方式；控制台 Blueprint 才是免卡路径。
2. **免费实例 15 分钟休眠**：休眠后首个请求需 30–60 秒冷启动，脚本类验收要先把 `/api/health` 唤醒再跑，否则读超时。
3. **`ADMIN_TOKEN` 可由 API 读回**：`GET /v1/services/{id}/env-vars` 能取到值（长度 44），因此无需人工复制；但不要把它写进任何文档或聊天记录。
4. **签发设备凭据必须带 `owner_id`**：只传 `label` 会 422；`tools/issue_device_token.py --owner A` 已封装。

---

## 11. 升级到 2.1.7（2026-11-03）

| 项目 | 值 |
| --- | --- |
| 代码 | `256fafd` → `b9600eb`，分支 `main` |
| 版本 | TimeSync 2.1.7（助手、QQ 模块、PWA、schema v4） |
| 构建 | 自动部署，约 72 秒进入 live |
| 数据库 | Neon `neondb`，schema v2 → v4（新增迁移 3、4） |
| 回退标记 | git tag `pre-2.1.7`、分支 `backup/pre-2.1.7`、旧部署 `dep-dbj14rnavr4c73biicd0` |

**升级前备份**：`.pytest-tmp/upgrade/backup-20261103-192236/neon-logical-backup.json`
（15 张表、121 行、27.2 KB，含 `schema_migrations` 记录）。

**新增表**：`assistant_threads`、`assistant_proposals`、`qq_groups`、`qq_messages`、`qq_notices`。
迁移只增不改，升级前后 `users=4 / tasks=12 / availability=56 / busy_intervals=20` 完全一致。

**环境变量**（28 项，`DATABASE_URL` 与 `ADMIN_TOKEN` 原值保留）
新增 `ASSISTANT_MODE=auto`、`ASSISTANT_AUTO_CREATE=true`、`ASSISTANT_TIMEOUT_SECONDS=60`、`AI_ADMIN_UI=false`；
`AI_BUDGET_ENABLED=false`、`BOOTSTRAP_FIXTURES=false`（Blueprint 同步已生效）。
`AI_API_KEY` 仍为空 → 助手运行在规则演示模式（`/api/v1/assistant/status` 返回 `mode=mock`）。

**线上验收**

| 检查 | 结果 |
| --- | --- |
| `/api/health`、`/api/ready` | 200，schema v4 = expected |
| 基础 12 项（登录、ETag/304、设备只读、越权 403…） | 12/12 通过 |
| 原有数据 | `revision=958f70e0…` 与升级前完全一致 |
| AI 查询 | 200，回答引用真实日程「11-04 08:00–10:00 大学英语」 |
| AI 新增 | 「添加明天20点到21点的高数复习」→ 已添加 11-04 20:00–21:00，日历可见 |
| 多轮补充 | 先问「几点到几点」，补「20点到21点」后落库 11-05 20:00–21:00 |
| 重试 | 同一 `request_id` 连发两次，仅生成 1 条 |
| 排程 / 修复 | `POST /api/plans` 生成 plan 6；`/api/disruptions/preview` 200 |
| 会议 | 候选人 17 个 → 创建 pending → A、B 均接受 → `confirmed` |
| PWA | `/manifest.webmanifest`、`/sw.js`、图标均 200；首页引用新构建资源 |
| QQ | `/api/v1/qq/status` 200；`live_enabled=false`、`account=null`（未接真实账号） |

**验收数据清理**：临时可用时段、验收会议、测试事件、助手会话、`deploy-check` 凭据与
全部沙箱会话均已删除；清理后 `revision` 回到升级前的 `958f70e0…`，两个真实设备凭据未受影响。

**回退方法**

1. 代码：`git revert b9600eb` 后推送，或在 Render 选择旧部署 `dep-dbj14rnavr4c73biicd0` 重新部署。
2. 数据：v4 只新增表，旧代码读取 v4 不受影响；如需完全还原，用上面的 JSON 备份按表回灌。

**仍未配置**：`AI_API_KEY`（真实 MiMo Key）为空，助手为规则演示；QQ 真实连接需要外部 NapCat 可公网访问，
当前 `SANDBOX_MODE=true` 按设计强制关闭真实入口。
