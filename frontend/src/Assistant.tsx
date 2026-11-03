import { useEffect, useRef, useState, Fragment } from 'react';
import { Send, Sparkles, Trash2, X, CalendarDays } from 'lucide-react';
import { Changes, SolveResult, type Data } from './ui';
import { requestId } from './requestId';

type AssistantRequest={message:string;conversation_id:string|null;request_id:string};

const starters=['帮我添加一个日程','今天有什么安排？','明天什么时候有空？','本周有哪些即将到期的任务？','我的任务是否存在冲突？','为什么系统把这个任务安排在这个时间？','今天的时间安排是否合理？'];
const actions:Record<string,string>={create_task:'新增任务',create_event:'添加个人日程',update_task:'修改任务并重新排程',repair:'加入事件并修复计划',generate_plan:'重新生成计划',move_task:'移动任务到指定时段'};
const time=(s:string)=>new Date(s).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
function inline(value:string){return value.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((s,j)=>s.startsWith('**')?<strong key={j}>{s.slice(2,-2)}</strong>:s.startsWith('`')?<code key={j}>{s.slice(1,-1)}</code>:<Fragment key={j}>{s}</Fragment>);}
function Markdown({text}:{text:string}){
  const lines=text.split('\n'),blocks=[];
  for(let i=0;i<lines.length;i++){
    if(!lines[i].trim())continue;
    if(lines[i].startsWith('- ')){const items=[];while(i<lines.length&&lines[i].startsWith('- ')){items.push(<li key={i}>{inline(lines[i].slice(2))}</li>);i++;}i--;blocks.push(<ul key={'list'+i}>{items}</ul>);}
    else blocks.push(lines[i].startsWith('### ')?<h3 key={i}>{inline(lines[i].slice(4))}</h3>:<p key={i}>{inline(lines[i])}</p>);
  }
  return <>{blocks}</>;
}
function ProposalDetails({proposal}:{proposal:Data}){
  const d=proposal.payload.data||proposal.payload;
  return <dl className="proposal-fields">{d.title&&<><dt>名称</dt><dd>{d.title}</dd></>}{d.deadline&&<><dt>截止时间</dt><dd>{time(d.deadline)}</dd></>}{d.duration_minutes&&<><dt>预计耗时</dt><dd>{d.duration_minutes}分钟</dd></>}{d.priority&&<><dt>优先级</dt><dd>{({1:'低',2:'中',3:'高'} as Record<number,string>)[d.priority]}</dd></>}{d.start&&<><dt>目标时段</dt><dd>{time(d.start)} 至 {time(d.end)}</dd></>}</dl>;
}
export default function Assistant({api,onApplied,onClose,onNavigate,open}:{api:(path:string,method?:string,body?:unknown)=>Promise<any>;onApplied:()=>Promise<void>;onClose:()=>void;onNavigate:(page:string,date?:string)=>void;open:boolean}){
  const [messages,setMessages]=useState<Data[]>([]),[conversation,setConversation]=useState<string|null>(null),[input,setInput]=useState(''),[pending,setPending]=useState(false),[ready,setReady]=useState(false),[error,setError]=useState(''),[retry,setRetry]=useState<AssistantRequest|null>(null),[service,setService]=useState<Data|null>(null);
  const alive=useRef(true),end=useRef<HTMLDivElement>(null);
  useEffect(()=>{alive.current=true;Promise.all([api('/v1/assistant/conversations/latest'),api('/v1/assistant/status')]).then(([r,s])=>{if(alive.current){setService(s);setConversation(r.conversation_id);setMessages(r.messages);setReady(true);}}).catch(e=>{if(alive.current){setError(e.message);setReady(true);}});return()=>{alive.current=false;};},[]);
  useEffect(()=>{if(open)end.current?.scrollIntoView({block:'nearest'});},[messages,pending,open]);
  async function refreshService(){try{const s=await api('/v1/assistant/status');if(alive.current)setService(s);}catch{}}
  useEffect(()=>{if(open)void refreshService();},[open]);
  async function send(message=input,again?:AssistantRequest){
    if(!message.trim()||pending||!ready)return;
    if(!navigator.onLine){setError('当前离线，问题没有发送。');return;}
    const payload=again||{message,conversation_id:conversation,request_id:requestId()};
    setPending(true);setError('');setRetry(null);setInput('');setMessages(v=>[...v,{role:'user',content:message}]);
    try{const r=await api('/v1/assistant/chat','POST',payload);if(!alive.current)return;setConversation(r.conversation_id);setMessages(v=>[...v,{role:'assistant',content:r.answer,...r}]);if(r.applied){try{await onApplied();}catch{if(alive.current)setError('日程已保存，页面刷新失败，请刷新后查看。');}}}
    catch(e){if(alive.current){setError(e instanceof Error?e.message:'问答失败');setRetry(payload);setMessages(v=>v.slice(0,-1));}}
    finally{if(alive.current)setPending(false);}
  }
  async function clear(){if(pending||!window.confirm('清空当前对话及其待确认建议？'))return;try{if(conversation)await api('/v1/assistant/conversations/'+conversation,'DELETE');setMessages([]);setConversation(null);setError('');setRetry(null);}catch(e){setError((e as Error).message);}}
  async function confirm(index:number,p:Data){
    setPending(true);setError('');
    try{const result=await api('/v1/assistant/proposals/'+p.id+'/confirm','POST',{confirmed:true});if(!alive.current)return;setMessages(v=>v.map((m,i)=>i===index?{...m,applied:true,planId:result.plan?.id}:m));await onApplied();}
    catch(e){if(alive.current)setError((e as Error).message);}
    finally{if(alive.current)setPending(false);}
  }
  return <section className="assistant-card">
    <header><div><Sparkles size={22}/><div><h2>TimeSync AI Assistant</h2><p>边看日程，边问边调整</p></div></div><div className="assistant-tools"><button onClick={clear} disabled={pending} aria-label="清空对话"><Trash2 size={18}/></button><button onClick={onClose} aria-label="关闭AI助手"><X size={20}/></button></div></header>
    <div className="assistant-service" role="status">{service?.mode==='live'?(service?.auto_create?'新增日程直接保存 · 缺少关键信息时再补充':'项目AI已启用 · 修改须先预览、再确认'):service?.notice||'正在连接项目AI…'}</div>
    <div className="assistant-messages" aria-live="polite">
      {!messages.length&&<div className="assistant-welcome"><Sparkles size={30}/><h3>想知道什么安排？</h3><p>可以直接说：添加明天上午9点到10点的“自习”。</p><div className="assistant-starters">{starters.map(s=><button key={s} onClick={()=>send(s)} disabled={pending||!ready}>{s}</button>)}</div></div>}
      {messages.map((m,i)=><article key={i} className={'chat-message '+m.role}>
        <small>{m.role==='user'?'你':m.mode==='direct'?'时聚 · 直接录入':m.mode==='live'?'时聚AI':m.mode==='mock'?'时聚助手 · 规则演示':'时聚助手 · 历史回答'}</small>
        {m.response_notice&&<p role="status">{m.response_notice}</p>}
        <Markdown text={m.content}/>
        {m.applied_result&&<button className="btn secondary" onClick={()=>onNavigate(m.applied_result.action==='create_task'&&m.applied_result.requires_scheduling?'tasks':'calendar',m.applied_result.start||m.applied_result.deadline)}><CalendarDays size={16}/>查看{m.applied_result.action==='create_task'&&m.applied_result.requires_scheduling?'任务':'日历'}</button>}
        {m.proposal&&<div className={'assistant-proposal '+(m.applied?'applied':'')}>
          <div className="proposal-heading"><b>{actions[m.proposal.action]}</b><span>{m.applied?(m.planId?`已保存 #${m.planId}`:'已保存'):m.proposal.can_confirm?'待你确认':'无法执行'}</span></div>
          <ProposalDetails proposal={m.proposal}/>{m.proposal.preview.save_only?<div className={"event-save-summary "+(m.proposal.can_confirm?"":"failure")}><b>{m.proposal.can_confirm?(m.proposal.action==='create_event'?'日程可保存':'任务可保存，尚未排程'):'请先解决时间冲突'}</b>{m.proposal.preview.diagnostics.map((s:string)=><p key={s}>{s}</p>)}</div>:<><SolveResult result={m.proposal.preview}/><Changes changes={m.proposal.preview.changes}/></>}
          {m.proposal.preview.meeting_conflicts?.map((c:Data)=><p className="assistant-error" key={c.id}>{c.title}：{c.reason}</p>)}
          <div className="proposal-actions">{m.applied?<button className="btn" onClick={()=>onNavigate(m.proposal.action==='create_task'&&m.proposal.preview.save_only?'tasks':'calendar',m.proposal.payload.start||m.proposal.preview.changes[0]?.after?.start||m.proposal.payload.data?.deadline)}><CalendarDays size={16}/>{m.proposal.action==='create_task'&&m.proposal.preview.save_only?'查看任务':'查看日历'}</button>:<button className="btn" disabled={pending||!m.proposal.can_confirm} onClick={()=>confirm(i,m.proposal)}>{m.proposal.preview.save_only?(m.proposal.action==='create_event'?'确认添加到日历':'确认保存任务'):'确认执行并保存计划'}</button>}</div>
          <p className="proposal-hint">{m.applied?(m.planId?'日程与计划已同步更新。':'已保存，可在日历或任务列表查看。'):'10分钟内有效；数据变化后须重新预览。已确认会议仍需成员协商。'}</p>
        </div>}
        {m.facts&&<details className="answer-sources"><summary>查询依据</summary><p>{time(m.facts.start)} 至 {time(m.facts.end)} · 上海时间</p><p>{m.facts.events.length}个事件、{m.facts.tasks.length}项任务；计划{m.facts.plan.valid?'有效':'未生成或待更新'}。</p></details>}
      </article>)}
      {pending&&<p className="assistant-thinking" role="status">正在理解问题、核对日程并整理建议…</p>}<div ref={end}/>
    </div>
    {error&&<div className="assistant-error" role="alert">{error}{retry&&<button disabled={pending} onClick={()=>send(retry.message,retry)}>重试</button>}</div>}
    <form onSubmit={e=>{e.preventDefault();send();}}><label htmlFor="assistant-input" className="sr-only">向时聚提问</label><textarea id="assistant-input" value={input} maxLength={1200} rows={2} onChange={e=>setInput(e.target.value)} placeholder="问问日程，或描述想调整的安排…" disabled={pending||!ready}/><button className="btn" disabled={pending||!ready||!input.trim()} aria-label="发送问题"><Send size={18}/></button></form>
    <footer>聊天按登录身份保存；共享演示身份的访客共用同一份数据。</footer>
  </section>;
}
