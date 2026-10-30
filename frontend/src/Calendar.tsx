import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ShieldCheck } from "lucide-react";
import { Data, md, hm, Legend } from "./ui";
import { addDays, calendarBusy, calendarStart,layoutEvents } from "./calendarData";
export default function Calendar({
  state,
  me,
  meetings,
  compact = false,
}: {
  state: Data;
  me: Data;
  meetings: Data[];
  compact?: boolean;
}) {
  const imports = state.timetable_imports || [];
  const newest = imports.find((r: Data) => r.course_count > 0);
  const [firstDay, setFirstDay] = useState(() =>
    calendarStart(me.window_start, imports),
  );
  useEffect(() => {
    if (newest) setFirstDay(newest.week_start);
  }, [compact, newest?.id]);
  const height = compact ? 30 : 48;
  const days = Array.from({ length: 7 }, (_, i) => addDays(firstDay, i));
  const events = [
    ...calendarBusy(state.busy, firstDay).map((b) => ({
      ...b,
      title: b.title || "固定时段",
      className: b.kind === "disruption" ? "disruption" : "course",
    })),
    ...state.schedule.map((r: Data) => ({ ...r, className: "task" })),
    ...meetings
      .filter((m) => m.status === "confirmed")
      .map((m) => ({ ...m, className: "meeting" })),
  ];
  const visible = events.filter((e) => days.includes(e.start.slice(0, 10)));
  const hour = (v: string) =>
    Number(v.slice(11, 13)) + Number(v.slice(14, 16)) / 60;
  const startHour = Math.min(
    8,
    ...visible.map((e) => Math.floor(hour(e.start))),
  );
  const endHour = Math.max(22, ...visible.map((e) => Math.ceil(hour(e.end))));
  const hours = endHour - startHour;
  const top = (v: string) => (hour(v) - startHour) * height;
  const outside =
    firstDay < me.window_start.slice(0, 10) ||
    addDays(firstDay, 7) > me.window_end.slice(0, 10);
  return (
    <>
      {!compact && (
        <div className="calendar-import-status">
          <span>
            查看日期与排程窗口独立。
            {outside
              ? "当前周在计划窗口之外；要为本周排程，请同时设置排程窗口与可用时段。"
              : ""}
          </span>
          {imports.length > 0 && (
            <label>
              已导入课表
              <select
                aria-label="选择已导入课表周"
                value={String(
                  imports.find(
                    (r: Data) =>
                      r.week_start === firstDay && r.course_count > 0,
                  )?.id || "",
                )}
                onChange={(e) => {
                  const record = imports.find(
                    (r: Data) => String(r.id) === e.target.value,
                  );
                  if (record) setFirstDay(record.week_start);
                }}
              >
                <option value="">选择导入周</option>
                {imports
                  .filter((r: Data) => r.course_count > 0)
                  .map((r: Data) => (
                    <option key={r.id} value={r.id}>
                      {r.week_start} · {r.course_count}条课程
                    </option>
                  ))}
              </select>
            </label>
          )}
        </div>
      )}
      <div className="calendar-toolbar">
        <div>
          <b>
            {days[0].slice(0, 4)} 年 {Number(days[0].slice(5, 7))} 月
          </b>
          <span>
            {md(days[0] + "T00:00:00+08:00")} –{" "}
            {md(days[6] + "T00:00:00+08:00")}
          </span>
        </div>
        <div className="week-controls">
          <button
            className="icon-button"
            aria-label="上一周"
            onClick={() => setFirstDay(addDays(firstDay, -7))}
          >
            <ChevronLeft size={15} />
          </button>
          <button onClick={() => setFirstDay(me.window_start.slice(0, 10))}>
            计划周
          </button>
          {!compact && (
            <input
              type="date"
              aria-label="选择日历查看日期"
              value={firstDay}
              onChange={(e) => {
                if (e.target.value) setFirstDay(e.target.value);
              }}
            />
          )}
          <button
            className="icon-button"
            aria-label="下一周"
            onClick={() => setFirstDay(addDays(firstDay, 7))}
          >
            <ChevronRight size={15} />
          </button>
        </div>
      </div>
      <div className={"calendar-scroll " + (compact ? "compact" : "")}>
        <div className="week-calendar">
          <div className="day-header">
            <div className="utc-label">UTC+8</div>
            {days.map((d, i) => (
              <div className={i === 2 ? "highlight-day" : ""} key={d}>
                <span>
                  周
                  {
                    ["日", "一", "二", "三", "四", "五", "六"][
                      new Date(d + "T12:00:00+08:00").getUTCDay()
                    ]
                  }
                </span>
                <b>{Number(d.slice(8, 10))}</b>
              </div>
            ))}
          </div>
          <div className="calendar-body" style={{ height: hours * height }}>
            <div className="time-axis">
              {Array.from({ length: hours }, (_, i) => (
                <span key={i} style={{ top: i * height }}>
                  {String(i + startHour).padStart(2, "0")}:00
                </span>
              ))}
            </div>
            {days.map((d, di) => (
              <div
                className={"day-column " + (di === 2 ? "highlight-column" : "")}
                key={d}
                style={{ backgroundSize: `100% ${height}px` }}
              >
                {layoutEvents(events.filter((e) => e.start.slice(0, 10) === d))
                  .map(({event:e,index:i,lane,lanes}) => {
                    const y = Math.max(0, top(e.start)),
                      b = Math.min(hours * height, top(e.end));
                    return b > y ? (
                      <div
                        key={e.start + e.title + i}
                        className={
                          "calendar-event " +
                          e.className +
                          (!state.plan_valid && e.className === "task"
                            ? " stale"
                            : "")
                        }
                        style={{ top: y + 2, height: Math.max(b - y - 4, 18),left:`calc(${lane*100/lanes}% + 3px)`,width:`calc(${100/lanes}% - 6px)`,right:'auto' }}
                        title={`${e.title} ${hm(e.start)}–${hm(e.end)}`}
                      >
                        <b>{e.title.split(" · ")[0]}</b>
                        <small>
                          {hm(e.start)}–{hm(e.end)}
                        </small>
                        {!state.plan_valid && e.className === "task" && (
                          <small>待更新</small>
                        )}
                      </div>
                    ) : null;
                  })}
                {state.tasks
                  .filter((t: Data) => t.deadline.slice(0, 10) === d)
                  .map((t: Data) => (
                    <div
                      className="ddl-marker"
                      key={t.id}
                      style={{
                        top: Math.max(
                          0,
                          Math.min(hours * height - 14, top(t.deadline)),
                        ),
                      }}
                      title={t.title + " 截止"}
                    >
                      <i />
                      <span>{hm(t.deadline)} DDL</span>
                    </div>
                  ))}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="calendar-bottom">
        <Legend />
        <span className="privacy">
          <ShieldCheck size={13} />
          私人日程仅自己可见
        </span>
      </div>
    </>
  );
}
