# ①全栈核心开发交接说明

整理日期：2026-10-30（上海时间）。交付代码为前两轮合并后的版本；本次只整理交接文档与归档，不修改业务代码、配置或运行数据。

> **③ 接手结果（2026-10-30 追加）**：[docs/backend-03-handoff.md](docs/backend-03-handoff.md)。数据库已支持 PostgreSQL 并有版本化迁移，新增沙箱会话与设备只读凭据、AI 限额与体积保护、容器与 Render 配置；新增 44 项自动测试（合计 116 项通过）。**Docker 构建、真实 PostgreSQL、Render/Neon 部署尚未执行**，不视为已完成。本文其余内容仍为①的原文，未改动。

## 1. 这次交出什么

交出可运行的Web业务核心、既有前后端代码、统一日程读取接口、接口契约与合成样例、自动测试、两轮实际验收记录和更新日志。

①继续负责业务规则解释、核心缺陷修复、接口语义协调和最终业务集成。云部署、数据库迁移、生产/设备认证由③接手；UI和产品验收由②接手；固件由④接手；板卡与硬件由⑤接手。

**硬件尚未购买。现有图片是候选商品资料，不是实物验证记录。第一阶段只读显示、自动轮播，不做触摸、按钮或设备端日程写入。**

## 2. 接收者先看这些文件

| 内容 | 文件或目录 |
|---|---|
| 本交接入口 | `HANDOFF.md` |
| 启动、配置、操作与已知限制 | `README.md` |
| 两轮合并日志 | `CHANGELOG.md` |
| 团队接口与状态约定 | `docs/team-handoff.md` |
| ③后端实现顺序、数据库/认证/设备与部署验收 | `docs/backend-implementation-roadmap.md` |
| OpenAPI | `docs/contracts/openapi.json` |
| 可直接解析的合成日程 | `docs/contracts/agenda.example.json` |
| 湖大作息响应样例 | `docs/contracts/timetable-profile.example.json` |
| 核心接口与算法验收 | `docs/core-handoff-validation.md`、`docs/core-check-output.txt` |
| 作息适配与清理验收 | `docs/huda-timetable.md`、`docs/huda-check-output.txt` |
| 独立演示 | `backend/demo_flow.py`、`docs/demo-flow.json` |

上述路径均相对于解压后的 `TimeSync/`。`docs/contracts/` 中的样例使用合成数据。

## 3. 已完成的核心与代码入口

| 功能 | 当前实现 | 主要文件 |
|---|---|---|
| DDL识别 | 文本/图片提取、JSON校验、原文证据、歧义提示、人工确认后保存、手动兜底 | `backend/app/ai.py`、`schemas.py`；前端 `Forms.tsx` |
| MiMo接入 | 后端独立适配、服务端Key、失败提示；无Key明确为规则演示 | `backend/app/ai.py`、`ai_config.py`；前端 `AISettings.tsx` |
| 课表导入 | 截图提取、湖大节次映射、编辑与冲突预览、确认后只导入选定周 | `backend/app/timetable.py`、`school_time.py`；前端 `TimetableImport.tsx` |
| 个人排程 | CP-SAT硬约束、分阶段软目标、结构化不可行诊断、超时处理、独立约束校验 | `backend/app/scheduler.py`、`plans.py` |
| 动态修复 | 预览不落库、快照防过期、确认后保存版本与时间变化 | `backend/app/main.py`、`plans.py`；前端 `Forms.tsx` |
| 多人协调 | 忙闲求交、候选排序、邀请/拒绝/全员确认、会议与个人计划联动 | `backend/app/intervals.py`、`coordination.py` |
| 统一日程读取 | 本人课程/任务/DDL/会议与待办、失效计划标记、ETag/304 | `backend/app/agenda.py`、`main.py` |
| 数据与写入保护 | SQLAlchemy实体、SQLite持久化、归属校验、幂等请求 | `backend/app/models.py`、`db.py`、`main.py` |

核心限制：15分钟排程单位、最多14天窗口及60项任务、任务连续安排、时区固定上海。任务完成归档/拆分、全学期课表推导、真实教务同步和推送尚未实现。

### 业务状态不可改错

- AI提取与课表识别不等于保存成功，必须经过人工确认。
- `optimal`/`feasible` 才是可用新计划；`infeasible` 是不可行；`unknown` 是预算内未找到可行解，不能改称不可行或成功。
- 修复确认使用预览返回的 `expected_plan_id`、`expected_snapshot`；409时重新预览，不自动覆盖。
- 会议 `pending` 只有必要成员全部同意后才能 `confirmed`；拒绝为 `declined`，约束不再满足时可为 `needs_reschedule`。
- 已确认会议改期需新邀请及全员重新确认；成功后旧会议为 `superseded`。硬件不调用答复或改期接口。
- 排程目标顺序保持：改动任务数、移动距离、短碎片、优先级；不得为了优先级破坏硬约束或高层目标。

## 4. 当前数据与环境边界

