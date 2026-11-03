import hashlib
import hmac
import json
import os
from datetime import timedelta
from fastapi import APIRouter,Depends,Header,HTTPException,Request,Response,Query
from sqlalchemy import select,delete,func
from ...auth import current_user
from ...db import session,write_transaction
from ...models import QQGroup,QQMessage,QQNotice
from ...plans import serialize
from ...timeutil import dt,now
from .schemas import GroupInput,GroupPatch,Event,Confirmation
from . import service
from . import account
from .adapter import conversation_key

router=APIRouter(prefix='/api/v1/qq',tags=['QQ notifications'])


def mutate(db,user,key,tag,payload,fn):
    from ...main import mutation
    return mutation(db,user,key,'qq:'+tag,payload,fn)

@router.get('/groups')
def groups(response:Response,user=Depends(current_user),db=Depends(session)):
    response.headers['Cache-Control']='no-store'
    return [serialize(g) for g in db.scalars(select(QQGroup).where(QQGroup.owner_id==user.id).order_by(QQGroup.id))]

@router.post('/groups')
def create_group(data:GroupInput,user=Depends(current_user),db=Depends(session),key:str=Header(default='',alias='Idempotency-Key')):
    if not data.synthetic and (not service.live_allowed() or data.bot_id=='synthetic'):raise HTTPException(403,'真实QQ接入默认关闭；需维护者配置并提供bot_id')
    managed=account.policy()
    if not data.synthetic and managed and (user.id!=managed['owner_id'] or data.bot_id!=managed['bot_id']):raise HTTPException(403,'真实收录只绑定已指定的小号和本人身份')
    def action():
        existing=db.scalar(select(QQGroup).where(QQGroup.owner_id==user.id,QQGroup.group_id==data.group_id,QQGroup.bot_id==data.bot_id))
        if existing:raise HTTPException(409,'该群已配置')
        row=QQGroup(owner_id=user.id,created_at=now(),**data.model_dump());db.add(row);db.flush();return serialize(row)
    return mutate(db,user,key,'group:create',data.model_dump(),action)

@router.patch('/groups/{ident}')
def patch_group(ident:int,data:GroupPatch,user=Depends(current_user),db=Depends(session),key:str=Header(default='',alias='Idempotency-Key')):
    def action():
        row=service.own(db,QQGroup,ident,user)
        for k,v in data.model_dump(exclude_none=True).items():setattr(row,k,v)
        if not row.consent:row.enabled=False
        if row.retention_days:
            for m in db.scalars(select(QQMessage).where(QQMessage.group_config_id==row.id)):
                m.expires_at=min(m.expires_at,(dt(m.received_at)+timedelta(days=row.retention_days)).isoformat())
        return serialize(row)
    return mutate(db,user,key,'group:patch:'+str(ident),data.model_dump(),action)

def remove_message(db,row):
    notice_id=row.notice_id;db.delete(row);db.flush()
    if notice_id and not db.scalar(select(func.count()).select_from(QQMessage).where(QQMessage.notice_id==notice_id)):
        notice=db.get(QQNotice,notice_id)
        if notice:db.delete(notice);db.flush()

@router.delete('/groups/{ident}')
def delete_group(ident:int,user=Depends(current_user),db=Depends(session),key:str=Header(default='',alias='Idempotency-Key')):
    def action():
        row=service.own(db,QQGroup,ident,user)
        for m in list(db.scalars(select(QQMessage).where(QQMessage.group_config_id==row.id))):remove_message(db,m)
        db.delete(row);return {'deleted':True,'notice':'已撤销授权并删除收录记录；个人任务未删除。'}
    return mutate(db,user,key,'group:delete:'+str(ident),{},action)

@router.post('/groups/{ident}/simulate')
def simulate(ident:int,data:Event,user=Depends(current_user),db=Depends(session),key:str=Header(default='',alias='Idempotency-Key')):
    def action():
        group=service.own(db,QQGroup,ident,user)
        if not group.synthetic:raise HTTPException(403,'模拟入口仅接受合成群')
        return service.accept(db,group,data)
    return mutate(db,user,key,'simulate:'+str(ident),data.model_dump(),action)

@router.post('/events')
async def events(request:Request,db=Depends(session)):
    if not service.live_allowed():raise HTTPException(503,'真实QQ收录未启用；公开演示仅接受登录后的合成事件')
    secret=os.getenv('QQ_EVENT_SECRET','')
    if len(secret)<24:raise HTTPException(503,'未配置独立事件认证密钥')
    raw=await request.body()
    supplied=request.headers.get('Authorization','')
    signature=request.headers.get('X-Signature','')
    bearer=hmac.compare_digest(supplied.encode(),('Bearer '+secret).encode())
    signed=hmac.compare_digest(signature,'sha1='+hmac.new(secret.encode(),raw,hashlib.sha1).hexdigest())
    if not (bearer or signed):raise HTTPException(401,'QQ事件认证失败')
    try:data=Event.model_validate_json(raw)
    except ValueError:raise HTTPException(422,'OneBot事件格式无效')
    managed=account.policy()
    if managed and str(data.self_id)!=managed['bot_id']:raise HTTPException(403,'事件账号不是指定的小号')
    with write_transaction(db,'qq:event'):
        query=select(QQGroup).where(QQGroup.synthetic==False,QQGroup.enabled==True,QQGroup.consent==True,QQGroup.bot_id==str(data.self_id))
        if managed:query=query.where(QQGroup.owner_id==managed['owner_id'])
        if data.post_type!='meta_event':query=query.where(QQGroup.group_id==conversation_key(data))
        groups=list(db.scalars(query))
        if not groups and managed and data.post_type!='meta_event':
            conversation=account.ensure_conversation(db,data)
            if conversation:groups=[conversation]
        if not groups and managed and data.post_type=='meta_event':return {'accepted':True,'heartbeat':True}
        if not groups:raise HTTPException(403,'事件不在授权群/机器人白名单内')
        results=[service.accept(db,g,data) for g in groups];db.commit()
        return {'accepted':True,'results':results}

