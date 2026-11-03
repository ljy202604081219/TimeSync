"""Opt-in replies to one verified private peer; reuse the existing assistant.

RequestRecord is the durable send journal. Ambiguous sends are never retried:
OneBot has no client idempotency key, so a lost acknowledgement cannot prove failure.
"""
import asyncio
import hashlib
import logging
import os
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from ... import assistant
from ...db import SessionLocal,write_transaction
from ...models import RequestRecord,QQMessage,QQGroup,User,AssistantThread,AssistantProposal
from ...timeutil import dt,now
from . import account

log=logging.getLogger(__name__)
PREFIX='qq-reply:'


def policy():
    from .service import live_allowed,enabled
    p=account.policy();peer=os.getenv('QQ_REPLY_PEER_ID','').strip()
    if not p or not p['private'] or not live_allowed() or not enabled('QQ_REPLY_ENABLED') or not peer.isdigit() or peer==p['bot_id']:return None
    return {**p,'peer_id':peer}


def allowed(group,p):
    return bool(p and group and not group.synthetic and group.enabled and group.consent and
        group.owner_id==p['owner_id'] and group.bot_id==p['bot_id'] and group.group_id=='private:'+p['peer_id'])


def enqueue(db,group,row,event):
    p=policy()
    if not allowed(group,p) or event.post_type!='message' or event.message_type!='private' or str(event.user_id)!=p['peer_id']:return False
    age=(dt(now())-dt(row.sent_at)).total_seconds()
    if age < -60 or age>120:return False  # Never reply to catch-up history.
    key=PREFIX+str(row.id)
    if not db.scalar(select(RequestRecord.id).where(RequestRecord.owner_id==row.owner_id,RequestRecord.key==key)):
        db.add(RequestRecord(owner_id=row.owner_id,key=key,fingerprint=row.content_hash,
            response={'state':'queued','message_id':row.id,'updated_at':now()}))
    return True


def echo(db,group,record):
    p=policy()
    if not allowed(group,p) or not record['raw_text'].startswith('【小号发出】\n'):return False
    digest=hashlib.sha256(record['raw_text'].encode()).hexdigest()
    recent=db.scalars(select(RequestRecord).where(RequestRecord.owner_id==group.owner_id,RequestRecord.key.like(PREFIX+'%')).order_by(RequestRecord.id.desc()).limit(40))
    return any(r.response.get('reply_hash')==digest and (dt(now())-dt(r.response['updated_at'])).total_seconds()<600 for r in recent)


def stamp(db,ident,**fields):
    with write_transaction(db,'qq:reply-state'):
        row=db.get(RequestRecord,ident,populate_existing=True)
        row.response={**row.response,**fields,'updated_at':now()};db.commit()


async def send_private(peer,text):
    p=policy()
    if not p or peer!=p['peer_id']:raise ValueError('Reply peer not authorized')
    # Check the actual account immediately before sending, not a cached badge.
    info=await account.read_api('get_login_info')
    if str(info.get('user_id'))!=p['bot_id']:raise ValueError('Connected account changed')
    base=os.getenv('QQ_ONEBOT_API_URL','').rstrip('/');parsed=urlsplit(base)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1')):raise ValueError('Invalid OneBot address')
    async with httpx.AsyncClient(timeout=15,follow_redirects=False) as c:
        response=await c.post(base+'/send_private_msg',headers={'Authorization':'Bearer '+os.getenv('QQ_ONEBOT_API_TOKEN','')},
            json={'user_id':peer,'message':[{'type':'text','data':{'text':text}}]})
        response.raise_for_status();data=response.json()
        if data.get('status')!='ok' or data.get('retcode',0)!=0 or data.get('data',{}).get('message_id') is None:raise ValueError('OneBot did not acknowledge reply')
        return str(data['data']['message_id'])


def plain(text):
    return text.replace('**','').replace('`','')


def proposal_text(proposal):
    if not proposal:return ''
    payload=proposal['payload'];data=payload.get('data',payload)
    names={'title':'名称','start':'开始','end':'结束','deadline':'截止','duration_minutes':'预计分钟','priority':'优先级'}
    lines=['\n【待确认安排】']+[label+'：'+str(data[key]) for key,label in names.items() if data.get(key) is not None]
    lines+=['回复“确认”保存，或继续说明要调整的内容；回复“取消”放弃。' if proposal['can_confirm'] else '当前约束不允许保存，请调整时间或查看网页诊断。']
    return '\n'.join(lines)


