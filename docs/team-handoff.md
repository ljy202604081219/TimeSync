# 时聚核心开发与团队接口交接

本轮归属①全栈核心开发：业务算法、AI 适配、模块联动、API 契约和核心回归测试。没有部署公网，没有实现 ESP32 固件或硬件驱动，也没有改版 UI、制作海报。新增接口不改变现有数据库表，保留原来的前端接口。

最新交接以根目录 [HANDOFF.md](../HANDOFF.md) 为入口：硬件尚未购买，商品图仅供采购核对；第一阶段只读显示、自动轮播，不开发触摸、按钮或设备端日程写入。

③的具体开工顺序、数据库事务兼容、认证/设备凭据、安全与Render＋Neon部署门槛见 [backend-implementation-roadmap.md](backend-implementation-roadmap.md)；其中新增接口均为待实施设计。

后续更新：默认初始化只保留四人联调身份，不再生成样例日程。`GET /api/timetable/profile` 返回用户给定的湖大11节作息；`POST /api/timetable/extract` 新增可选表单字段 `use_school_schedule`，默认true。识别行新增可选 `period_start`、`period_end` 和服务端生成的 `time_basis`；原有导入确认字段不变。晚课及清理说明见 [huda-timetable.md](huda-timetable.md)，OpenAPI已重新导出。

## 分工边界

| 成员 | 可立即开始的工作 | 与①的接口 |
|---|---|---|
| ① 全栈核心（你） | 排程正确性、识别确认流程、会议状态机、模块联动、接口兼容与缺陷修复 | 维护后端契约及算法测试，接收明确复现步骤 |
| ② UI 与产品测试 | 现有六页交互、响应式、日历展示、测试/调研/验收、海报与答辩 | 复用原 API；新日历可调用 `/api/v1/agenda`，使用合成样例先开发；不要在 UI 自行计算最终排程或会议状态 |
| ③ 后端与云服务 | 托管部署、持久化数据库、真实认证、密钥配置、设备凭据绑定与撤销、跨设备同步策略 | 保留接口字段与状态语义；SQLite 写事务适配、账号及设备 token 生命周期由该成员负责，涉及业务语义变更再与①确认 |
| ④ ESP32 软件 | 联网、请求、JSON 解析、缓存、轮询、业务界面联调 | 使用下方只读日程 API；先解析 `contracts/agenda.example.json`，网络与凭据准备好再连接服务 |
| ⑤ ESP32 硬件 | 候选CYD板的采购资料/版本核对；到货后驱动、装配、供电与硬件排查 | 与④交接验证后的板卡配置和显示条件；首阶段不做触摸，后端不依赖屏幕驱动或引脚 |

候选板为 ESP32-2432S028R（CYD）2.8 英寸触摸屏开发板，当前尚未购买。商品图显示双USB外观，控制器、版本和GPIO仍待核实。本轮接口为通用 HTTP/JSON，与具体屏幕驱动无关；未在实物上验证，不能把接口测试当作硬件验收。

## 已有核心业务与入口

- AI：`backend/app/ai.py` 是模型调用入口；MiMo 使用独立适配，Key 仅由后端读取。`POST /api/extract` 处理通知，`POST /api/timetable/extract` 处理课表。提取不直接保存。没 Key 时返回明确的 `mode=demo`，截图不会伪装成 OCR 成功。
- DDL：用户编辑、确认后才调用 `POST /api/tasks`；不明确的日期/时间保持空值，提交任务时必须补齐。
- 课表：提取 → `/api/timetable/preview` → 人工确认 → `/api/timetable/import`；导入需要预览返回的快照，过期返回409。课表截图当前按用户选择的一周导入，不擅自推断整个学期。
- 排程：`scheduler.py` 只做确定性约束优化；`plans.py` 负责当前约束、版本和变更。`POST /api/plans` 是用户主动生成并保存；窗口最多14天、60项任务、15分钟单位，任务连续安排。
- 修复：`POST /api/disruptions/preview` 不落库；确认时 POST `/api/disruptions`，带预览的 `expected_plan_id`、`expected_snapshot`。旧预览被拒绝时重新预览，不自动覆盖。
- 协调：区间求交只输出忙闲；邀请必须由所有必要成员分别答复。最后一次同意时复查固定约束、计算个人修复；有人失败不会提交部分个人计划。改期使用新邀请与 `replaces_id`，原会议在全员同意新时间前保持有效。

