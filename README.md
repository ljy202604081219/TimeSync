# TimeSync 时聚

面向大学生的时间信息确认、个人约束排程、多人时间协调与动态计划修复 Web App。React / TypeScript / Vite / Tailwind CSS + Python / FastAPI / SQLAlchemy / SQLite 或 PostgreSQL + Google OR-Tools CP-SAT。

**①核心开发交接入口：[HANDOFF.md](HANDOFF.md)**。包含已完成功能、现有接口、四位成员接收边界、验收方法与已知缺口；硬件尚未购买，首阶段只读显示。

**③后端与云服务交接入口：[docs/backend-03-handoff.md](docs/backend-03-handoff.md)**。数据库适配、沙箱会话、设备只读凭据、AI 限额、容器与 Render 配置；部署步骤见 [docs/deployment.md](docs/deployment.md)。

最近两轮的合并更新记录见 [CHANGELOG.md](CHANGELOG.md)，包含核心接口、排程优化、湖大作息、数据清理及实际验证结果。

这是可运行的本地应用：任务、固定时间、计划版本、事件、会议和邀请状态保存在数据库；求解器与区间算法实际执行。默认只创建**四名本地联调身份**，不生成样例课程、任务、计划或可用时段；课表由本人导入，未对接教务系统。无 API Key 时是明确标注的规则演示，**不执行截图 OCR，不冒充真实 AI**。

应用新建数据库和演示重置时不生成内置课程。下文涉及预设课表的算法验收场景通过独立测试或 `demo_flow.py` 的专用合成夹具运行，不代表新安装的默认课表。源码 ZIP 包含 README 和 docs 下的全部 Markdown 文档，排除本机 API Key、运行数据库和依赖目录。

湖大课表导入已默认配置用户给定的11节作息；19:00开始的课程默认至21:35，可在确认页修改。首页优先展示上传课表所在周。最新清理范围、完整时间表及 **72项后端 + 4项前端** 验证见 [湖大课表与数据清理](docs/huda-timetable.md)。现有本地业务数据按用户要求只保留上传课程，API配置及登录身份保留；数据库备份未放入源码包。

## 核心开发与团队交接（2026-10-29）

①负责的核心改动及②③④⑤的接入边界见 [团队交接文档](docs/team-handoff.md)。新增 `GET /api/v1/agenda` 统一读取本人课表、任务、DDL、已确认会议和待确认邀请，支持有界范围、失效计划标记及 ETag/304；不改现有前端和数据库表。机器可读字段见 [OpenAPI](docs/contracts/openapi.json)，ESP32/前端可先使用 [合成日程 JSON](docs/contracts/agenda.example.json) 联调。

排程新增连续空档、DDL容量和依赖链诊断，四个优化阶段共用默认3秒求解预算。完整测试记录见 [核心交接验收](docs/core-handoff-validation.md)。云端部署、正式账号与设备凭据、固件、硬件驱动及UI美化由对应成员继续完成；当前新增接口不等同于这些工作已经交付。

## 快速启动

环境：Python 3.12、Node.js 22+，npm 或 pnpm；首次安装需要联网。已验证环境为 Windows、Python 3.12.9、Node 24.22.1、pnpm 11.25.0。

Windows 双击 `start.cmd`，或者在项目根目录运行：

```powershell
python run.py
```

脚本创建 `.venv`、安装固定版本依赖、复制 `.env.example` 为 `.env`、安装前端依赖、检查 TypeScript、构建前端并启动服务，健康检查成功后打开浏览器。

- 应用：<http://127.0.0.1:8000>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>
- Ctrl+C 停止服务，数据库保留。端口冲突时用 `python run.py --port 8001`。
- 登录选择 A/B/C/D；多人协调页可切换身份，模拟四人分别答复。

`start.ps1` 也可使用；系统限制 PowerShell 脚本时直接使用 `start.cmd`，无需更改执行策略。Codex 环境缺少系统 npm 时，启动器会检测已有的 bundled pnpm。依赖安装跳过生命周期脚本，esbuild 使用平台 optional dependency 中的二进制；本机已验证构建成功。

只做验收、不启动服务：

```powershell
python run.py --check
```

