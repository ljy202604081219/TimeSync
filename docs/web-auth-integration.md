# Web 登录与权限接入说明（给②）

现状：本机开发仍用 `GET /api/demo/accounts` 的四个演示令牌；公网部署关闭该入口，改用**短时沙箱会话**。③ 已实现接口，② 需要接界面。

---

## 1. 两种模式

| 模式 | 开关 | 前端行为 |
|---|---|---|
| 本机演示 | `DEMO_MODE=true` | 保持现状：读 `/api/demo/accounts`，选中成员后用其令牌请求 |
| 公网沙箱 | `DEMO_MODE=false` + `SANDBOX_MODE=true` | 不再有永久令牌；进入页面先建会话 |

`DEMO_MODE=false` 时 `/api/demo/accounts` 返回 404，`LEGACY_TOKEN_AUTH` 随之为 false，旧令牌全部失效。

---

## 2. 进入沙箱

```http
POST /api/sandbox/sessions
Content-Type: application/json

{"member": "A"}       // A/B/C/D，默认 A
```

响应（`docs/contracts/sandbox-session.example.json`）：

```json
{
  "token": "<只出现这一次>",
  "kind": "session",
  "scope": ["agenda:read","sandbox","web:read","web:write"],
  "user": {"id":"A","name":"林同学"},
  "issued_at": "2026-10-30T21:12:20+08:00",
  "expires_at": "2026-10-30T23:12:20+08:00",
  "expires_in_seconds": 10800,
  "notice": "共享演示沙箱：其他体验者可能修改同一份合成数据；请勿填写真实个人信息。"
}
```

前端做法：

1. 存内存（或 `sessionStorage`），**不要**写进 URL、localStorage 长期保存或日志。
2. 后续所有请求带 `Authorization: Bearer <token>`。
3. 页面显著位置显示 `notice`，明确"共享演示沙箱，其他体验者可能修改同一份合成数据"。

查询剩余时间：

```http
GET /api/sandbox/session     → {"kind":"session","remaining_minutes":176,...}
```

到期前 10 分钟提示"演示会话即将结束"；到期后按钮变为"重新进入"。

主动退出：

```http
DELETE /api/sandbox/session  → {"revoked":true,...}
```

---

## 3. 401 / 403 处理

| 场景 | `detail` 关键字 | 前端行为 |
|---|---|---|
| 会话过期 | `沙箱会话已过期` | 清本地令牌，弹"重新进入演示沙箱" |
| 会话被撤销 | `已退出或被撤销` | 同上 |
| 设备凭据误用 | `设备凭据只允许读取日程` | 不应出现在 Web 端；出现即前端错误 |
| 无权限 | `不能读取或修改其他成员` | 提示切换身份 |

401 不要自动无限重试；一次"重新建会话 + 重放当前请求"即可，再失败就让用户点按钮。

---

## 4. 与③有关的界面调整

1. **隐藏不适用的配置入口**：云端 `DEMO_MODE=false`，`/api/ai/settings`、`/api/ai/test-and-save`、`/api/ai/demo` 会返回 403（沙箱会话也不允许配置模型）。前端应在非本机模式下隐藏"模型设置"页签，而不是让用户点出 403。
2. **AI 额度提示**：`GET /api/ai/quota` 返回
   ```json
   {"global":{"limit":20,"used":3,"remaining":17},"actor":{"limit":5,"used":3,"remaining":2},"resets_in_seconds":12345}
   ```
   额度用完时后端返回 429 + `Retry-After`，界面应引导"手动录入"，不能显示成"AI 识别失败，请重试"。
3. **设备状态页（可选）**：`GET /api/devices` 返回本人设备元数据（无 token/hash）。文案必须写"最近一次请求时间"，**不能**写"屏幕已同步"——服务器无法证明屏幕亮没亮。
4. **上传失败**：整包超过 8 MB 时后端在解析前返回 413（`{"detail":"请求体超过 8.0 MB 上限…"}`），提示压缩截图或手动录入。

---

## 5. 自测清单

- [ ] `DEMO_MODE=true` 本机：原六页流程不变
- [ ] `DEMO_MODE=false` + `SANDBOX_MODE=true`：能进沙箱、能完成任务→排程→修复→会议全流程
- [ ] 手动把会话改成过期（或等 TTL）：401 → 一键重进
- [ ] 429：提示手动录入，而不是"失败重试"
- [ ] 413：提示压缩/手动录入
- [ ] 设备页只列本人设备，页面文案不承诺屏幕状态