完整机器可读字段见 [OpenAPI](contracts/openapi.json)；运行中的交互文档为 `/docs`。导出命令（在项目根目录）：

```powershell
Push-Location backend
..\.venv\Scripts\python.exe export_contracts.py
Pop-Location
```

该脚本只写契约文件，使用独立临时数据库和合成数据，不调用外部模型、不读取现有用户日程、不输出访问令牌。

## 统一日程读取接口 v1

```http
GET /api/v1/agenda?start=2026-11-04T00%3A00%3A00%2B08%3A00&end=2026-11-06T00%3A00%3A00%2B08%3A00&limit=12
Authorization: Bearer <由服务端分配的本人访问令牌>
```

`+08:00` 的加号必须 URL 编码为 `%2B`，优先使用客户端 query 参数编码器。默认省略 start/end 时读取服务器上海时区今天零点至次日零点；指定时必须一起提供且带时区，最多7天。`limit` 为1–50，默认12。不能传 owner/user_id 来切换身份，服务端只从令牌确定本人。

返回体可直接使用 [合成日程样例](contracts/agenda.example.json)。

| 字段 | 客户端约定 |
|---|---|
| schema_version | 当前为1；增加可选字段不破坏兼容，客户端应忽略不认识的字段；不兼容变更另开版本 |
| revision | 内容版本，不是计划 ID；对应当前查询和用户的返回内容，用于判断是否重绘 |
| server_time / timezone | 带时区 ISO8601；时区固定 Asia/Shanghai；不依赖设备字符串的本地时区默认值 |
| user_id | 当前鉴权身份，用于排查错误绑定；不能据此请求别人的私人日程 |
| plan | `id` 是最后一次成功版本；`latest_attempt_status` 可能是之后失败的排程；二者不可混淆 |
| plan.valid / repair_needed | 约束失效时旧任务仍可查看，但应显示“待重新排程”；不能当作已生效新安排 |
| events | 课表、不可用时段、突发事件、个人任务、已确认会议、DDL，按时间排序；只含本人及本人会议 |
| event_total / truncated | 返回数量不足时明确提示；需要更多可增大 limit，或缩小日期范围分段读取；没有静默丢弃保证 |
| pending_invitations / pending_total | 本人尚未答复的待确认邀请，独立于日期范围，最多返回12条，避免漏掉范围外的待办；更多可读取 `/api/meetings` |

事件 `kind`：`course`、`unavailable`、`disruption`、`task`、`meeting`、`deadline`。`source_id` 是对应课表/任务/会议实体 ID，不要把不同 kind 的数字 ID 混用。`id` 是实例标识，同一每周课程在不同日期有不同 id。标题最长80个字符，仅用于显示；完整名称和证据仍用原业务接口读取。

事件 `status`：固定安排为 `fixed`，有效计划任务为 `scheduled`，旧失效计划任务为 `stale`，已确认会议为 `confirmed`，截止点为 `due`。DDL 是一个时间点，`start=end`；其他事件为半开区间 `[start,end)`。事件与请求区间有交集就返回其真实起止时间，可能跨过查询边界；DDL 在 end 恰好相等时归下一段，避免重复。

待确认/被拒绝/需要重排的会议不会当作确定会议放进 events。设备若要展示待办，仅展示 pending_invitations；首阶段设备只读，会议答复在Web完成，不开发触摸确认。③需提供可撤销且权限受限的设备身份；不能把当前全权限演示令牌固化在对外发布的固件里。

### 轮询与错误

第一次读取200，保存响应 `ETag`，后续请求带 `If-None-Match`。304无响应体，沿用本地内容。ETag 使用弱比较，忽略仅 server_time 的变化；需要校时可定期不带该头请求。鉴权仍在304判断前执行。