如已有独立 Python 环境，可传 `--python C:\path\to\python.exe`。`backend/requirements.txt` 固定直接依赖与原生兼容版本，`requirements.lock` 记录实际测试环境的完整依赖快照；前端使用 `pnpm-lock.yaml`。

## 开发方式

先从项目根目录完成 `python run.py --check`，然后在两个终端分别运行：

```powershell
# 后端终端，从项目根目录开始
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端终端，从项目根目录开始
cd frontend
pnpm exec vite --host 127.0.0.1
```

前端开发代理将 `/api` 转发给 8000。生产启动由 FastAPI 同源提供前端，不需要 CORS 放开。macOS/Linux 下使用 `.venv/bin/python`；这两种操作系统尚未实机验证。

## AI 配置与确认流程

### 小米 MiMo：在页面中接入

登录演示管理员 **A**，点击右上角 **MiMo 接入**。默认 Base URL 为 `https://api.xiaomimimo.com/v1`，视觉模型为 `mimo-v2.6-pro`。在本机页面的密码框中填写 Key，点击“测试连接并保存”。测试只发送合成文本，验证鉴权、模型调用和 JSON 输出，可能消耗少量额度；成功才写入本机 `.env` 并即时生效，无需重启。失败保留原配置。真实截图识别请在 DDL 页面另行上传核验。

Key 不回显、不存储在 localStorage 或业务数据库；配置接口只允许本机、同源的演示管理员 A 使用。可移除 Key 切回明确标注的演示模式。此入口是本地演示配置，不是生产多租户密钥管理。Token Plan 使用控制台提供的官方专属地址与配套 Key，不能混用普通按量 Key。切换地址必须重新填 Key。

官方依据：[MiMo 图片理解](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/multimodal-understanding/image-understanding)、[JSON 输出](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/structured-output)。MiMo 请求使用 api-key 鉴权、Base64 图片、关闭 thinking 的 JSON 输出并限制输出长度。自动化验收不发送真实付费请求；适配、故障和秘密保护用 mock 测试验证。

### 通过服务端环境配置

编辑根目录 `.env` 后重启后端：

```dotenv
AI_PROVIDER=mimo
AI_BASE_URL=https://api.xiaomimimo.com/v1
AI_MODEL=mimo-v2.6-pro
AI_API_KEY=你的密钥
DEMO_MODE=true
DATABASE_URL=sqlite:///./timesync.db
```

适配的是 OpenAI 兼容的 `POST /chat/completions` 接口，需支持 image_url 和 JSON object 响应。密钥仅存在服务端，不返回浏览器。模型选择由 API 提供商决定，示例模型名不保证所有兼容服务均支持。

DDL 管理 → 识别通知 → 粘贴文本/上传 PNG、JPEG、WebP（上限 6 MB）→ 提取结构化 JSON → 查看证据、修改字段与歧义 → 填写预计耗时 → 勾选人工确认 → 保存。没有完整日期和时间不会默认补成 23:59；多个日期或证据不一致时清空 deadline，要求人工确认。截图模糊或接口失败时可手动创建任务。

规则演示仅识别一处明确的 `2026年11月5日18:00` 等日期文本；自然语言解析能力有限。截图在演示模式下返回空字段和明确提示。**本轮核心交接没有调用真实外部视觉服务**；接口适配器与异常处理通过 mock 测试，实际识别质量需要使用者在配置模型后核验。

## 可复现演示

### 课表截图导入（新增）

个人日历 → **课表截图导入**；也可在“课程与可用时间”中点击“上传课表截图并识别”。支持整周 PNG / JPEG / WebP（6 MB以内）、本地预览、节次作息补充、视觉模型结构化提取、逐条编辑和勾选、目标周选择、重复与冲突预览、最终确认与数据库保存。原文证据和导入记录保存在本人名下。

1. 先在 MiMo 接入中配置可用的视觉 Key，再选择课表截图。
2. 截图中只有“第1–2节”时，默认按湖大作息换算成08:00–09:40；19:00开始默认到21:35。其他学校可取消“使用湖大默认作息”并补充实际时间；未识别到时间或节次时保持空白，不能直接导入。
3. 核对课程名、星期、开始结束、单双周、指定周次和停课规则，勾选目标周确实上课的课程。不需要的课程可取消勾选或删除，也可手动添加。
4. 选择目标周的周一，检查导入预览，核对已存在课程、固定时间冲突以及原任务影响；确认后仅追加该周的固定课程。
5. 返回智能排程重新生成计划，让任务避开新课表。旧任务版本保留；已确认会议不会被擅自移动。

