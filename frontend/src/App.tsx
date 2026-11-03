import { requestId } from "./requestId";
import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  Plus,
  CalendarDays,
  LayoutDashboard,
  ListTodo,
  Layers3,
  WandSparkles,
  RefreshCw,
  Users,
  ChevronRight,
  Check,
  Clock3,
  ShieldCheck,
  Bell,
  Upload,
  FileText,
  X,
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  Settings2,
  LogOut,
  Menu,
  Sparkles,
} from "lucide-react";
import {
  Data,
  Button,
  Badge,
  Empty,
  Modal,
  md,
  hm,
  ScheduleList,
  SolveResult,
  Changes,
} from "./ui";
import Assistant from "./Assistant";
import QQCenter from "./QQCenter";
import Calendar from "./Calendar";
import Team from "./Team";
import AISettings from "./AISettings";
import FreeTimePanel from "./FreeTimePanel";
import TimetableImport from "./TimetableImport";
import { TaskForm, ExtractPanel, RepairPanel, Settings } from "./Forms";
import {
  ApiFailure,
  type AuthConfig,
  type AuthSession,
  fetchAuthConfig,
  fetchDemoAccounts,
  loadAuth,
  remainingMinutes,
  sandboxLogin,
  sandboxLogout,
  saveAuth,
} from "./auth";
const pages = [
  { id: "home", name: "概览", icon: LayoutDashboard },
  { id: "tasks", name: "DDL 管理", icon: ListTodo },
  { id: "calendar", name: "个人日历", icon: CalendarDays },
  { id: "schedule", name: "计划工作台", icon: WandSparkles },
  { id: "team", name: "多人协调", icon: Users },
  { id: "qq", name: "QQ 消息", icon: Bell },
  { id: "assistant", name: "AI 助手", icon: Sparkles },
];
const titles: Record<string, [string, string]> = {
  qq: ["QQ 通知", "授权收录、AI识别、核对确认，与个人排程相连。"],
  assistant: ["问清安排，再确认改变。", "查询真实日程，让每次修改都有依据。"],
  home: ["日程概览", "查看日程、近期截止与待处理事项。"],
  tasks: [
    "任务与截止时间",
    "从一条通知开始，把模糊的信息变成可执行的任务。",
  ],
  calendar: ["我的日历", "课程、专注时间和会议，都有自己的位置。"],
  schedule: [
    "计划工作台",
    "在真实约束下安排任务，把改动控制在最小。",
  ],
  repair: ["变化来了，计划跟得上。", "加入突发事件，先比较，再确认新的安排。"],
  team: ["多人时间协调", "只共享忙闲，保留每个人的私人日程。"],
};
export default function App() {
  const [page, setPage] = useState("home"),
    // One session object instead of a bare token: the kind decides whether
    // logout must call the server, and expires_at drives the countdown.
    [auth, setAuth] = useState<AuthSession | null>(() => loadAuth()),
    [authConfig, setAuthConfig] = useState<AuthConfig | null>(null),
    [signingIn, setSigningIn] = useState(false),
    [accounts, setAccounts] = useState<Record<string, string>>({}),
    [me, setMe] = useState<Data | null>(null),
    [state, setState] = useState<Data | null>(null),
    [meetings, setMeetings] = useState<Data[]>([]),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [loading, setLoading] = useState(false),
    [working, setWorking] = useState(false),
    [mobile, setMobile] = useState(false),
    [assistantOpen, setAssistantOpen] = useState(false),
    [calendarFocus,setCalendarFocus] = useState<{date:string;revision:number}|null>(null),
    [planMode, setPlanMode] = useState<"plan" | "repair">("plan"),
    [taskEdit, setTaskEdit] = useState<Data | "new" | null>(null),
    [extractOpen, setExtractOpen] = useState(false),
    [settings, setSettings] = useState(false),
    [aiSettings, setAISettings] = useState(false),
    [timetableOpen, setTimetableOpen] = useState(false),
    [planResult, setPlanResult] = useState<Data | null>(null),
    [repairResult, setRepairResult] = useState<Data | null>(null),
    [version, setVersion] = useState<Data | null>(null),
    [sessionLeft, setSessionLeft] = useState<number | null>(null);
  const assistantDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = assistantDialog.current; if (!dialog) return;
    if (assistantOpen && !dialog.open) { dialog.showModal(); dialog.focus(); }
    if (!assistantOpen && dialog.open) dialog.close();
  }, [assistantOpen, me?.id]);
  const token = auth?.token ?? "";
  const currentToken = useRef(token);
  currentToken.current = token;
  async function api(
    path: string,
    method = "GET",
    body?: unknown,
    form = false,
  ): Promise<any> {
    if (!navigator.onLine) throw new Error("当前离线，请恢复网络后重试；没有提交操作。");
    const response = await fetch("/api" + path, {
      cache: "no-store",
      method,
      headers: {
        ...(token ? { Authorization: "Bearer " + token } : {}),
        ...(method !== "GET" ? { "Idempotency-Key": path.startsWith("/v1/assistant/proposals/") ? "assistant-confirm:" + path.split("/")[4] : requestId() } : {}),
        ...(!form && body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
      },
      body:
        body === undefined
          ? undefined
          : form
            ? (body as FormData)
            : JSON.stringify(body),
    });
    let data: any = null;
    try {
      data = await response.json();
    } catch {
      // non-JSON error page: build a readable message below
    }
    if (!response.ok) {
      const detail =
        typeof data?.detail === "string"
          ? data.detail
          : JSON.stringify(data?.detail ?? response.status);
      // 401 means the credential is gone (expired/revoked/server restarted
      // with a fresh database): drop it so the login screen comes back
      // instead of looping on a dead token.
      if (response.status === 401 && token) endSession(false);
      throw new ApiFailure(detail, response.status, data?.code);
    }
    return data;
  }
  async function refresh() {
    const authToken = token;
    const user = await api("/me");
    const [s, m] = await Promise.all([
      api(`/users/${user.id}/state`),
      api("/meetings"),
    ]);
    if (currentToken.current !== authToken) return;
    setMe(user);
    setState(s);
    setMeetings(m);
  }
  async function run(action: () => Promise<void>) {
    setError("");
    setWorking(true);
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败，请重试");
    } finally {
      setWorking(false);
    }
  }
  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 5000);
  }
  function applyAuth(session: AuthSession | null, message = "") {
    setMobile(false);
    setAssistantOpen(false);
    setCalendarFocus(null);
    saveAuth(session);
    currentToken.current = session?.token ?? "";
    setAuth(session);
    setError(message);
    setMe(null);
    setState(null);
  }
  /** Local sign-out. `remote` true also tells the server to revoke the session. */
  async function endSession(remote = true) {
    const current = auth;
    if (remote && current?.kind === "session" && current.token)
      await sandboxLogout(current.token);
    applyAuth(null);
  }
  async function signInWithSandbox(member: string) {
    setSigningIn(true);
    try {
      applyAuth(await sandboxLogin(member));
    } catch (e) {
      setError(e instanceof Error ? e.message : "登录失败，请重试");
    } finally {
      setSigningIn(false);
    }
  }
  function login(value: string) {
    // Manual token entry and the local demo-account buttons land here.
    if (!value) {
      endSession();
      return;
    }
    applyAuth({ token: value, kind: "manual", user: null, expires_at: null });
  }
  function navigate(id: string) {
    if (id === "assistant") { setAssistantOpen(true); setMobile(false); return; }
    if (id === "repair") { setPage("schedule"); setPlanMode("repair"); }
    else { setPage(id); if (id === "schedule") setPlanMode("plan"); }
    setMobile(false);
  }
  useEffect(() => {
    // Which login flow is offered is decided by the server, never by the UI.
    fetchAuthConfig().then((config) => {
      setAuthConfig(config);
      if (!config) setError("后端未连接，请检查启动终端。");
      else if (config.demo_mode)
        fetchDemoAccounts()
          .then(setAccounts)
          .catch(() => setError("后端未连接，请检查启动终端。"));
    });
  }, []);
  useEffect(() => {
    // Sandbox sessions expire: refresh the remaining-minutes label regularly.
    if (auth?.kind !== "session") return;
    const timer = window.setInterval(
      () => setSessionLeft(remainingMinutes(auth.expires_at)),
      30000,
    );
    setSessionLeft(remainingMinutes(auth.expires_at));
    return () => window.clearInterval(timer);
  }, [auth]);
  useEffect(() => {
    if (!token) {
      setMe(null);
      setState(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setState(null);
    setAssistantOpen(false);
    setRepairResult(null);
    setPlanResult(null);
    setTaskEdit(null);
    setAISettings(false);
    setTimetableOpen(false);
    setExtractOpen(false);
    setVersion(null);
    refresh()
      .catch((e) => {
        if (alive) {
          setError(e.message);
          setMe(null);
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [token]);
  useEffect(() => {
    const recover = () => { if (token) refresh().catch(e => setError(e.message)); };
    window.addEventListener("online",recover);
    return () => window.removeEventListener("online",recover);
  }, [token]);
  useEffect(() => { document.body.dataset.authenticated = me ? "true" : "false"; }, [me]);
  const brand = (
    <>
      <span className="brand-icon">
        <Layers3 size={25} />
      </span>
      <strong>
        TimeSync<em>时聚</em>
      </strong>
    </>
  );
  if (!me || !state)
    return (
      <div className="login">
        <div className="brand">{brand}</div>
        <div className="login-card">
          <span className="eyebrow">YOUR TIME, IN SYNC</span>
          <h1>好的计划，从这里相聚。</h1>
          <p>理解通知，安排任务，找到大家共同的时间。</p>
          {loading ? (
            <p className="busy">
              <LoaderCircle className="spin" />
              正在连接你的时间空间…
            </p>
          ) : (
            <>
              <div className="demo-note">
                <ShieldCheck size={17} />
                {authConfig?.sandbox_mode
                  ? `共享演示沙箱 · 会话有效期 ${authConfig.session_ttl_minutes ?? 180} 分钟`
                  : "四人合成数据 · 本地演示 · 2026.11.02–11.08"}
              </div>
              <div className="login-members">
                {authConfig?.sandbox_mode
                  ? (authConfig.members ?? []).map((m) => (
                      <button
                        key={m.id}
                        disabled={signingIn}
                        onClick={() => signInWithSandbox(m.id)}
                      >
                        <span className={"avatar " + m.id}>{m.id}</span>
                        <b>
                          {m.name}
                          <small className="member-id">成员 {m.id}</small>
                        </b>
                        <small>
                          {signingIn ? (
                            <LoaderCircle className="spin" size={13} />
                          ) : (
                            "进入沙箱 "
                          )}
                          {!signingIn && <ArrowUpRight size={13} />}
                        </small>
                      </button>
                    ))
                  : Object.entries(accounts).map(([m, t]) => (
                      <button key={m} onClick={() => login(t)}>
                        <span className={"avatar " + m}>{m}</span>
                        <b>成员 {m}</b>
                        <small>
                          进入演示 <ArrowUpRight size={13} />
                        </small>
                      </button>
                    ))}
              </div>
              {authConfig?.sandbox_mode && authConfig.notice && (
                <p className="sandbox-notice">{authConfig.notice}</p>
              )}
              <details>
                <summary>使用独立访问令牌</summary>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    login(new FormData(e.currentTarget).get("token") as string);
                  }}
                >
                  <input
                    name="token"
                    aria-label="访问令牌"
                    type="password"
                    required
                    placeholder="输入服务端签发的令牌"
                  />
                  <Button type="submit">登录</Button>
                </form>
              </details>
            </>
          )}
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button
                onClick={() => {
                  login("");
                  setError("");
                }}
              >
                重新登录
              </button>
            </div>
          )}
        </div>
        <small className="login-footer">
          AI 理解信息 · 约束优化安排时间 · 你的确认决定变更
        </small>
      </div>
    );
  const s = state,
    u = me;
  const pending = meetings.filter(
    (m) =>
      m.status === "pending" &&
      m.invitations.some(
        (i: Data) => i.member_id === u.id && i.status === "pending",
      ),
  );
  const planned = new Set(s.schedule.map((r: Data) => r.task_id));
  const risk = s.tasks.filter(
    (t: Data) =>
      !planned.has(t.id) ||
      +new Date(t.deadline) < +new Date(u.window_start) ||
      !s.plan_valid,
  );
  const confirmed = meetings.filter((m) => m.status === "confirmed");
  const recent = [...s.tasks].sort((a, b) =>
    a.deadline.localeCompare(b.deadline),
  );
  async function generate() {
    await run(async () => {
      const r = await api("/plans", "POST");
      setPlanResult(r);
      await refresh();
      notify(
        ["optimal", "feasible"].includes(r.status)
          ? "个人计划已保存为新版本。"
          : "未找到可行计划，请查看冲突信息。",
      );
    });
  }
  async function saveTask(data: Data) {
    await api(
      "/tasks" + (taskEdit && taskEdit !== "new" ? "/" + taskEdit.id : ""),
      taskEdit && taskEdit !== "new" ? "PUT" : "POST",
      data,
    );
    setTaskEdit(null);
    setExtractOpen(false);
    await refresh();
    notify("任务已保存，请生成计划以应用新约束。");
  }
  const openImport = () => {
    setPage("tasks");
    setExtractOpen(true);
  };
  return (
    <div className="shell">
      <aside className={"sidebar " + (mobile ? "show" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("home");
          }}
        >
          {brand}
        </a>
        <div className="workspace-label">
          个人工作空间 <span>DEMO</span>
        </div>
        <nav aria-label="主导航">
          {pages.map((p) => (
            <button
              key={p.id}
              className={(page === p.id || (p.id === "assistant" && assistantOpen)) ? "active" : ""}
              aria-label={p.id === "assistant" ? "打开AI助手" : undefined}
              onClick={() => navigate(p.id)}
            >
              <p.icon size={19} />
              <span>{p.name}</span>
              {p.id === "repair" && <i className="nav-dot" />}
              {p.id === "team" && pending.length > 0 && (
                <small>{pending.length}</small>
              )}
            </button>
          ))}
        </nav>
        <button className="sidebar-install" onClick={()=>window.dispatchEvent(new Event("timesync-install"))}>安装 TimeSync 到桌面</button>
        <div className="sidebar-bottom">
          <span className={"avatar " + u.id}>{u.id}</span>
          <div>
            <b>{u.name}</b>
            <small>
              演示成员 {u.id} · 私人空间
              {sessionLeft !== null && (
                <em className={sessionLeft <= 10 ? "session-low" : undefined}>
                  {sessionLeft <= 0
                    ? "会话已到期，正在退出…"
                    : ` · 会话剩余 ${sessionLeft} 分钟`}
                </em>
              )}
            </small>
          </div>
          <button
            title="退出登录"
            aria-label="退出登录"
            disabled={working}
            className="icon-button"
            onClick={() => endSession()}
          >
            <LogOut size={16} />
          </button>
        </div>
      </aside>
      {mobile && (
        <div className="sidebar-shade" onClick={() => setMobile(false)} />
      )}
      <nav className="mobile-bottom-nav" aria-label="手机底部导航">{["home","calendar","tasks","schedule","team","qq","assistant"].map(id=>{const p=pages.find(p=>p.id===id)!;return <button key={id} className={(id==="assistant"?assistantOpen:page===id&&!assistantOpen)?"active":""} onClick={()=>navigate(id)} aria-label={p.name} aria-current={page===id?"page":undefined}><p.icon size={21}/><span>{({home:"概览",calendar:"日历",tasks:"任务",schedule:"计划",team:"协同",qq:"QQ",assistant:"AI"} as Record<string,string>)[id]}</span></button>;})}</nav>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label="打开导航"
              onClick={() => setMobile(true)}
            >
              <Menu />
            </button>
            <span>我的空间</span>
            <ChevronRight size={13} />
            <b>{pages.find((p) => p.id === page)?.name}</b>
          </div>
          <div className="top-actions">
            {u.ai_configuration_allowed && (
              <button
                className="btn secondary"
                onClick={() => setAISettings(true)}
              >
                项目 AI 管理
              </button>
            )}
            <span className="timezone">
              <i className="live-dot" />
              上海时间 UTC+8
            </span>
            <button
              className="icon-button notification"
              aria-label="查看待确认邀请"
              onClick={() => navigate("team")}
            >
              <Bell size={19} />
              {pending.length > 0 && <i />}
            </button>
            <span className={"avatar small-avatar " + u.id}>{u.id}</span>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <h1>{titles[page][0]}</h1>
              <p>{titles[page][1]}</p>
            </div>
            <div
              className={
                "heading-actions " +
                (page === "calendar" ? "calendar-actions" : "")
              }
            >
              {page === "home" ? (
                <>
                  <Button secondary onClick={() => setSettings(true)}>
                    <Settings2 size={16} />
                    时间设置
                  </Button>
                  <Button onClick={openImport}>
                    <Plus size={17} />
                    导入通知
                  </Button>
                </>
              ) : page === "tasks" ? (
                <>
                  <Button secondary onClick={openImport}>
                    <Upload size={16} />
                    识别通知
                  </Button>
                  <Button onClick={() => setTaskEdit("new")}>
                    <Plus size={17} />
                    手动创建
                  </Button>
                </>
              ) : page === "calendar" ? (
                <>
                  <Button secondary onClick={() => setSettings(true)}>
                    <Settings2 size={16} />
                    课程与可用时间
                  </Button>
                  <Button onClick={() => setTimetableOpen(true)}>
                    <Upload size={16} />
                    课表截图导入
                  </Button>
                </>
              ) : null}
            </div>
          </div>
          <div className="demo-banner workspace-context">
            <span>
              <span className="demo-tag">演示空间</span>{" "}
              {authConfig?.sandbox_mode ? "共享演示沙箱 · 合成数据" : "四人联调身份"} · 计划窗口 {md(u.window_start)}–{md(u.window_end)}
            </span>
            <span>{page === "schedule" ? "生成、修复与版本统一管理" : "上海时间 UTC+8"}</span>
          </div>
          {error && (
            <div className="alert error" role="alert">
              <AlertTriangle size={18} />
              <span>{error}</span>
              <button aria-label="关闭错误" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {working && (
            <div className="processing" role="status">
              <LoaderCircle size={16} className="spin" />
              正在处理，请稍候…
            </div>
          )}
          {page === "home" && (
            <>
              <div className="metrics">
                {[
                  {
                    label: "待完成任务",
                    value: s.tasks.length,
                    unit: "项",
                    hint: "所有已确认的 DDL",
                    icon: ListTodo,
                    tone: "green",
                  },
                  {
                    label: "已安排专注时间",
                    value: s.schedule
                      .reduce(
                        (n: number, r: Data) =>
                          n + (+new Date(r.end) - +new Date(r.start)) / 3600000,
                        0,
                      )
                      .toFixed(1),
                    unit: "小时",
                    hint: !s.plan ? "尚未生成任务计划" : s.plan_valid
                      ? "当前计划满足硬约束"
                      : "计划需要重新校验",
                    icon: Clock3,
                    tone: "blue",
                  },
                  {
                    label: "需要留意",
                    value: risk.length,
                    unit: "项",
                    hint: risk.length
                      ? "约束变化或尚未安排"
                      : "当前任务均已安排",
                    icon: AlertTriangle,
                    tone: "orange",
                  },
                  {
                    label: "小组会议",
                    value: confirmed.length,
                    unit: "场",
                    hint: pending.length
                      ? `${pending.length} 场邀请待确认`
                      : "已获全体成员确认",
                    icon: Users,
                    tone: "purple",
                  },
                ].map((m) => (
                  <div className="metric card" key={m.label}>
                    <div className="metric-top">
                      <span>{m.label}</span>
                      <span className={"metric-icon " + m.tone}>
                        <m.icon size={17} />
                      </span>
                    </div>
                    <div className="metric-value">
                      {m.value}
                      <small>{m.unit}</small>
                    </div>
                    <div className="metric-hint">
                      <i className={"tiny-dot " + m.tone} />
                      {m.hint}
                    </div>
                  </div>
                ))}
              </div>
              <div className="home-grid">
                <section className="card calendar-card">
                  <div className="section-heading">
                    <div>
                      <h2>
                        日程一览{" "}
                        
                      </h2>
                      <p>
                        {!s.plan ? "显示你的课表；添加任务并设置可用时段后可生成计划。" : s.plan_valid
                          ? "安排已经就位，留出时间专注当下。"
                          : "旧计划受约束变化影响，请重新生成。"}
                      </p>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => navigate("calendar")}
                    >
                      完整日历 <ArrowUpRight size={15} />
                    </button>
                  </div>
                  <Calendar state={s} me={u} meetings={meetings} compact />
                </section>
                <div className="home-right">
                  <section className="card">
                    <div className="section-heading">
                      <h2>
                        近期截止 <span className="count">{recent.length}</span>
                      </h2>
                      <button
                        className="icon-button"
                        aria-label="全部任务"
                        onClick={() => navigate("tasks")}
                      >
                        <ArrowUpRight size={17} />
                      </button>
                    </div>
                    <div className="deadline-list">
                      {recent.slice(0, 4).map((t, i) => (
                        <button key={t.id} onClick={() => setTaskEdit(t)}>
                          <div
                            className={
                              "deadline-date " + (i === 0 ? "urgent" : "")
                            }
                          >
                            <strong>{Number(t.deadline.slice(8, 10))}</strong>
                            <small>{Number(t.deadline.slice(5, 7))} 月</small>
                          </div>
                          <div>
                            <b>{t.title}</b>
                            <small>
                              {hm(t.deadline)} 截止 · {t.duration_minutes / 60}{" "}
                              小时
                            </small>
                          </div>
                          <i className={"priority-pip p" + t.priority} />
                        </button>
                      ))}
                      {!recent.length && <Empty text="没有待完成任务" />}
                    </div>
                    <button className="card-footer-button" onClick={openImport}>
                      <Plus size={15} />
                      从课程通知添加任务
                    </button>
                  </section>
                  <section className="sync-card">
                    <div className="sync-top">
                      <span className="sync-orbit">
                        <Users size={22} />
                      </span>
                      <Badge>多人协调</Badge>
                    </div>
                    <h2>找到共同空档</h2>
                    <p>
                      四人忙闲自动求交，
                      <br />
                      全员确认后，会议才会确定。
                    </p>
                    <div className="avatar-stack">
                      {"ABCD".split("").map((m) => (
                        <span key={m} className={"avatar " + m}>
                          {m}
                        </span>
                      ))}
                      <small>4 位演示伙伴</small>
                    </div>
                    <button onClick={() => navigate("team")}>
                      找个共同时间 <ArrowRight size={16} />
                    </button>
                  </section>
                </div>
              </div>
              <section className="card next-card">
                <span className="metric-icon green">
                  <WandSparkles size={22} />
                </span>
                <div>
                  <h2>
                    {pending.length
                      ? "有新的邀请，等你确认"
                      : "让临时变化，也有从容的答案。"}
                  </h2>
                  <p>
                    {pending.length
                      ? `${pending.length} 场会议等待你的答复。`
                      : "新增突发事件，先查看影响，再确认修复方案。"}
                  </p>
                </div>
                <Button
                  secondary
                  onClick={() => navigate(pending.length ? "team" : "repair")}
                >
                  {pending.length ? "查看邀请" : "调整计划"}
                  <ArrowUpRight size={15} />
                </Button>
              </section>
            </>
          )}
          {page === "tasks" && (
            <>
              <div className="import-callout">
                <span className="big-icon">
                  <FileText size={26} />
                </span>
                <div>
                  <h2>通知里藏着的 DDL，交给时聚整理</h2>
                  <p>
                    粘贴文字或上传截图 → 校验字段与原文证据 → 由你确认后保存。
                  </p>
                </div>
                <Button secondary onClick={openImport}>
                  开始识别
                  <ArrowRight size={16} />
                </Button>
              </div>
              <section className="card">
                <div className="section-heading">
                  <h2>
                    我的任务 <span className="count">{s.tasks.length}</span>
                  </h2>
                  <span className="subtle">优先级在满足硬约束后参与优化</span>
                </div>
                <div className="table-scroll">
                  <table className="task-table">
                    <thead>
                      <tr>
                        <th>任务 / 提交要求</th>
                        <th>截止时间</th>
                        <th>预计耗时</th>
                        <th>优先级</th>
                        <th>安排状态</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {recent.map((t) => (
                        <tr key={t.id}>
                          <td data-label="任务">
                            <b>{t.title}</b>
                            <small>
                              {t.requirements || "未填写提交要求"}
                              {t.dependencies.length > 0 &&
                                ` · ${t.dependencies.length} 个前置任务`}
                            </small>
                          </td>
                          <td data-label="截止时间">
                            {md(t.deadline)}
                            <small>{hm(t.deadline)} · UTC+8</small>
                          </td>
                          <td data-label="预计耗时">{t.duration_minutes} 分钟</td>
                          <td data-label="优先级">
                            <span className={"priority-label p" + t.priority}>
                              {["", "低", "中", "高"][t.priority]}
                            </span>
                          </td>
                          <td data-label="安排状态">
                            <Badge
                              status={
                                planned.has(t.id) && s.plan_valid
                                  ? "confirmed"
                                  : "pending"
                              }
                            >
                              {planned.has(t.id) && s.plan_valid
                                ? "已安排"
                                : "待排程"}
                            </Badge>
                          </td>
                          <td data-label="操作">
                            <button
                              className="text-button"
                              onClick={() => setTaskEdit(t)}
                            >
                              编辑
                              <ArrowUpRight size={14} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!s.tasks.length && (
                    <Empty text="导入通知，或手动创建第一个任务。" />
                  )}
                </div>
              </section>
            </>
          )}
          {page === "calendar" && (
            <section className="card calendar-card">
              <div className="section-heading">
                <div>
                  <h2>个人日程</h2>
                  <p>
                    {!s.plan ? "当前显示上传的课表，尚未生成任务计划。" : s.plan_valid
                      ? "当前计划有效"
                      : "展示旧计划，请重新排程更新。"}
                  </p>
                </div>
                <Badge>UTC+8</Badge>
              </div>
              <Calendar key={calendarFocus?.revision??0} state={s} me={u} meetings={meetings} focusDate={calendarFocus?.date} />
            </section>
          )}
          {page === "schedule" && <div className="planning-toolbar"><div role="tablist" aria-label="计划操作"><button role="tab" aria-selected={planMode==="plan"} onClick={()=>setPlanMode("plan")}>生成计划</button><button role="tab" aria-label="突发事件与修复" aria-selected={planMode==="repair"} onClick={()=>setPlanMode("repair")}>动态修复</button></div><button className="btn secondary" onClick={()=>setSettings(true)}><Settings2 size={16}/>时间设置</button></div>}
          {page === "schedule" && planMode === "plan" && (
            <>
              <section className="card optimizer-card unified-optimizer">
                <div><h2>按现有约束生成计划</h2><p>自动避开课程与会议，满足DDL和依赖，优先保留原有安排。</p>
                  <details className="solver-explanation"><summary>排程依据</summary><p>以15分钟为单位连续安排；优化顺序为改动任务数、移动距离、短碎片、优先级。不可行时保留旧计划并展示原因。</p></details>
                </div>
                <Button disabled={working} onClick={generate}><WandSparkles size={17}/>生成并采用计划</Button>
              </section>
              {planResult && <SolveResult result={planResult} />}
              <FreeTimePanel key={u.id} api={api} onApplied={refresh} onResult={r=>setPlanResult(r.scheduling)}/>
            </>
          )}
          {page === "schedule" && planMode === "repair" && (
            <RepairPanel
              key={u.id}
              result={repairResult}
              busy={working}
              state={s}
              onPreview={(data) =>
                run(async () =>
                  setRepairResult(
                    await api("/disruptions/preview", "POST", data),
                  ),
                )
              }
              onCommit={(data) =>
                run(async () => {
                  setRepairResult(await api("/disruptions", "POST", data));
                  await refresh();
                  notify("突发事件与修复结果已保存。");
                })
              }
            />
          )}
          {page === "schedule" && <details className="plan-history"><summary>当前安排 · {s.versions.length}个历史版本</summary>              <div className="two-columns wide-left">
                <section className="card">
                  <div className="section-heading">
                    <h2>当前安排</h2>
                    <Badge status={s.plan_valid ? "feasible" : "pending"}>
                      {s.plan_valid ? `版本 #${s.plan?.id}` : "待更新"}
                    </Badge>
                  </div>
                  <ScheduleList items={s.schedule} />
                </section>
                <section className="card">
                  <div className="section-heading">
                    <h2>版本记录</h2>
                    <Layers3 size={18} />
                  </div>
                  <div className="versions">
                    {s.versions.map((v: Data) => (
                      <button
                        key={v.id}
                        onClick={() =>
                          run(async () =>
                            setVersion(await api(`/plans/${v.id}`)),
                          )
                        }
                      >
                        <div>
                          <b>版本 #{v.id}</b>
                          <Badge status={v.status} />
                        </div>
                        <p>{v.reason}</p>
                        <small>
                          {md(v.created_at)} {hm(v.created_at)} ·{" "}
                          {v.changes.length} 项变更
                        </small>
                      </button>
                    ))}
                  </div>
                </section>
              </div>
</details>}
          {page === "qq" && <QQCenter api={api} onApplied={refresh} onNavigate={navigate}/>}
          {page === "team" && (
            <Team
              key={u.id}
              me={u}
              meetings={meetings}
              accounts={accounts}
              busy={working}
              api={api}
              run={run}
              refresh={refresh}
              login={login}
              notify={notify}
            />
          )}

        </main>
      </div>
      <dialog ref={assistantDialog} className="assistant-drawer" aria-label="时聚AI助手" tabIndex={-1} onCancel={()=>setAssistantOpen(false)} onClose={()=>setAssistantOpen(false)}>
        <Assistant key={token} api={api} open={assistantOpen} onClose={()=>setAssistantOpen(false)} onNavigate={(id,date)=>{if(id==="calendar"&&date)setCalendarFocus(prev=>({date,revision:(prev?.revision??0)+1}));setAssistantOpen(false);navigate(id);}} onApplied={async()=>{setPlanResult(null);setRepairResult(null);await refresh();}}/>
      </dialog>
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={18} />
          {toast}
        </div>
      )}
      {taskEdit && (
        <Modal
          title={taskEdit === "new" ? "创建任务" : "编辑任务"}
          close={() => setTaskEdit(null)}
        >
          <TaskForm
            tasks={s.tasks}
            initial={taskEdit === "new" ? undefined : taskEdit}
            busy={working}
            onSave={(data) => run(() => saveTask(data))}
          />
        </Modal>
      )}
      {extractOpen && (
        <Modal title="从课程通知提取 DDL" close={() => setExtractOpen(false)}>
          <ExtractPanel
            tasks={s.tasks}
            busy={working}
            request={(form) => api("/extract", "POST", form, true)}
            onSave={(data) => run(() => saveTask(data))}
          />
        </Modal>
      )}
      {aiSettings && (
        <Modal title="MiMo API 接入" close={() => setAISettings(false)}>
          <AISettings api={api} onChanged={refresh} />
        </Modal>
      )}
      {timetableOpen && (
        <Modal title="课表截图识别与确认" close={() => setTimetableOpen(false)}>
          <TimetableImport
            api={api}
            me={u}
            initialWeek={s.timetable_imports?.find((r: Data) => r.course_count > 0)?.week_start}
            onSaved={async () => {
              await refresh();
              setTimetableOpen(false);
              setCalendarFocus(null);
              setPage("calendar");
              notify(
                "课表已导入，已切换到对应周。请核对本周的排程窗口与可用时段。",
              );
            }}
          />
        </Modal>
      )}
      {settings && (
        <Modal title="课程与可用时间" close={() => setSettings(false)}>
          <Settings
            onImport={() => {
              setSettings(false);
              setTimetableOpen(true);
            }}
            state={s}
            me={u}
            busy={working}
            onWindow={(data) =>
              run(async () => {
                await api("/settings/window", "PUT", data);
                await refresh();
                notify("排程窗口已更新。");
              })
            }
            onAdd={(kind, data) =>
              run(async () => {
                await api("/" + kind, "POST", data);
                await refresh();
                notify("时间约束已保存。");
              })
            }
            onDelete={(kind, id) =>
              run(async () => {
                await api(`/constraints/${kind}/${id}`, "DELETE");
                await refresh();
              })
            }
          />
        </Modal>
      )}
      {error && (taskEdit || settings || extractOpen) && (
        <div className="toast error-toast" role="alert">
          <AlertTriangle size={17} />
          {error}
        </div>
      )}
      {version && (
        <Modal title={`计划版本 #${version.id}`} close={() => setVersion(null)}>
          <div className="version-summary">
            <Badge status={version.status} />
            <p>{version.reason}</p>
            {version.diagnostics.map((d: string) => (
              <div className="alert warning" key={d}>
                {d}
              </div>
            ))}
          </div>
          <ScheduleList items={version.schedule || []} />
          {version.changes.length > 0 && <Changes changes={version.changes} />}
        </Modal>
      )}
    </div>
  );
}
