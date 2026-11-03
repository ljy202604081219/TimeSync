import {useEffect,useState} from 'react';
import {Button,range,SolveResult,type Data} from './ui';

type Props={api:(path:string,method?:string,body?:unknown)=>Promise<any>;onApplied:()=>Promise<void>;onResult?:(result:Data)=>void};

export default function FreeTimePanel({api,onApplied,onResult}:Props){
  const [data,setData]=useState<Data|null>(null),[selected,setSelected]=useState<number[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<Data|null>(null);
  async function load(){setData(await api('/availability/suggestions'));setSelected([]);}
  useEffect(()=>{let active=true;api('/availability/suggestions').then(d=>{if(active)setData(d);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
  async function apply(){if(busy||!data)return;setBusy(true);setError('');try{const r=await api('/availability/apply-suggestions','POST',{slots:selected.map(i=>({start:data.eligible_slots[i].start,end:data.eligible_slots[i].end}))});setResult(r);onResult?.(r);await onApplied();await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <section className="card free-time-panel" aria-label="今天的参考空档">
    <h2>今天的参考空档</h2>
    {error&&<p role="alert">{error}</p>}
    {!data?<p role="status">正在核对今天的日历…</p>:<>
      <p>{data.configuration_status==='missing'?'尚未设置可排程时段，不代表没有空闲。':'以下空档按已记录的课程、任务和会议计算。'} 参考范围为08:00—22:00，仅显示尚未过去的时间。</p>
      {data.eligible_slots.map((slot:Data,i:number)=><label className="free-time-choice" key={slot.start}><input type="checkbox" checked={selected.includes(i)} disabled={busy} onChange={e=>setSelected(s=>e.target.checked?[...s,i]:s.filter(n=>n!==i))}/><span>{range(slot.start,slot.end)} · {slot.minutes}分钟</span></label>)}
      {!data.eligible_slots.length&&<p>{data.calendar_gaps.length?'今天有参考空档，但不在当前规划窗口内，请在“时间设置”调整规划日期。':'今天剩余时间内没有已记录的连续参考空档，可在“时间设置”选择其他日期。'}</p>}
      {data.eligible_slots.length>0&&<><p>勾选表示你允许在该时段安排任务。重新排程会使用现有任务，遵守DDL、课程和依赖约束。</p><Button disabled={busy||!selected.length} onClick={apply}>{busy?'正在排程…':'允许所选时段并重新排程'}</Button></>}
    </>}
    {result&&<><p role="status">{result.notice}</p><SolveResult result={result.scheduling}/></>}
  </section>;
}
