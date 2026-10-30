# 部署与运维手册（Render + Neon）

适用版本：③ 接手后的后端（`docs/backend-03-handoff.md`）。
**本文所有步骤在本机均未执行**：没有 Docker、没有 PostgreSQL、没有 Render/Neon 账号授权。执行者请边做边把结果填到文末"部署记录"，未填的部分不能对外声称已完成。

---

## 1. 目标形态

```text
手机/电脑 ── HTTPS ──┐
                     ├─ Render Web Service（Docker）：FastAPI + 前端静态产物
ESP32 只读屏 ─ HTTPS ─┘        ├─ Neon PostgreSQL：业务、会话、设备凭据、AI 台账
                              └─ MiMo（服务端 Key）
```

约束：单实例、单 worker；不使用 Redis/Celery/MQTT/对象存储。免费实例闲置约 15 分钟休眠，唤醒有延迟；容器本地文件不持久，**不能把 SQLite 或令牌文件当线上存储**。

---

## 2. 一次性准备

1. Neon 建项目，选与 Render 相近的地域（Render `singapore` → Neon `ap-southeast-1`）。
2. 复制 **pooler** 连接串（主机名含 `-pooler`），确认带 `sslmode=require`。
3. Render 新建 Blueprint 或 Web Service，指向本仓库 `Dockerfile`。
4. 在 Render 环境变量里填：
   - `DATABASE_URL`：上一步的连接串（Secret）
   - `AI_API_KEY`：MiMo Key（Secret）
   - 其余由 `render.yaml` 提供；`ADMIN_TOKEN` 由平台生成，创建后到控制台 **Environment** 查看并复制到密码管理器。

不要把这些值写进 `.env.example`、README、聊天记录或答辩材料。

---

## 3. 首次上线顺序

```bash
# 1) 应用 schema（容器启动会自动执行，也可手动确认）
python -m app.migrate --status

# 2) 建四个合成身份；必要时加本周演示夹具
python -m app.bootstrap --status
python -m app.bootstrap --fixtures

# 3) 健康与就绪
curl -s https://<service>.onrender.com/api/health   # {"status":"ok",...}
curl -s https://<service>.onrender.com/api/ready    # status ok, schema_version=2
```

`/api/ready` 返回 503 时：`status=behind` → 跑迁移；`database=unavailable` → 查 Neon 连接串/额度/白名单；两者都不回显 DSN。

---

## 4. 演示前检查清单

- [ ] `/api/ready` 为 200 且 `schema_version` 等于 `expected_schema_version`
- [ ] `DEMO_MODE=false`、`LEGACY_TOKEN_AUTH=false`、`SANDBOX_MODE=true`
- [ ] 打开页面能拿到沙箱会话（DevTools 里 `/api/sandbox/sessions` 200）
- [ ] `python -m app.bootstrap --clear-sessions` 清掉上一场遗留会话
- [ ] 演示夹具日期覆盖当天（`--fixtures` 默认用本周一；跨周演示要重跑并确认 agenda 有内容）
- [ ] 设备凭据已签发、已写入设备、`GET /api/devices` 能看到 `last_request_at`
- [ ] `/api/ai/quota` 剩余额度足够（默认 20 次/天）

**冷启动**：演示开始前 2–3 分钟打开页面预热；把"正在唤醒服务"作为正常提示，不要把唤醒失败显示成"今天没有日程"。

---

## 5. 限额与费用观察

| 变量 | 默认 | 调整建议 |
|---|---|---|
| `AI_DAILY_BUDGET` | 20 | 按账户余额与当天体验人数调整；调小更安全 |
| `AI_ACTOR_DAILY_BUDGET` | 5 | 单会话上限，防止一个人刷完 |
| `AI_MAX_CONCURRENCY` | 1 | 免费实例保持 1 |
| `MAX_REQUEST_BYTES` | 8 MB | 与隧道/平台限制一致即可 |

- 额度不足 → 429 + `Retry-After`，前端应提示"手动录入"，不能伪装成识别失败。
- 失败/超时也计数（防止重试绕过预算），因此"当天 20 次"不等于"20 次成功"。
- Neon 免费额度按 CU-hour 与存储计；**30 秒轮询会让数据库长期活跃**，演示结束后应停止设备轮询或放宽间隔。
- 费用查看：MiMo 控制台看调用量与余额；Neon 控制台看 CU-hours；Render 看实例状态与带宽。

---

## 6. 备份与恢复

```bash
# 备份（只导数据，不含角色）
pg_dump "$DATABASE_URL" --no-owner --no-privileges -Fc -f timesync-$(date +%Y%m%d-%H%M).dump

# 恢复到隔离库后验证，再决定是否切换
createdb timesync_restore
pg_restore --no-owner --no-privileges -d timesync_restore timesync-YYYYMMDD-HHMM.dump
python -m app.migrate --status      # DATABASE_URL 指向隔离库
```

验收要点：四个身份、任务、计划版本、会议、设备凭据、AI 台账都在；`/api/ready` 正常；恢复库上跑一次 agenda 读取与一次写操作。**恢复演练不要覆盖线上库。**

---

## 7. 回滚

1. **应用回滚**：Render 控制台回退到上一个部署；数据库不需要回滚（版本 1/2 只新增表，旧代码会忽略）。
2. **迁移回滚**（仅在确认要清理时）：先备份，再
   ```sql
   DROP TABLE IF EXISTS ai_usage, device_tokens, sandbox_sessions;
   DELETE FROM schema_migrations WHERE version=2;
   ```
3. **配置回退到本机演示**：`DEMO_MODE=true`、`SANDBOX_MODE=false`，并确认服务不再公网可达。
4. **关闭管理接口**：删除 `ADMIN_TOKEN`，管理路由立即返回 503。

---

## 8. 日志与排障

- 记录内容：时间、路径、状态码、耗时、脱敏错误类型。不记录 `Authorization`、Key、完整 DSN、原始截图、模型完整请求。
- 常见错误：
  - `401 沙箱会话已过期` → 正常过期，前端重新进沙箱。
  - `401 设备凭据已过期/已撤销` → 管理员重新签发并替换设备配置。
  - `403 设备凭据只允许读取日程` → 设备端误调了写接口，属预期拒绝。
  - `413` → 截图过大或被中间层截断，提示手动录入。
  - `429` → 额度或并发限制，按提示重试时间处理。
  - `503` + `/api/ready` 非 200 → 数据库或迁移问题，先修基础设施，不要改业务代码。

---

## 9. 部署记录（执行者填写）

| 项目 | 结果 | 时间 | 执行人 |
|---|---|---|---|
| Neon 项目与地域 | | | |
| Render 服务与子域名 | | | |
| `/api/health` | | | |
| `/api/ready`（schema_version） | | | |
| `python -m app.bootstrap --fixtures` | | | |
| 重启/重新部署后数据仍在 | | | |
| 冷启动耗时 | | | |
| 备份文件位置 | | | |
| 恢复演练结果 | | | |
| 设备凭据签发与撤销 | | | |
| AI 额度实测 | | | |