async def process(db,ident):
    p=policy()
    if not p:return
    with write_transaction(db,'qq:reply-claim'):
        job=db.get(RequestRecord,ident,populate_existing=True)
        if not job or job.response.get('state')!='queued':return
        row=db.get(QQMessage,job.response['message_id']);group=db.get(QQGroup,row.group_config_id) if row else None
        if not row or not allowed(group,p) or not row.raw_text or dt(row.expires_at)<dt(now()) or dt(now())-dt(row.received_at)>timedelta(minutes=10):
            job.response={**job.response,'state':'skipped','updated_at':now()};db.commit();return
        text=row.raw_text;user=db.get(User,p['owner_id'])
        thread_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'timesync:qq:'+p['owner_id']+':'+p['bot_id']+':'+p['peer_id']))
        thread=db.get(AssistantThread,thread_id)
        if not thread:db.add(AssistantThread(id=thread_id,owner_id=user.id,revision=0,messages=[],context={},updated_at=now()))
        job.response={**job.response,'state':'generating','thread_id':thread_id,'updated_at':now()};db.commit()
    proposal=None
    try:
        if text.strip().strip('。！!')=='确认':
            previous=db.scalar(select(RequestRecord).where(RequestRecord.owner_id==user.id,RequestRecord.key.like(PREFIX+'%'),RequestRecord.id<ident).order_by(RequestRecord.id.desc()).limit(1))
            candidate=previous.response.get('proposal_id') if previous and previous.response.get('state')=='sent' else None
            item=db.get(AssistantProposal,candidate) if candidate else None
            thread=db.get(AssistantThread,thread_id,populate_existing=True)
            if not item or item.owner_id!=user.id or item.payload.get('thread_id')!=thread_id or thread.context.get('pending_proposal_id')!=candidate:
                reply='当前没有刚才已展示的待确认方案。请先告诉我要添加或调整什么安排。'
            else:
                from ...main import mutation
                outcome=mutation(db,user,'qq-confirm:'+str(row.id),'assistant-confirm',{'id':candidate},lambda:assistant.apply_proposal(db,user,candidate))
                reply='已保存到你的时聚日程。'+ ('\n'+str(outcome.get('notice','')) if outcome.get('notice') else '')
        elif len(text)>1200:reply='这条消息较长，请拆成几条发给我，每条不超过1200字。'
        else:
            result=await assistant.chat(db,user,assistant.ChatInput(message=text,conversation_id=thread_id,request_id='qq-message:'+str(row.id)))
            reply=plain(result['answer']);proposal=result.get('proposal')
            if result.get('mode')=='mock':reply='【规则演示，当前非真实AI】\n'+reply
            if result.get('response_notice'):reply=result['response_notice']+'\n'+reply
            reply=reply[:3000]+proposal_text(proposal)
    except HTTPException as exc:
        db.rollback();reply=str(exc.detail)
    except Exception:
        db.rollback();reply='刚才处理失败，请稍后再发一次；没有自动执行新的日程修改。'
    # A stop/revocation or peer rebind during model generation takes effect before send.
    db.rollback();group=db.get(QQGroup,row.group_config_id,populate_existing=True)
    if policy()!=p or not allowed(group,p):stamp(db,ident,state='skipped');return
    digest=hashlib.sha256(('【小号发出】\n'+reply).encode()).hexdigest()
    stamp(db,ident,state='sending',reply_hash=digest,proposal_id=proposal['id'] if proposal else None)
    try:
        sent=await send_private(p['peer_id'],reply)
        stamp(db,ident,state='sent',reply_message_id=sent)
    except Exception as exc:
        # The service may have sent successfully before the HTTP response was lost.
        stamp(db,ident,state='uncertain',error='发送结果未确认，不自动重发')
        log.warning('qq_reply_unconfirmed type=%s',type(exc).__name__)


async def worker(stop):
    while not stop.is_set():
        try:
            if policy():
                with SessionLocal() as db:
                    # ponytail: small per-account journal scan; use a dedicated indexed outbox at larger scale.
                    jobs=list(db.scalars(select(RequestRecord).where(RequestRecord.key.like(PREFIX+'%')).order_by(RequestRecord.id.desc()).limit(100)))
                    for job in reversed(jobs):
                        if stop.is_set():break
                        if job.response.get('state')=='queued':await process(db,job.id)
        except asyncio.CancelledError:raise
        except Exception as exc:log.warning('qq_reply_worker_failed type=%s',type(exc).__name__)
        try:await asyncio.wait_for(stop.wait(),timeout=1)
        except asyncio.TimeoutError:pass
