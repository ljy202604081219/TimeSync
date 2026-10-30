import { useState } from "react";
import {
  Users,
  ShieldCheck,
  WandSparkles,
  ArrowUpRight,
  Check,
  RefreshCw,
  X,
} from "lucide-react";
import { Data, Button, Badge, Empty, iso, range, md, hm, labels } from "./ui";
type Props = {
  me: Data;
  meetings: Data[];
  accounts: Record<string, string>;
  busy: boolean;
  api: (path: string, method?: string, body?: unknown) => Promise<any>;
  run: (action: () => Promise<void>) => Promise<void>;
  refresh: () => Promise<void>;
  login: (token: string) => void;
  notify: (text: string) => void;
};
export default function Team({
  me,
  meetings,
  accounts,
  busy,
  api,
  run,
  refresh,
  login,
  notify,
}: Props) {
  const [result, setResult] = useState<Data | null>(null),
    [replacement, setReplacement] = useState<Data | null>(null),
    [meetingTitle, setMeetingTitle] = useState("小组学习讨论");
  return (
    <>
      <div className="coord-layout">
        <section className="card coordination-form">
          <div className="section-heading">
            <h2>{replacement ? "为会议提出新时间" : "发起一次相聚"}</h2>
            <Users size={18} />
          </div>
          {replacement && (
            <div className="alert warning">
              关联会议 #{replacement.id}，全员确认前原会议保持有效。
              <button
                aria-label="取消关联"
                onClick={() => setReplacement(null)}
              >
                <X size={14} />
              </button>
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              run(async () =>
                setResult(
                  await api("/coordination/candidates", "POST", {
                    start: iso(f.get("start") as string),
                    end: iso(f.get("end") as string),
                    duration_minutes: Number(f.get("duration")),
                    members: ["A", "B", "C", "D"],
                    preferred: f.get("preferred")
                      ? iso(f.get("preferred") as string)
                      : null,
                  }),
                ),
              );
            }}
          >
            <label>
              会议名称
              <input
                value={replacement?.title || meetingTitle}
                onChange={(e) => setMeetingTitle(e.target.value)}
                required
                maxLength={160}
              />
            </label>
            <label>
              会议日期范围（上海时间）
              <input
                name="start"
                type="datetime-local"
                required
                defaultValue="2026-11-04T13:00"
              />
              <input
                name="end"
                type="datetime-local"
                required
                defaultValue="2026-11-04T20:00"
              />
            </label>
            <div className="form-row">
              <label>
                会议时长
                <select name="duration" defaultValue={60}>
                  {[30, 60, 90, 120].map((n) => (
                    <option key={n} value={n}>
                      {n} 分钟
                    </option>
                  ))}
                </select>
              </label>
              <label>
                偏好时间（可选）
                <input name="preferred" type="datetime-local" />
              </label>
            </div>
            <label>必要成员</label>
            <div className="member-pills">
              {"ABCD".split("").map((m) => (
                <span key={m}>
                  <i className={"avatar " + m}>{m}</i>成员 {m}
                  <Check size={13} />
                </span>
              ))}
            </div>
            <Button disabled={busy} type="submit">
              <WandSparkles size={16} />
              计算共同空档
            </Button>
          </form>
          <div className="privacy-note">
            <ShieldCheck size={17} />
            <p>
              伙伴只能看到忙闲。全员同意后系统会尝试调整冲突的个人任务；无法调整时生成会议备选。
            </p>
          </div>
        </section>
        <section className="card candidate-card">
          <div className="section-heading">
            <div>
              <h2>共同时间</h2>
              <p>
                {result
                  ? `找到 ${result.total} 个候选 · 优先避开不便时段`
                  : "让四份课表找到交集。"}
              </p>
            </div>
            <Badge>区间求交</Badge>
          </div>
          {result ? (
            <>
              <BusyGrid result={result} />
              {result.diagnostics.map((d: string) => (
                <div className="alert warning" key={d}>
                  {d}
                </div>
              ))}
              <div className="candidates">
                {result.candidates.slice(0, 8).map((c: Data, i: number) => (
                  <div key={c.start} className="candidate">
                    <span className="candidate-number">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <b>{range(c.start, c.end)}</b>
                      <small>
                        {c.uncomfortable_members
                          ? `${c.uncomfortable_members} 位成员标记不太方便`
                          : "全员可用 · 无不便偏好冲突"}
                      </small>
                    </div>
                    <Button
                      secondary
                      disabled={busy}
                      onClick={() =>
                        run(async () => {
                          await api("/meetings", "POST", {
                            title: replacement?.title || meetingTitle,
                            start: c.start,
                            end: c.end,
                            members: ["A", "B", "C", "D"],
                            replaces_id:
                              replacement?.status === "confirmed"
                                ? replacement.id
                                : null,
                          });
                          setReplacement(null);
                          await refresh();
                          notify("邀请已创建，请四名成员分别确认。");
                        })
                      }
                    >
                      发起邀请
                      <ArrowUpRight size={13} />
                    </Button>
                  </div>
                ))}
              </div>
              {result.alternatives.length > 0 && (
                <>
                  <h3 className="inset">协商备选 · 不能直接确认</h3>
                  {result.alternatives.map((c: Data) => (
                    <div key={c.start} className="alternative">
                      {range(c.start, c.end)}
                      <small>
                        {c.available_count}/4 人有空 ·{" "}
                        {c.unavailable_members.join("、")} 需协商
                      </small>
                    </div>
                  ))}
                </>
              )}
            </>
          ) : (
            <Empty text="计算后将显示四人忙闲与候选时间。" />
          )}
        </section>
      </div>
      <section className="card">
        <div className="section-heading">
          <div>
            <h2>
              会议与邀请 <span className="count">{meetings.length}</span>
            </h2>
            <p>全员确认后确定会议，改期需要重新邀请。</p>
          </div>
          <div className="demo-switch">
            <span>切换演示身份</span>
            {Object.entries(accounts).map(([m, t]) => (
              <button
                disabled={busy}
                className={me.id === m ? "selected" : ""}
                key={m}
                onClick={() => login(t)}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        {meetings.length ? (
          meetings.map((m) => (
            <div className="meeting" key={m.id}>
              <div className="meeting-top">
                <span className="meeting-icon">
                  <Users size={20} />
                </span>
                <div>
                  <h3>
                    {m.title}
                    <small>
                      #{m.id}
                      {m.replaces_id ? ` · 关联原会议 #${m.replaces_id}` : ""}
                    </small>
                  </h3>
                  <p>
                    {range(m.start, m.end)} · 发起人 {m.organizer_id}
                  </p>
                </div>
                <Badge status={m.status} />
              </div>
              <div className="meeting-bottom">
                <div className="responses">
                  {m.invitations.map((i: Data) => (
                    <span key={i.member_id}>
                      <i className={"avatar " + i.member_id}>{i.member_id}</i>
                      <small className={i.status}>{labels[i.status]}</small>
                    </span>
                  ))}
                </div>
                <div className="meeting-actions">
                  {m.status === "pending" &&
                    m.invitations.find((i: Data) => i.member_id === me.id)
                      ?.status === "pending" && (
                      <>
                        <Button
                          secondary
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await api(`/meetings/${m.id}/respond`, "POST", {
                                response: "declined",
                                revision: m.revision,
                              });
                              await refresh();
                            })
                          }
                        >
                          拒绝
                        </Button>
                        <Button
                          disabled={busy}
                          onClick={() =>
                            run(async () => {
                              await api(`/meetings/${m.id}/respond`, "POST", {
                                response: "accepted",
                                revision: m.revision,
                              });
                              await refresh();
                              notify("答复已保存，全员同意后检查联动。");
                            })
                          }
                        >
                          <Check size={14} />
                          确认参加
                        </Button>
                      </>
                    )}
                  {["confirmed", "needs_reschedule", "declined"].includes(
                    m.status,
                  ) &&
                    m.organizer_id === me.id && (
                      <Button
                        secondary
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            const r = await api(
                              `/meetings/${m.id}/alternatives`,
                            );
                            setReplacement(m);
                            setResult({
                              candidates: r.candidates,
                              total: r.candidates.length,
                              alternatives: [],
                              diagnostics: r.diagnostics,
                              members: {},
                            });
                            window.scrollTo({ top: 0, behavior: "smooth" });
                          })
                        }
                      >
                        生成改期候选
                        <RefreshCw size={13} />
                      </Button>
                    )}
                </div>
              </div>
              {m.linkage.length > 0 && (
                <details
                  className="linkage"
                  open={m.status === "needs_reschedule"}
                >
                  <summary>查看个人计划与会议联动过程</summary>
                  {m.linkage.map((l: Data, i: number) => (
                    <div
                      key={i}
                      className={l.status === "blocked" ? "blocked" : ""}
                    >
                      <span>
                        {l.member_id ? `成员 ${l.member_id}` : "协调服务"}
                      </span>
                      <p>
                        {l.reason}
                        {l.changed_count
                          ? ` 共调整 ${l.changed_count} 项任务。`
                          : ""}
                      </p>
                      {l.candidates && (
                        <small>
                          已生成 {l.candidates.length}{" "}
                          个备选，请发起人选择并重新邀请。
                        </small>
                      )}
                    </div>
                  ))}
                </details>
              )}
            </div>
          ))
        ) : (
          <Empty text="选择一个共同空档，发出第一份邀请。" />
        )}
      </section>
    </>
  );
}
function BusyGrid({ result }: { result: Data }) {
  const entries = Object.entries(result.members) as [string, Data][];
  const all = entries.flatMap(([, v]) => [...v.free, ...v.busy]);
  if (!all.length) return null;
  const start = Math.min(...all.map((s) => +new Date(s.start))),
    end = Math.max(...all.map((s) => +new Date(s.end)));
  return (
    <div className="busy-grid">
      <div className="busy-grid-label">
        <span>成员忙闲概览</span>
        <span>绿色：可用 · 灰色：忙碌</span>
      </div>
      {entries.map(([member, info]) => (
        <div className="busy-row" key={member}>
          <span className={"avatar small-avatar " + member}>{member}</span>
          <div className="busy-track" title="仅共享忙闲，不展示私人日程内容">
            {info.free.map((s: Data) => (
              <span
                key={s.start}
                style={{
                  left: `${((+new Date(s.start) - start) / (end - start)) * 100}%`,
                  width: `${((+new Date(s.end) - +new Date(s.start)) / (end - start)) * 100}%`,
                }}
              />
            ))}
            {info.busy.map((s: Data, i: number) => (
              <i
                key={i}
                style={{
                  left: `${Math.max(0, ((+new Date(s.start) - start) / (end - start)) * 100)}%`,
                  width: `${Math.min(100, ((+new Date(s.end) - +new Date(s.start)) / (end - start)) * 100)}%`,
                }}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="busy-ticks">
        <span>
          {md(new Date(start).toISOString())}{" "}
          {hm(new Date(start).toISOString())}
        </span>
        <span>
          {md(new Date(end).toISOString())} {hm(new Date(end).toISOString())}
        </span>
      </div>
    </div>
  );
}
