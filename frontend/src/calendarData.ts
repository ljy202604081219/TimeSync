// View dates are independent of the solver's planning window. Shanghai is UTC+8.
type Busy = {
  id?: number;
  title?: string;
  start: string;
  end: string;
  weekday: number | null;
  kind: string;
};
export function addDays(day: string, count: number): string {
  const value = new Date(day + "T12:00:00Z");
  value.setUTCDate(value.getUTCDate() + count);
  return value.toISOString().slice(0, 10);
}
export function calendarStart(
  windowStart: string,
  imports: { week_start: string; course_count: number }[],
): string {
  return (
    imports.find((r) => r.course_count > 0)?.week_start ||
    windowStart.slice(0, 10)
  );
}
export function calendarBusy(rows: Busy[], firstDay: string): Busy[] {
  const limit = addDays(firstDay, 7);
  const out: Busy[] = [];
  for (const row of rows) {
    if (row.weekday === null) {
      if (row.start.slice(0, 10) < limit && row.end.slice(0, 10) >= firstDay)
        out.push(row);
    } else {
      for (let i = 0; i < 7; i++) {
        const day = addDays(firstDay, i);
        const weekday = (new Date(day + "T12:00:00Z").getUTCDay() + 6) % 7;
        if (weekday === row.weekday)
          out.push({
            ...row,
            start: day + row.start.slice(10),
            end: day + row.end.slice(10),
          });
      }
    }
  }
  return out;
}

export function layoutEvents<T extends {start:string;end:string}>(events:T[]) {
  const result:{event:T;lane:number;lanes:number;index:number}[]=[];
  let group:typeof result=[],laneEnds:number[]=[],groupEnd=-Infinity;
  function flush(){for(const row of group)result.push({...row,lanes:laneEnds.length});group=[];laneEnds=[];groupEnd=-Infinity}
  const sorted=events.map((event,index)=>({event,index})).sort((a,b)=>Date.parse(a.event.start)-Date.parse(b.event.start)||Date.parse(a.event.end)-Date.parse(b.event.end));
  for(const row of sorted){
    const start=Date.parse(row.event.start),end=Date.parse(row.event.end);
    if(start>=groupEnd)flush();
    let lane=laneEnds.findIndex(value=>value<=start);
    if(lane<0)lane=laneEnds.length;
    laneEnds[lane]=end;groupEnd=Math.max(groupEnd,end);
    group.push({...row,lane,lanes:1});
  }
  flush();return result;
}