可从30秒轮询作为联调起点，结合实际服务限制调整；这是客户端建议，本轮没有新增定时推送服务。断网保留最后一份数据并标记“离线/上次同步时间”，不要把请求失败显示为“今天没有安排”。401停止重试并提示重新绑定，422检查范围/时区/字段，5xx退避重试。写请求遇到网络不确定时重试必须沿用原幂等键。

默认只有127.0.0.1可访问；ESP32上的 localhost 指向设备本身。由③提供局域网/云端可达的 API Base URL、访问凭据、HTTPS 证书验证方案。HTTPS 私有 token 不等于 MiMo Key；板端不能保存模型 Key。不要以关闭证书校验作为正式交付方案。

## 共用写入约定与状态

所有现有业务写操作需要 `Authorization` 和 `Idempotency-Key`（1–120字符）。同一用户、同键同内容返回原结果；同键不同内容409。AI 提取和修复预览是 POST 但不保存业务数据，不要求幂等键。本地 AI 配置是只供本机管理员的独立管理入口，不能作为设备或公网配置接口。

- HTTP 200 不一定表示求解成功，必须再读 `status`。`optimal`/`feasible` 才有可用新计划，`infeasible` 为不可行，`unknown` 为预算内未找到可行解，`invalid` 为输入不适用。
- `diagnostics` 保持现有字符串数组供 UI 展示；本轮新增 `conflicts` 数组供结构化提示，含 code、task_ids，部分含 required_minutes/available_minutes。按 code 不认识时回退显示 diagnostics。
- code：planning_limits、duplicate_task、missing_dependency、dependency_cycle、no_contiguous_slot、dependency_deadline、deadline_capacity、combined_constraints、solver_timeout。这些是必要条件诊断及求解结果，不是最小不可满足约束集。
- 排程软目标仍依次为改动任务数、移动距离、短碎片、优先级；低层目标不能牺牲已证明的高层目标。本轮四个求解阶段共用默认3秒求解预算，超时保留已找到并独立验证的可行结果。预处理、数据库和网络时间不包含在该求解预算内。
- 会议状态：pending → confirmed / declined / needs_reschedule；成功改期后的旧会议为 superseded。个人计划详情只可本人读取；协调响应不提供他人的任务内容。

## 联调验收顺序

1. ②/④先用 OpenAPI 与合成 JSON 开发，不等待③部署，不使用真实学生截图或令牌作为测试素材。
2. 本地启动后获取本人演示身份；使用显式演示日期2026-11-04至11-06读取 agenda，避免“今天”与固定演示日期不同造成空列表。
3. ①运行 `python run.py --check` 和 `backend/demo_flow.py`；②记录UI问题时附页面、输入、预期/实际、接口状态码与脱敏响应。
4. 新增固定事件使旧任务冲突，确认 `plan.valid=false`、任务标记 stale；修复预览不改变 agenda；确认修复后版本和内容更新。
5. 发起四人会议：待确认只在待办；全员确认后进入 events，冲突任务完成联动修复；拒绝时不产生确定会议。
6. ③接入正式认证后复测跨用户401/403、设备解绑与 token 撤销、同键重试、云端重启持久化。硬件到货后④/⑤共同验证屏幕显示与断网重连，首阶段不验收触摸功能。

## 给③的部署前阻塞项与尚未完成项

本轮没有把本地程序变成公网可安全使用的多用户产品。③需接手真实身份隔离与设备凭据、关闭公开演示凭据入口、平台 Secret、数据库持久化和备份；迁移 PostgreSQL 前适配当前 SQLite `BEGIN IMMEDIATE` 与锁机制，不能仅改 DATABASE_URL。依赖安全升级、上传总体积/调用频率/模型费用限制和 HTTPS 配置也需要在公开访问前完成验证。此前审计发现的风险未因新增接口自动消失。

任务完成归档/拆分、真实教务同步、推送通知、跨时区、多设备写冲突UI均未在本轮新增。新增只读接口不提供设备注册/绑定、后台推送、固件OTA或硬件测试。接口的现有 token 是全账户权限；③实现设备限权前仅供可信本地联调，不可作为公网设备安全设计。
