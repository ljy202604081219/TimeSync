import { useEffect, useRef } from "react";
import {
  Layers3,
  X,
  MoveRight,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
export type Data = Record<string, any>;
export const labels: Record<string, string> = {
  optimal: "最优解",
  feasible: "可行解",
  infeasible: "不可行",
  invalid: "输入无效",
  unknown: "求解超时",
  pending: "待确认",
  accepted: "已同意",
  declined: "已拒绝",
  confirmed: "已确认",
  needs_reschedule: "需要重新协调",
  superseded: "已完成改期",
};
export function md(v: string) {
  return new Date(v).toLocaleDateString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
  });
}
export function hm(v: string) {
  return new Date(v).toLocaleTimeString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
export function iso(v: string) {
  return v.length === 16 ? v + ":00+08:00" : v;
}
export function range(a: string, b: string) {
  return `${md(a)} ${hm(a)} — ${hm(b)}`;
}
export function Badge({
  status = "",
  children,
}: {
  status?: string;
  children?: React.ReactNode;
}) {
  return (
    <span className={"badge " + status}>
      {children || labels[status] || status}
    </span>
  );
}
export function Button({
  children,
  onClick,
  secondary = false,
  disabled = false,
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  secondary?: boolean;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={"btn " + (secondary ? "secondary" : "")}
    >
      {children}
    </button>
  );
}
export function Empty({
  text = "还没有内容，开始创建第一项吧。",
}: {
  text?: string;
}) {
  return (
    <div className="empty">
      <Layers3 size={28} />
      <p>{text}</p>
    </div>
  );
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: React.ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLElement>(null),
    closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const f = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
      if (e.key === "Tab") {
        const nodes = Array.from(
          ref.current?.querySelectorAll<HTMLElement>(
            "button:not(:disabled),input:not(:disabled),select,textarea,a[href],summary",
          ) || [],
        ).filter((n) => n.getClientRects().length);
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", f);
    return () => {
      document.body.style.overflow = bodyOverflow;
      window.removeEventListener("keydown", f);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <section
        ref={ref}
        tabIndex={-1}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="关闭" onClick={close}>
            <X />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
export function Legend() {
  return (
    <div className="legend">
      {[
        ["course", "固定课程"],
        ["task", "个人任务"],
        ["ddl", "截止时间"],
        ["meeting", "会议"],
      ].map(([c, t]) => (
        <span key={c}>
          <i className={c} />
          {t}
        </span>
      ))}
    </div>
  );
}
export function ScheduleList({ items }: { items: Data[] }) {
  return items.length ? (
    <div className="schedule-list">
      {[...items]
        .sort((a, b) => a.start.localeCompare(b.start))
        .map((r) => (
          <div key={r.task_id}>
            <div className="schedule-date">
              <b>{md(r.start)}</b>
              <small>{hm(r.start)}</small>
            </div>
            <span className="schedule-line" />
            <div>
              <b>{r.title}</b>
              <p>
                {hm(r.start)}–{hm(r.end)}{" "}
                <span>
                  · {(+new Date(r.end) - +new Date(r.start)) / 60000} 分钟
                </span>
              </p>
            </div>
            <Badge>#{r.task_id}</Badge>
          </div>
        ))}
    </div>
  ) : (
    <Empty text="暂无安排，请生成计划。" />
  );
}
export function SolveResult({ result }: { result: Data }) {
  const good = ["optimal", "feasible"].includes(result.status);
  return (
    <div className={"solve-result " + (good ? "success" : "failure")}>
      <div>
        {good ? <CheckCircle2 size={24} /> : <AlertTriangle size={24} />}
        <div>
          <h3>
            {good ? "找到满足全部硬约束的计划" : "未生成新的有效计划"}{" "}
            <Badge status={result.status} />
          </h3>
          <p>
            {good
              ? `${result.schedule.length} 项任务，${result.changes.length} 项发生变化。${result.status === "feasible" ? "部分目标尚未证明最优。" : ""}`
              : result.diagnostics.join("；")}
          </p>
        </div>
      </div>
      {result.objectives && (
        <div className="objectives">
          {result.objectives.map((o: Data, i: number) => (
            <span key={o.goal}>
              {["改动任务", "移动格数", "零碎空档", "优先级目标"][i]}{" "}
              <b>{o.value}</b>
              {!o.optimal && "（未证最优）"}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
export function Changes({ changes }: { changes: Data[] }) {
  return changes.length ? (
    <div className="table-scroll">
      <table className="change-table">
        <thead>
          <tr>
            <th>变化任务</th>
            <th>原计划</th>
            <th />
            <th>新计划</th>
            <th>原因</th>
          </tr>
        </thead>
        <tbody>
          {changes.map((c) => (
            <tr key={c.task_id}>
              <td>
                <b>{c.title}</b>
              </td>
              <td className="old-time">
                {c.before ? range(c.before.start, c.before.end) : "尚未安排"}
              </td>
              <td>
                <MoveRight size={16} />
              </td>
              <td className="new-time">{range(c.after.start, c.after.end)}</td>
              <td>
                <small>{c.reason}</small>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty text="原计划已符合新增约束，无需移动。" />
  );
}