导入成功会自动进入对应周的日历，不需要重新上传。个人日历可选择日期或已导入周，查看范围独立于排程窗口；若要为导入周安排任务，还需在“课程与可用时间”中设置该周的排程窗口与可用时段。原来的范围外课表不显示问题已修复，见 `docs/calendar-display-fix.md`。`python run.py --check` 也会执行前端日历回归测试。

**当前只导入选定的一周，不自动复制整个学期。** 这是为了避免把单双周与指定周次错误推广；学期起始日期、周次例外的自动推导尚未实现。无 API Key 时明确提示不做截图 OCR，返回空课程列表，仍可手动填写。识别不写数据库，确认前可修改；确认接口有幂等保护并拒绝过期预览。数据库启动时新增 timetable_imports 审计表，保留原有任务与课表。

API：`POST /api/timetable/extract`（multipart image/notes）、`POST /api/timetable/preview`、`POST /api/timetable/import`、`GET /api/timetable/imports`。识别和导入只作用于当前登录成员；导入记录不会向其他成员公开。自动化验收见 `docs/timetable-check-output.txt`，新增11个测试，合计44项通过；真实模型识别质量仍需用户实际截图核验。

### 原有完整流程

初始计划窗口：2026-11-02 08:00 至 2026-11-09 08:00（上海时间）。周历展示前七天。四人初始任务在周三 14:00–16:00、周四 09:00–10:30、周五 16:00–17:00；每人有独立课表。

1. 登录 A，在 DDL 管理中识别默认通知，检查“演示模式”标识、证据与日期；勾选确认保存。
2. 智能排程 → “生成并采用计划”。检查有效状态、硬约束、优化目标、版本记录。
3. 多人协调，将范围设为周三 13:00–20:00、时长 60 分钟、偏好时间 **2026-11-04 14:00**；计算共同空档并选择 14:00–15:00 发起邀请。个人任务在协调时作为可调整安排，不会泄露给伙伴。
4. A 确认，再依次切换 B、C、D 确认。前三人同意时仍为待确认，最后一人同意后才检查四人计划并确定会议。展开联动过程，查看任务调整数量；各身份进入智能排程可查看本人的修复版本。
5. 切回 A → 动态修复，录入“临时增加实验”，周三 **15:00–17:00** → 预览。对比原时间、新时间与变化原因 → 确认采用。初始种子下任务在会议确认后移到 15:00–17:00，此事件再次触发修复。
6. 想单独演示动态修复，可在未做步骤 3–4 的初始数据中直接使用默认周三 **14:00–16:00** 事件；只需移动实验报告。
7. 试验不可行：把某项 120 分钟任务截止改为 11/02 08:15，再生成计划。系统返回不可行诊断，旧计划显示待更新，不保存违反约束的安排。
8. 试验无共同空档：协调范围设为 11/02 08:00–12:00、60 分钟。显示缺席成员与协商备选，不能直接确认为全员会议。
9. 已确认会议只能由发起人“生成改期候选”，新邀请全员同意前原会议保持有效。若个人任务无法修复，会议进入 needs_reschedule，展示备选并重新邀请。

独立的自动演示在临时数据库执行同一条完整流程，不改变日常演示数据，也不依赖模型：

```powershell
cd backend
..\.venv\Scripts\python.exe demo_flow.py
```

结果写入 `docs/demo-flow.json`，包含提取模式、版本、会议状态转换、四人联动和修复变化；不包含令牌。

