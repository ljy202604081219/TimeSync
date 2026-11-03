import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ShieldCheck } from "lucide-react";
import { Data, md, hm, Legend, Modal, Empty, range } from "./ui";
import { addDays, calendarBusy, calendarStart,layoutEvents,weekStart } from "./calendarData";
export default function Calendar({
  state,
  me,
  meetings,
  compact = false,
  focusDate,
}: {
  state: Data;
  me: Data;
  meetings: Data[];
  compact?: boolean;
  focusDate?: string;
}) {
  const imports = state.timetable_imports || [];
  const today = new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
  const [view,setView] = useState<'day'|'week'>(()=>compact||window.matchMedia('(max-width:760px)').matches?'day':'week');
  const [chosenDay,setChosenDay] = useState('');
  const [detail,setDetail] = useState<Data|null>(null);
  const newest = imports.find((r: Data) => r.course_count > 0);
  const [firstDay, setFirstDay] = useState(() =>
    focusDate?weekStart(focusDate):calendarStart(me.window_start, imports),
  );
  useEffect(() => {
    if (focusDate) {setFirstDay(weekStart(focusDate));setChosenDay(focusDate.slice(0,10));}
    else if (newest) setFirstDay(newest.week_start);
  }, [compact, newest?.id,focusDate]);
  const height = compact ? 44 : 64;
  const days = Array.from({ length: 7 }, (_, i) => addDays(firstDay, i));
  const selectedDay = days.includes(chosenDay)?chosenDay:days.includes(today)?today:firstDay;
  const dayName=(d:string)=>'周'+['日','一','二','三','四','五','六'][new Date(d+'T12:00:00+08:00').getUTCDay()];
  const kindName=(e:Data)=>(({course:'课程',task:'任务',meeting:'会议',disruption:'突发事件',unavailable:'固定日程'} as Record<string,string>)[e.className]||'日程');
  const events = [
    ...calendarBusy(state.busy, firstDay).map((b) => ({
      ...b,
      title: b.title || "固定时段",
      className: b.kind === "disruption" ? "disruption" : b.kind === "unavailable" ? "unavailable" : "course",
    })),
    ...state.schedule.map((r: Data) => ({ ...r, className: "task",source:state.tasks.find((t:Data)=>t.id===r.task_id)?.source })),
    ...meetings
      .filter((m) => m.status === "confirmed")
      .map((m) => ({ ...m, className: "meeting" })),
  ];
  const visible = events.filter((e) => days.includes(e.start.slice(0, 10)));
  const dailyEvents=visible.filter(e=>e.start.slice(0,10)===selectedDay).sort((a,b)=>a.start.localeCompare(b.start));
  const dailyDeadlines=state.tasks.filter((t:Data)=>t.deadline.slice(0,10)===selectedDay);
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
        <div className="calendar-controls">
        <div className="calendar-view-switch" role="group" aria-label="日历视图">
          <button aria-pressed={view==='day'} onClick={()=>setView('day')}>按日</button>
          <button aria-pressed={view==='week'} onClick={()=>setView('week')}>按周</button>
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
      </div>
      {view==='day'?<div className="day-agenda">
        <div className="agenda-days" role="group" aria-label="选择查看日期">{days.map(d=><button key={d} aria-pressed={d===selectedDay} onClick={()=>setChosenDay(d)}><span>{d===today?'今天':dayName(d)}</span><b>{Number(d.slice(8,10))}</b></button>)}</div>
        <div className="agenda-summary"><strong>{md(selectedDay+'T00:00:00+08:00')} · {dayName(selectedDay)}</strong><span>{dailyEvents.length}项日程{dailyDeadlines.length?` · ${dailyDeadlines.length}项截止`:''}</span></div>
        <div className="agenda-list">{dailyEvents.map((e,i)=><button className={'agenda-event '+e.className} key={e.start+e.title+i} onClick={()=>setDetail(e)}><time><b>{hm(e.start)}</b><span>{hm(e.end)}</span></time><div><span className="agenda-kind">{kindName(e)}{e.source==='qq'?' · QQ通知':''}</span><strong>{e.title}</strong>{!state.plan_valid&&e.className==='task'&&<small>计划待更新</small>}</div><ChevronRight size={18}/></button>)}
        {dailyDeadlines.map((t:Data)=><button className="agenda-event deadline" key={'ddl'+t.id} onClick={()=>setDetail({...t,start:t.deadline,end:t.deadline,className:'deadline'})}><time><b>{hm(t.deadline)}</b><span>截止</span></time><div><span className="agenda-kind">DDL{t.source==='qq'?' · QQ通知':''}</span><strong>{t.title}</strong></div><ChevronRight size={18}/></button>)}
        {!dailyEvents.length&&!dailyDeadlines.length&&<Empty text="这一天还没有记录日程，可以留给新的安排。"/>}</div>
      </div>:<>
      <p className="calendar-scroll-hint">左右滑动查看整周，点击日程查看完整内容。</p>
      <div className={"calendar-scroll " + (compact ? "compact" : "")}>
        <div className="week-calendar">
          <div className="day-header">
            <div className="utc-label">UTC+8</div>
            {days.map(d => (
              <div className={d === today ? "highlight-day" : ""} key={d}>
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
            {days.map(d => (
              <div
                className={"day-column " + (d === today ? "highlight-column" : "")}
                key={d}
                style={{ backgroundSize: `100% ${height}px` }}
              >
                {layoutEvents(events.filter((e) => e.start.slice(0, 10) === d))
                  .map(({event:e,index:i,lane,lanes}) => {
                    const y = Math.max(0, top(e.start)),
                      b = Math.min(hours * height, top(e.end));
                    return b > y ? (
                      <button
                        type="button"
                        onClick={()=>setDetail(e)}
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
                        {e.source==='qq'&&<small>QQ通知</small>}
                        <small>
                          {hm(e.start)}–{hm(e.end)}
                        </small>
                        {!state.plan_valid && e.className === "task" && (
                          <small>待更新</small>
                        )}
                      </button>
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
                      <span>{hm(t.deadline)} DDL{t.source==='qq'?' · QQ':''}</span>
                    </div>
                  ))}
              </div>
            ))}
          </div>
        </div>
      </div>
      </>}
      <div className="calendar-bottom">
        <Legend />
        <span className="privacy">
          <ShieldCheck size={13} />
          私人日程仅自己可见
        </span>
      </div>
      {detail&&<Modal title={detail.className==='deadline'?'任务截止':'日程详情'} close={()=>setDetail(null)}><div className="calendar-detail"><span className={'badge '+detail.className}>{detail.className==='deadline'?'DDL':kindName(detail)}</span><h3>{detail.title}</h3><p>{detail.className==='deadline'?range(detail.start,detail.start).split(' — ')[0]+' 截止':range(detail.start,detail.end)}</p>{detail.source==='qq'&&<p>来源：QQ通知</p>}{!state.plan_valid&&detail.className==='task'&&<p>此任务的计划待更新，请到计划工作台重新校验。</p>}</div></Modal>}
    </>
  );
}
