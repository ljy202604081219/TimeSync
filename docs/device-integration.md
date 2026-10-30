# 设备端接入说明（给④）

面向 ESP32 只读屏。**首阶段只读**：不发业务写请求、不做会议答复、不做触摸或按钮。

---

## 1. 凭据

设备不再使用任何人的登录令牌。管理员（③）签发一次性只读凭据：

```bash
curl -sS -X POST https://<service>.onrender.com/api/admin/device-tokens \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"owner_id":"A","label":"宿舍只读屏","ttl_days":7}'
```

响应（`docs/contracts/device-token.example.json`）：

```json
{
  "token": "<只出现这一次>",
  "id": "…", "owner_id": "A", "label": "宿舍只读屏",
  "scope": "agenda:read", "status": "active",
  "created_at": "2026-10-30T21:12:20+08:00",
  "expires_at": "2026-11-06T21:12:20+08:00",
  "revoked_at": null, "last_request_at": null, "ttl_days": 7
}
```

- 明文令牌**只出现一次**，服务端只存 SHA-256 哈希。
- 默认 7 天到期，可提前撤销；撤销或到期后下一次请求立即 401。
- 写入方式：USB/串口等可信本地配置写入 NVS，可替换、可轮换。**不要把个人登录令牌或 MiMo Key 编译进固件**；NVS 不等于加密存储，不要声称具备未经验证的物理防提取能力。

**权限边界**：该凭据只能 `GET /api/v1/agenda`。调 `/api/tasks`、`/api/meetings`、`/api/extract`、`/api/ai/*`、`/api/me`、`/api/devices` 一律 403。这是设计意图，不是 bug。

---

## 2. 请求

```http
GET /api/v1/agenda?limit=12 HTTP/1.1
Host: <service>.onrender.com
Authorization: Bearer <设备凭据>
If-None-Match: <上次响应的 ETag；首次不发送>
```

- 省略 `start`/`end` 读服务器上海时区的当天；显式范围必须同时提供、带时区、≤7 天。`+08:00` 在查询串里编码为 `%2B08%3A00`。
- `limit` 默认 12，最大 50；用 `event_total` 与 `truncated` 判断是否截断。
- 响应体结构见 `docs/contracts/agenda.example.json`，`schema_version=1`。

字段要点：

| 字段 | 含义 |
|---|---|
| `revision` | 内容版本（不是计划 ID），变了才需要重绘 |
| `server_time` | 服务器时间；**不参与** `revision`，304 不会返回新的 `server_time` |
| `events[].kind` | `course` / `unavailable` / `disruption` / `task` / `meeting` / `deadline` |
| `events[].status` | `fixed` / `scheduled` / `stale` / `confirmed` / `due` |
| `events[].title` | 已截到 80 字符，仍要按屏宽做 UTF-8 截断/换行 |
| `plan.valid=false` | 旧计划可能失效，任务显示为 `stale`（待修复），**不要**当成冲突 |
| `pending_invitations` | 只用于提示"请到网页处理"，**不进入**确定会议列表 |
| DDL | `start == end` 的时间点，不是零时长课程 |

---

## 3. 状态码处理

| 状态 | 处理 |
|---|---|
| 200 | 有数据。`events` 为空才是"当前范围暂无安排" |
| 304 | 无 JSON 体；保留上一份内容，**不要**清屏 |
| 401 | 凭据过期/撤销；显示"需要重新授权"，停止重试并等待人工更换 |
| 403 | 权限不足（调了只读以外的接口），属实现错误 |
| 422 | 参数不合法（范围/时区/limit），修参数，不要重试 |
| 429 | 频率/额度限制，按提示延后 |
| 超时 / 5xx / JSON 解析失败 | 保留上一份有效内容，标记"同步异常"；**不要**显示成空日程 |
| 冷启动（连接超时或长时间无响应） | 显示"正在连接"，恢复后自动重读；不要显示"暂无安排" |

弱网与恢复：指数退避（如 30s → 60s → 120s，上限 5 分钟），恢复后立即重读一次。演示期间可从 30 秒轮询起步；**长期 30 秒轮询会让免费数据库保持活跃**，非演示期间请放宽或停止。

---

## 4. 校时

- 响应头有 `Date`，正文有 `server_time`；但 304 不带新的 `server_time`。
- 因此校时只用于初次同步与漂移校正（例如每次 200 时记录差值），不要依赖每次请求都拿到时间。
- 设备应校验 HTTPS 证书，不关闭校验；不要为了联调开放公网端口。

---

## 5. 本地联调

```bash
# 电脑上：仅供同一可信局域网内的设备访问
python run.py --host 0.0.0.0 --port 8000

# 本机签发一张设备凭据（ADMIN_TOKEN 在 .env 中）
curl -sS -X POST http://127.0.0.1:8000/api/admin/device-tokens \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"owner_id":"A","label":"桌面调试","ttl_days":1}'

# 模拟设备读取（硬件到货前就先用这个验收）
curl -sS -i "http://<电脑局域网IP>:8000/api/v1/agenda?limit=4" \
  -H "Authorization: Bearer <设备凭据>"
```

- 设备请求必须指向电脑的**局域网地址**，不能用设备自己的 `localhost`。
- 硬件未到货前，用 HTTP 客户端完成同一凭据的模拟请求；**模拟通过**与**实物通过**要分别记录，不能混写。

---

## 6. 不能声称的事

- `last_request_at` 只表示服务器最近收到该凭据的请求，**不能证明屏幕已亮或内容已绘制**。没有设备回执时，网页侧不显示"屏幕同步成功"。
- 当前接口没有电量、Wi-Fi 信号、屏幕状态、细粒度冲突原因；不要自行编造这些字段。
- 首阶段没有设备端会议确认、任务修改、按钮或触摸接口。