@router.post('/groups/{ident}/catchup')
async def catchup(ident:int,user=Depends(current_user),db=Depends(session)):
    service.own(db,QQGroup,ident,user)
    from .bridge import catchup as recover
    return await recover(db,ident)

@router.get('/messages')
def messages(response:Response,group_id:int | None=None,status:str | None=None,limit:int=Query(default=100,ge=1,le=200),offset:int=Query(default=0,ge=0),user=Depends(current_user),db=Depends(session)):
    response.headers['Cache-Control']='no-store'
    q=select(QQMessage).where(QQMessage.owner_id==user.id)
    if group_id is not None:q=q.where(QQMessage.group_config_id==group_id)
    if status:q=q.where(QQMessage.status==status)
    return [service.public_message(m) for m in db.scalars(q.order_by(QQMessage.id.desc()).offset(offset).limit(limit))]

@router.get('/messages/{ident}')
def original(ident:int,response:Response,user=Depends(current_user),db=Depends(session)):
    response.headers['Cache-Control']='no-store'
    row=service.own(db,QQMessage,ident,user);available=row.expires_at>=now()
    return {**service.public_message(row),'text':row.raw_text if available else '', 'image_count':len(row.images) if available else 0,'expired':not available}

@router.delete('/messages/{ident}')
def delete_message(ident:int,user=Depends(current_user),db=Depends(session),key:str=Header(default='',alias='Idempotency-Key')):
    def action():remove_message(db,service.own(db,QQMessage,ident,user));return {'deleted':True}
    return mutate(db,user,key,'message:delete:'+str(ident),{},action)

@router.post('/messages/{ident}/process')
async def process(ident:int,user=Depends(current_user),db=Depends(session)):
    return await service.process_message(db,ident,user.id)

@router.get('/pending')
def pending(response:Response,status:str='pending_confirmation',group_id:int | None=None,importance:str | None=None,user=Depends(current_user),db=Depends(session)):
    response.headers['Cache-Control']='no-store'
    q=select(QQNotice).where(QQNotice.owner_id==user.id)
    if status!='all':q=q.where(QQNotice.status==status)
    if importance:q=q.where(QQNotice.importance==importance)
    if group_id is not None:q=q.where(QQNotice.id.in_(select(QQMessage.notice_id).where(QQMessage.group_config_id==group_id,QQMessage.owner_id==user.id)))
    return [service.public_notice(db,n) for n in db.scalars(q.order_by(QQNotice.id.desc()).limit(100))]

@router.post('/pending/{ident}/confirm')
def confirm(ident:int,data:Confirmation,user=Depends(current_user),db=Depends(session),key:str=Header(default='',alias='Idempotency-Key')):
    return mutate(db,user,key,'confirm:'+str(ident),data.model_dump(),lambda:service.confirm_notice(db,user,ident,data))

@router.post('/pending/{ident}/reject')
def reject(ident:int,user=Depends(current_user),db=Depends(session),key:str=Header(default='',alias='Idempotency-Key')):
    def action():
        row=service.own(db,QQNotice,ident,user)
        if row.status=='confirmed':raise HTTPException(409,'通知已确认，请到任务页面处理')
        row.status='rejected';return {'rejected':True}
    return mutate(db,user,key,'reject:'+str(ident),{},action)

@router.get('/status')
async def status(response:Response,user=Depends(current_user),db=Depends(session)):
    response.headers['Cache-Control']='no-store'
    counts=dict(db.execute(select(QQMessage.status,func.count()).where(QQMessage.owner_id==user.id).group_by(QQMessage.status)).all())
    group_rows=list(db.scalars(select(QQGroup).where(QQGroup.owner_id==user.id)))
    connections=[]
    for g in group_rows:
        state='synthetic' if g.synthetic and g.connection not in ('offline','partial') else g.connection
        if not g.enabled or not g.consent:state='disabled'
        elif not g.synthetic and g.last_seen_at and dt(now())-dt(g.last_seen_at)>timedelta(minutes=3):state='stale'
        connections.append({'id':g.id,'state':state,'last_seen_at':g.last_seen_at,'last_synced_at':g.last_synced_at})
    managed=account.policy()
    live_account=await account.connection_status() if managed and managed['owner_id']==user.id and service.live_allowed() else None
    from .replies import policy as reply_policy
    reply_enabled=bool(reply_policy()) and bool(managed and managed['owner_id']==user.id)
    return {'account':live_account,'private_reply_enabled':reply_enabled,'live_enabled':service.live_allowed(),'public_demo':service.enabled('QQ_PUBLIC_DEMO','true'),'worker_enabled':service.enabled('QQ_PROCESSOR_ENABLED','true'),
        'ai_mode':'live' if os.getenv('AI_API_KEY') and os.getenv('QQ_AI_MODE','auto')!='mock' else 'mock','counts':counts,'connections':connections,
        'notice':'已核实指定QQ小号在线，收录群聊与私聊消息。' if live_account and live_account.get('connected') else '接收端状态只表示服务收到事件；未验证真实QQ账号连接。' }