本次只读核对本地数据库：4个身份、12条上传课程、1条导入记录；任务、可用时段、计划版本、排程、会议、邀请、旧幂等记录均为0。

- 正常初始化只创建身份，不重新生成样例日程。准备演示任务时先配置目标周的排程窗口与可用时段。
- 本人的上传课程与AI配置保存在本机，交接包排除运行数据库、`.env`、访问令牌和私人备份。
- 接收者需自行配置Key；无Key仍可运行规则演示、手动创建和算法测试。
- 课表默认采用用户指定的11节作息；19:00开始的课程默认到21:35，可在确认页修改。完整时间表见 `docs/huda-timetable.md`。
- 云端竞赛使用独立合成数据，不直接复制本机上传课程和私人备份。
- 当前项目没有Git仓库、固件目录或云部署配置；这些不能当作已经交付的实现。

## 5. 接口交接

### 现有业务接口

| 接口 | 用途与接收者 |
|---|---|
| `GET /api/me`、`GET /api/users/{owner}/state` | ②读取本人资料及完整Web业务状态；不能跨身份读取私人日程 |
| `POST /api/tasks`、`PUT /api/tasks/{id}` | ②使用现有创建/编辑接口，③保持业务语义 |
| `POST /api/extract` | DDL文本/图片提取，返回后由用户确认保存 |
| `GET /api/timetable/profile` | ②读取湖大默认节次表 |
| `POST /api/timetable/extract`、`preview`、`import` | 课表提取→预览→确认；extract的 `use_school_schedule` 默认true |
| `POST /api/plans` | 主动生成并保存个人计划，需读响应中的求解status |
| `POST /api/disruptions/preview`、`POST /api/disruptions` | 先预览，再以快照确认修复 |
| `POST /api/coordination/candidates` | 返回必要的忙闲与候选，不返回他人私人任务内容 |
| `POST /api/meetings`、`POST /api/meetings/{id}/respond` | 网页会议邀请与本人答复 |
| `GET /api/v1/agenda` | ②/④共用的日程数据读取接口，③接入设备限权认证 |

所有现有业务写操作需要Bearer令牌和 `Idempotency-Key`；同键同内容返回原结果，同键不同内容409。AI提取、修复预览等不保存业务数据的POST不要求幂等键。设备阶段只读取日程。

### 给④的日程读取约定

```http
GET /api/v1/agenda?limit=12
Authorization: Bearer <本人访问令牌；设备专用凭据需③实现>
If-None-Match: <上次ETag；首次不发送>
```

- 省略start/end时读取服务器上海时区当天；显式范围必须一起提供、含时区且最多7天。`+08:00`放入查询参数时应编码为 `%2B08%3A00`。
- limit默认12、最多50；根据 `event_total` 与 `truncated` 展示截断提示，不能把截断当作完整日程。
- `schema_version=1`；`revision` 是内容版本，不是计划ID；时间为带 `+08:00` 的ISO8601字符串。
- events提供 `id`、`kind`、`source_id`、`title`、`start`、`end`、`status`。title最长80个字符，仍需按屏幕宽度处理UTF-8截断/换行。
- kind为course、unavailable、disruption、task、meeting、deadline；status为fixed、scheduled、stale、confirmed、due。
- DDL是 `start=end` 的时间点，不能误报为零时长课程；其余按 `[start,end)` 理解。
- `plan.valid=false` 时旧任务可能标为stale，应显示待修复；无任务且尚无计划时不要误报冲突。结合 `repair_needed`、`latest_attempt_status` 判断提示。
- 待确认邀请在 `pending_invitations`，只用于提示“请到网页处理”，不进入确定会议列表。
- 304无JSON体；沿用缓存。server_time不参与内容版本，304不会返回新的server_time，设备校时不能依赖每次304。
- 401提示重新授权；403表示无权限；422核对参数；超时、5xx、解析失败保留上一份有效内容并标为同步异常；空events的200才可显示“当前范围暂无安排”。
- 演示期间可从30秒轮询起步；最终频率、超时、重试与云端额度由③④联调确认。

**字段限制：** task事件目前没有独立的deadline属性；DDL通过查询范围内的deadline事件返回。下一任务可显示开始时间；若必须同时显示范围外DDL，由①确认最小字段扩展，不能假设现接口已返回全部任务DDL。接口也没有设备电量、Wi-Fi信号、物理屏幕状态或细粒度冲突原因，这些不应自行伪造。

## 6. 向四位成员分别交接

