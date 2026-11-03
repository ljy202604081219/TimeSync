"""Optional read-only NapCat history recovery. No login or send actions."""
import os
from datetime import datetime,timedelta,timezone
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from ...models import QQGroup
from ...timeutil import dt,now
from ...db import write_transaction
from .schemas import Event
from . import service

async def catchup(db,ident):
    if not service.live_allowed():raise HTTPException(503,'真实接入关闭')
    group=db.get(QQGroup,ident)
    if not group or group.synthetic or not group.enabled or not group.consent:raise HTTPException(403,'该群未授权历史补采')
    base=os.getenv('QQ_ONEBOT_API_URL','').rstrip('/')
    parsed=urlsplit(base)
    if not parsed.hostname or parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1')):
        raise HTTPException(503,'请配置HTTPS或本机OneBot只读API地址')
    token=os.getenv('QQ_ONEBOT_API_TOKEN','');headers={'Authorization':'Bearer '+token} if token else {}
    gid,bot,cursor=group.group_id,group.bot_id,group.history_cursor
    private=gid.startswith('private:');peer=gid[8:] if private else gid
    action='get_friend_msg_history' if private else 'get_group_msg_history'
    events=[];seen=set();complete=False
    cutoff=dt(now())-timedelta(hours=24)
    try:
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            for _ in range(3):
                payload={'user_id' if private else 'group_id':peer,'count':100,'reverse_order':False}
                if cursor:payload['message_seq']=cursor
                response=await client.post(base+'/'+action,json=payload,headers=headers);response.raise_for_status()
                envelope=response.json()
                if envelope.get('status')!='ok' or envelope.get('retcode',0)!=0:
                    message=str(envelope.get('message') or envelope.get('msg') or '')
                    if not cursor and '消息' in message and '不存在' in message and '权限' not in message:complete=True;break
                    raise ValueError('history_api_error')
                records=envelope.get('data',{}).get('messages',[])
                if not isinstance(records,list):raise ValueError('invalid_history')
                if not records:complete=True;break
                batch=[]
                for record in records:
                    if str(record.get('self_id',bot))!=bot:raise ValueError('history_source_mismatch')
                    if private:
                        if str(record.get('user_id','')) not in (peer,bot) or record.get('message_type')=='group':raise ValueError('history_source_mismatch')
                        value=Event.model_validate({**record,'post_type':'message','message_type':'private','group_id':'','self_id':bot,'target_id':peer})
                    else:
                        if str(record.get('group_id',gid))!=gid:raise ValueError('history_source_mismatch')
                        value=Event.model_validate({**record,'post_type':'message','message_type':'group','group_id':gid,'self_id':bot})
                    stamp=dt(datetime.fromtimestamp(value.time,timezone.utc))
                    if stamp>=cutoff:batch.append(value)
                    else:complete=True
                events.extend(batch)
                oldest=min(records,key=lambda m:int(m.get('time',0)))
                next_cursor=str(oldest.get('message_id',''))
                if len(records)<100 or not next_cursor:complete=True
                elif next_cursor in seen:break  # stalled pagination stays partial
                cursor=next_cursor;seen.add(cursor)
                if complete:break
    except Exception:
        with write_transaction(db,'qq:offline'):
            group=db.get(QQGroup,ident,populate_existing=True)
            if group:group.connection='offline';db.commit()
        raise HTTPException(503,'OneBot历史服务暂不可用；游标与已有消息保留，可稍后重试')
    with write_transaction(db,'qq:catchup'):
        group=db.get(QQGroup,ident,populate_existing=True)
        if not group or not group.enabled or not group.consent:raise HTTPException(403,'补采期间授权已撤销')
        results=[service.accept(db,group,e) for e in sorted(events,key=lambda e:e.time)]
        group.history_cursor=None if complete else cursor
        group.connection='receiving' if complete else 'partial'
        db.commit()
        return {'received':len(results),'duplicates':sum(bool(r.get('duplicate')) for r in results),'has_more':not complete,
                'window_hours':24,'cursor':group.history_cursor,'notice':'仅代表只读API补采响应，不证明真实QQ账号已连通。'}