停止服务后，可以重置本地合成演示数据。重置前自动备份 SQLite 与对应演示令牌：

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.seed_demo --reset
```

不带 `--reset` 时只初始化空库，保留已有数据。重置后原浏览器令牌失效，退出并重新选择成员。

## 算法与一致性

- 时间采用含时区的 ISO 8601，入库规范化为 `+08:00`，区间是 `[start,end)`。固定时段和可用时段可按周重复展开；可用范围向内取整，任务时长为 15 分钟倍数。
- 每项任务为一个连续 interval，start 的合法整数域来自“可用时间减去课程、不可用时段、突发事件、已确认会议”。通过 NoOverlap、DDL 上界、依赖先后保证硬约束。
- 分阶段目标：已安排任务开始时间变化数量 → 总移动格数 → 任务间 15/30 分钟碎片数量 → 优先级加权开始时间。每阶段证明最优后锁定结果再求下一阶段。单线程、固定种子；每阶段最多 3 秒。若只得到可行解，标记 feasible 并停止优化低层目标，不宣称最优。
- 最多 14 天、60 项任务。首次没有找到可行解返回 unknown；已证明不存在解返回 infeasible。独立 `verify()` 再检查所有硬约束，验证失败禁止保存。
- 预览不写数据库；确认时比较旧计划 ID 和约束指纹，拒绝过期预览。确认事件和新版本在同一事务保存。不可行时保存事件及诊断版本，旧有效版本保留并在当前约束下重新标记有效性。
- 多人协调采用区间合并、相减和双指针求交，候选按不便人数、偏好时间距离、开始时间排序。无共同空档时按可参加人数展示协商备选。
- 会议状态：pending → confirmed / declined / needs_reschedule；被全员接受的新改期会议替代后，旧会议为 superseded。最后一次确认在写事务中重新检查固定日程、计算所有个人修复；任何人不可行时不提交部分个人计划。
- 写操作必须带 `Idempotency-Key`，服务端保存请求指纹和原响应。同键同内容返回原响应，同键不同内容返回 409。SQLite BEGIN IMMEDIATE 和唯一约束防止并发重复创建。

参考实现依据：[OR-Tools CP-SAT 官方 API](https://or-tools.github.io/docs/pdoc/ortools/sat/python/cp_model.html)、[FastAPI 安全工具](https://fastapi.tiangolo.com/reference/security/)。

## 数据与接口

```text
TimeSync/
├─ run.py / start.cmd / start.ps1
├─ .env.example
├─ backend/
│  ├─ app/
│  │  ├─ db.py / models.py / schemas.py
│  │  ├─ scheduler.py / intervals.py / plans.py
│  │  ├─ ai.py / coordination.py / main.py
│  │  └─ demo.py / seed_demo.py
│  ├─ tests/                 核心算法与 API 测试
│  ├─ demo_flow.py
│  └─ requirements.txt / requirements.lock
├─ frontend/
│  ├─ src/                   六个页面与统一设计样式
│  ├─ pnpm-lock.yaml
│  └─ dist/                  已构建静态资源
└─ docs/                     初检计划、验收报告、演示证据、截图
```

实体：User、Task、BusyInterval、Availability、ScheduledTask、PlanVersion、Disruption、Meeting、MeetingInvitation、RequestRecord（①）；SandboxSession、DeviceToken、AiUsage 与 schema_migrations 版本表（③新增，均为增量表）。包含用户/计划/任务/会议外键、owner 和时间索引、邀请和排程唯一约束；SQLite 开启外键与 WAL，PostgreSQL 使用连接池与 advisory lock。依赖 ID 保存为 JSON，在 API 边界检查归属、存在性与环路。读取使用显式排序，避免 PostgreSQL 顺序变化影响快照与 ETag。

主要 API（完整 schema 见 `/docs`）：

| API | 用途 |
|---|---|
| GET /api/demo/accounts | 仅演示模式可切换的本地身份凭据 |
| GET /api/me、/api/users/{id}/state | 本人资料与私人日程，其他身份返回 403 |
| GET /api/v1/agenda | 本人有界日程，供日历/设备读取；支持 ETag 与304 |
| POST /api/tasks、PUT /api/tasks/{id} | 人工确认保存与编辑任务 |
| POST /api/extract | 文本或 multipart 截图提取，不保存任务 |
| POST /api/busy、/api/availability | 固定约束和偏好配置 |
| PUT /api/settings/window | 排程窗口 |
| POST /api/plans、GET /api/plans/{id} | 生成版本、读取本人版本 |
| POST /api/disruptions/preview、/api/disruptions | 预览与确认修复 |
| POST /api/coordination/candidates | 只返回忙闲与协调结果 |
| POST /api/meetings、/api/meetings/{id}/respond | 发起邀请、本人答复 |
| GET /api/meetings/{id}/alternatives | 考虑当前个人计划生成会议备选 |
| PATCH /api/meetings/{id} | 明确拒绝直接修改会议时间 |

③ 新增（详见 `docs/backend-03-handoff.md` §4）：

| API | 用途 |
|---|---|
| POST /api/sandbox/sessions | 公网演示的短时沙箱会话；替代公开的演示令牌 |
| GET / DELETE /api/sandbox/session | 查询剩余时间 / 主动退出 |
| POST /api/admin/device-tokens、DELETE /api/admin/device-tokens/{id} | 管理员签发、撤销绑定 owner 的只读设备凭据 |
| GET /api/devices | 本人设备脱敏元数据（不含 token/hash） |
| GET /api/ai/quota | 当日 AI 用量与剩余额度 |
| GET /api/ready | 数据库连通性与 schema 版本；落后或不可用返回 503 |

## 验收与边界

实际结果见 `docs/validation.md`，覆盖任务书列出的 12 类场景。所有自动测试独立于真实模型。浏览器手工完成 DDL 确认、个人排程、动态修复与四身份会议确认。初检与实施顺序见 `docs/01-inspection-plan.md`。

已实现：六页界面、人工任务兜底、AI 适配与明确演示模式、CP-SAT 硬约束/分阶段软目标、前后修复对比、计划版本、四人忙闲求交、邀请状态机、个人计划联动、幂等与权限检查、数据库种子、启动/测试/演示脚本。

第一版限制和未实现项：

- 演示身份选择会公开本地四个合成身份的令牌，这用于演示登录，不是生产认证。默认仅监听 127.0.0.1；不要把 DEMO_MODE=true 直接暴露到公网。DEMO_MODE=false 会关闭演示入口；③ 已补短时沙箱会话与设备只读凭据作为公网入口，但注册、密码、SSO 与生产用户管理仍未实现。
- 未接真实教务、真实日历或邮件/推送；会议邀请仅在本应用内显示。
- 尚未用真实视觉 API Key 验证外部模型；不同兼容服务对图片/JSON 支持可能不同。规则演示只处理有限的明确格式；AI 提取仍需人工核对。
- 任务连续安排，不拆分，不支持“已完成”历史归档。时区固定上海。周历每次显示七天，可前后翻周；跨日事件在周历中的显示有限，算法仍按完整区间处理。
- 风险提示以未排程、约束失效和窗口内截止为依据，尚无概率风险模型。碎片目标只统计任务之间的短空档，不是完整的人类专注偏好模型。
- 不可行诊断可指出单任务连续空档不足、DDL前总容量不足、依赖循环与依赖链赶不上截止；其余组合不可行仍给约束类别提示，尚未提取最小不可满足约束集。
- SQLite 与进程内写锁适合本地四人演示；PostgreSQL 适配与版本化迁移已实现，但**尚未在真实 PostgreSQL 实例上运行**；大规模并发、审计与监控需要后续工程化。历史版本保存时间安排及变更说明；任务编辑后旧版本列表仍使用当前任务名称。
- 响应式 CSS 已实现，浏览器在本机桌面窗口验证；尚未在真实手机与不同浏览器中全面测试。没有开展公网渗透测试或无障碍全面审计。

## ③ 后端基础设施与云端（2026-10-30 接手）

已完成：SQLite/PostgreSQL 双后端引擎与连接池、跨后端写事务（SQLite `BEGIN IMMEDIATE` / PostgreSQL advisory lock）、版本化迁移与云端初始化命令、短时沙箱会话、设备只读凭据（`agenda:read`，可到期可撤销）、AI 全局预算与并发预检、请求体总量限制、`/api/ready` 就绪检查、Docker/Render 部署文件、依赖安全升级。

验证：`116 passed`（原 72 项 + 新增 44 项），前端 `tsc -b` 与 `vite build` 通过。详细改动、权限矩阵、未完成项见 **`docs/backend-03-handoff.md`**。

**尚未验证**：Docker 镜像构建、真实 PostgreSQL 运行、Render/Neon 实际部署与持久化重启——本机无 Docker、无 PostgreSQL、无云账号授权，不能对外声称云端已跑通。部署步骤见 `docs/deployment.md`；② 登录改造见 `docs/web-auth-integration.md`；④ 设备接入见 `docs/device-integration.md`。
