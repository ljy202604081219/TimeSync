# 登录闭环契约（③ → ②）

适用版本：后端 ③ B4。所有示例值均为合成演示数据。

## 0. 总原则

1. **UI 永远不猜测登录方式**：先读 `GET /api/auth/config`，按返回值渲染。
2. 凭据统一放 `Authorization: Bearer <token>` 请求头。
3. **401 一律等于"请重新登录"**。响应体带稳定 `code`，UI 按 code 分支，不要解析中文文案。
4. 401 响应带 `WWW-Authenticate: Bearer` 响应头（符合 RFC 9110）。
5. 前端 localStorage 键：`timesync-auth`（JSON：token/kind/user/expires_at）。
   兼容旧键 `timesync-token`：读取时迁移，写入时两键同步。

## 1. 发现登录方式

```
GET /api/auth/config        （无需认证）
```

云端部署（DEMO_MODE=false, SANDBOX_MODE=true）：

```json
{
  "demo_mode": false,
  "sandbox_mode": true,
  "legacy_token_auth": false,
  "members": [{"id": "A", "name": "林同学"}, {"id": "B", "name": "陈同学"},
               {"id": "C", "name": "王同学"}, {"id": "D", "name": "许同学"}],
  "session_ttl_minutes": 180,
  "login_path": "/api/sandbox/sessions",
  "logout_path": "/api/sandbox/session",
  "credential_header": "Authorization: Bearer <token>",
  "notice": "共享演示沙箱：其他体验者可能修改同一份合成数据；请勿填写真实个人信息。"
}
```

- `members` 只有 `id` 与 `name`，绝不包含令牌或哈希。
- 本地演示（DEMO_MODE=true）则 `sandbox_mode=false`、`login_path=null`，
  UI 走旧 `/api/demo/accounts` 流程（仅限本机）。

## 2. 登录

```
POST /api/sandbox/sessions
Content-Type: application/json
{"member": "A"}
```

200 返回（样例见 docs/contracts/sandbox-session.example.json）：

```json
{
  "token": "<只在本次响应出现一次>",
  "kind": "session",
  "scope": ["agenda:read", "sandbox", "web:read", "web:write"],
  "user": {"id": "A", "name": "林同学"},
  "expires_at": "2026-10-31T00:12:20+08:00",
  "expires_in_seconds": 10800,
  "notice": "…"
}
```

错误码：`sandbox_disabled`（404，未开启）、`unknown_member`（404）、
`sandbox_full`（429，带 `Retry-After`）。

## 3. 会话信息与退出

```
GET    /api/sandbox/session   → {kind, scope, user, expires_at, remaining_minutes, notice}
DELETE /api/sandbox/session   → {revoked: true, id, revoked_at}
```

- 退出后原令牌**立即**失效（服务端撤销，不是仅本地删除）。
- 对已过期会话调用 DELETE 返回 401，属正常；前端本地清理即可。

## 4. 401/403/429 错误码表

| code | HTTP | 含义 | UI 行为 |
|---|---|---|---|
| `auth_missing` | 401 | 没带 Bearer 头 | 跳登录页 |
| `auth_invalid` | 401 | 令牌不存在（例如服务端换库） | 清除本地凭据，跳登录页 |
| `session_expired` | 401 | 沙箱会话过期 | 提示"会话已过期"，跳登录页 |
| `session_revoked` | 401 | 会话已退出/被撤销 | 同上 |
| `device_expired` / `device_revoked` | 401 | 设备凭据失效 | 设备端重新拉取配置或报警 |
| `device_forbidden` | 403 | 设备凭据调用了写接口 | 不重试；检查凭据类型 |
| `not_a_session` | 403 | 会话管理接口收到非会话凭据 | 同上 |
| `sandbox_disabled` | 404 | 该部署未开启沙箱登录 | 隐藏沙箱入口 |
| `unknown_member` | 404 | 成员不存在 | 刷新 config 后重试 |
| `sandbox_full` | 429 | 活跃会话数达上限 | 提示稍后再试，遵守 `Retry-After` |
| `rate_limited` | 429 | AI 调用额度用尽 | 提示明日再试，遵守 `Retry-After` |
| `payload_too_large` | 413 | 请求体超过上限 | 提示压缩截图 |
| `busy` | 503 | 业务写锁等待超时 | 一两秒后自动重试一次 |

所有错误体保持 `{"detail": "<中文说明>", "code": "<上述标识>"}`；
旧代码只读 `detail` 不受影响。

## 5. 前端参考实现

`frontend/src/auth.ts`（本仓库）已实现上述契约，`frontend/src/App.tsx` 接入：

- 登录页按 `config` 渲染：沙箱模式显示成员按钮 → `sandboxLogin(member)`；
  本地模式显示演示账号；两者都保留"独立令牌"兜底入口。
- `api()` 收到 401 自动清除本地凭据并回到登录页，错误信息直接展示 `detail`。
- 侧边栏"退出登录"按钮 → `DELETE /api/sandbox/session` → 清本地存储。
- 侧边栏显示"会话剩余 N 分钟"，每 30 秒刷新，≤10 分钟变橙色。

② 可以直接复用 `auth.ts`，也可以按同一契约重写。

## 6. 验收清单（浏览器操作流程）

1. 打开首页 → 未登录 → 显示 4 个成员按钮（来自 config）。
2. 点击成员 A → 进入主界面，侧边栏出现"会话剩余约 180 分钟"。
3. 任意写操作正常；等 3 小时（或让管理员把该会话 expires_at 改到过去）后
   点击任意操作 → 自动回到登录页，提示会话过期。
4. 点"退出登录" → 回到登录页；用旧令牌直接调 API → 401 `session_revoked`。
5. 关闭浏览器重开 → 仍在登录页有效期内则免登录（localStorage 会话恢复），
   过期则自动 401 → 登录页。