| 接收人 | ①现在交出的内容 | 接收者需要补齐 | 交接验收方式 |
|---|---|---|---|
| ② UI与产品测试 | 现有六页、业务API、状态语义、日志与测试证据 | 手机/电脑交互与日历完善、持续回归和Bug记录、设备状态页面需求；海报与答辩由②负责 | 按已有接口完成一条任务→排程→修复→会议流程；错误/空状态不把失败显示为成功 |
| ③ 云服务与数据库 | FastAPI服务、SQLAlchemy模型、SQLite实现、agenda和契约 | 延续Render同源服务+Neon路线；PostgreSQL事务兼容、安全依赖升级、认证、Key/限额、设备凭据及持久化 | 重启后数据保留；设备限权可撤销；原业务/幂等/归属测试通过；不改排程含义 |
| ④ 嵌入式软件 | agenda JSON样例、字段、缓存/错误约定 | JSON解析、中文显示、轮播、Wi-Fi/HTTPS、离线与恢复；先用模拟JSON开发 | 先证明样例解析与显示，再接真实读取接口；不发业务写请求；失联不显示成空日程 |
| ⑤ 嵌入式硬件 | 候选板型ESP32-2432S028R、只读显示需求、与驱动无关的数据契约 | 采购资料/版本核对、控制器与GPIO确认、供电/驱动/实物稳定性验证；尚未购买或验证实物 | 向④提供经实机验证的板卡配置及亮屏依据；首阶段不开发触摸/按钮 |

①保留业务模块的主责；③主责基础设施、认证和设备访问控制。②④不得在客户端另写一套最终排程或会议确认逻辑。⑤不需要等待云部署即可核对采购资料，④不需要等待云部署即可使用合成JSON开发。

### ③接手时必须知道的现状

完整实施顺序、建议新增接口、文件归属与验收条件见 [后端实现路线](docs/backend-implementation-roadmap.md)。其中拟新增的认证、设备和部署功能当前尚未实现。

1. 当前 `mutation()` 使用SQLite的 `BEGIN IMMEDIATE` 和进程内写锁，不能只改DATABASE_URL就宣称兼容PostgreSQL。
2. 当前Bearer对应完整用户身份，**没有设备只读scope、绑定、到期或撤销机制**。设备不能长期固化当前个人/演示登录令牌；③应扩展现有agenda认证，不重复实现日程数据投影。
3. `/api/demo/accounts` 在演示模式下公开四个身份凭据。`DEMO_MODE=false` 会关闭该入口，但当前没有替代的完整登录/注册流程；云端入口与Web登录要一起接手。
4. 本机AI配置接口有本机/同源/管理员限制；云端Key使用平台Secret，不能直接放开该管理入口。
5. 云端用户/设备身份初始化不能依赖本机 `.demo-tokens.json` 的临时文件持久化。
6. 依赖安全升级、总体上传限制、AI并发/频率/费用限制和持续运行检查仍需落实。没有现成设备状态接口；②如需展示“最近请求/同步状态”，字段由③提供，不能仅靠网页猜测设备是否亮屏。

## 7. 如何验收这份核心交接

在独立副本中验收，避免清空或回填用户现有课程：

```powershell
# 项目根目录：构建并验证
python run.py --check

# 正常启动
python run.py

# 已装好项目环境后，独立合成演示
Push-Location backend
..\.venv\Scripts\python.exe demo_flow.py
Pop-Location
```

交接门槛：

1. 接收者能完成安装、打开页面和API文档。
2. 在自己环境重跑测试并保存输出；历史记录不能代替接收环境结果。
3. 读取合成JSON，正确处理课程、任务、DDL、确定会议、待确认邀请及失效计划。
4. 完整演示使用临时数据库，按“规则提取/人工确认→排程→多人确认及任务修复→突发事件修复→agenda读取”走通。
5. 接收者记录环境、代码版本、用例、预期/实际、脱敏响应与复测结果；业务问题回①，UI回②，认证/部署回③，固件回④，板卡回⑤。

前两轮实际记录：第一轮59项后端与4项前端通过；第二轮累计72项后端与4项前端通过，均完成TypeScript及生产构建，存在1条已有TestClient弃用警告。**本次交接整理未重跑测试或真实模型请求**，以接收者新环境结果作为接收验收证据。

## 8. 后续改动如何对接①

- 保持现有接口路径、字段和状态语义；确需增加字段时，先给出界面/设备用途、示例和兼容方式，由①确认业务语义。
- ③修改认证/数据库，①修改业务计算；共享的 `main.py`、`models.py` 每次明确一个修改人，通过PR交叉评审，避免两人同时改同一片逻辑。
- 契约变更同步OpenAPI与合成样例，②④按同一版本开发。硬件相关未实现功能不得混入“已有接口”说明。
- ①最终接收四人的联调结果，负责业务整合和核心缺陷，不包揽部署、数据库迁移、固件、驱动、采购或宣传制作。

## 9. 可直接发到团队群的交接文字

> 我负责的时聚核心已经完成两轮开发，代码、接口、样例、日志和验收记录已放进交接包，请先读HANDOFF.md。统一日程入口是GET /api/v1/agenda，大家复用现有结构。②接UI与产品回归；③接Render+Neon、认证、安全和设备访问；④先用合成JSON做只读终端，再联调网络；⑤负责未购板卡的资料/版本核对及后续实物验证。首阶段不做触摸、按钮或设备写日程。我的后续职责是核心缺陷、业务接口协调和最终集成。72项后端、4项前端是历史验证记录，各自接收后请在自己的环境重跑，不将本机身份或模型密钥放入公开代码。
