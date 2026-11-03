"""Explicitly pinned, local QQ account capture. No outbound chat actions."""
import os
import time
import httpx
from sqlalchemy import select
from fastapi import HTTPException
from ...models import QQGroup,User
from ...timeutil import now
from ...db import write_transaction
from .adapter import conversation_key

READ_ACTIONS=frozenset({'get_login_info','get_status','get_group_list','get_friend_list'})
_status={};_checked=0

def policy():
    bot=os.getenv('QQ_MANAGED_BOT_ID','').strip()
    if not bot or not bot.isdigit():return None
    return {'bot_id':bot,'owner_id':os.getenv('QQ_CAPTURE_OWNER_ID','A'),
        'nickname':os.getenv('QQ_MANAGED_NICKNAME',''),
        'groups':os.getenv('QQ_CAPTURE_ALL_GROUPS','false').lower()=='true',
        'private':os.getenv('QQ_CAPTURE_PRIVATE','false').lower()=='true',
        'self':os.getenv('QQ_CAPTURE_SELF','false').lower()=='true'}

async def read_api(action,payload=None):
    from urllib.parse import urlsplit
    if action not in READ_ACTIONS:raise ValueError('Not a permitted account read action')
    base=os.getenv('QQ_ONEBOT_API_URL','').rstrip('/');parsed=urlsplit(base)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost','::1')):raise ValueError('Invalid account API address')
    token=os.getenv('QQ_ONEBOT_API_TOKEN','')
    async with httpx.AsyncClient(timeout=8,follow_redirects=False) as c:
        r=await c.post(base+'/'+action,json=payload or {},headers={'Authorization':'Bearer '+token});r.raise_for_status()
        data=r.json()
        if data.get('status')!='ok' or data.get('retcode',0)!=0:raise ValueError('Account read API unavailable')
        return data.get('data')

async def connection_status():
    global _status,_checked
    p=policy()
    if not p:return None
    if time.monotonic()-_checked<10:return dict(_status)
    state={'configured':True,'connected':False,'nickname':p['nickname'],'account_suffix':p['bot_id'][-4:],
           'capture_groups':p['groups'],'capture_private':p['private'],'capture_self':p['self'],'wrong_account':False}
    try:
        info=await read_api('get_login_info')
        health=await read_api('get_status')
        matched=str(info.get('user_id'))==p['bot_id']
        state.update(connected=matched and health.get('online') is True and health.get('good') is not False,wrong_account=not matched)
        if matched:state['nickname']=info.get('nickname') or p['nickname']
    except Exception:pass
    _status=state;_checked=time.monotonic()
    return dict(state)

def ensure_conversation(db,event):
    p=policy()
    if not p or str(event.self_id)!=p['bot_id']:return None
    key=conversation_key(event)
    if not key:return None
    private=key.startswith('private:')
    if not p['private' if private else 'groups']:return None
    if str(event.user_id)==p['bot_id'] and not p['self']:return None
    existing=db.scalar(select(QQGroup).where(QQGroup.owner_id==p['owner_id'],QQGroup.bot_id==p['bot_id'],QQGroup.group_id==key))
    if existing:return existing  # A per-conversation stop is never undone.
    if not db.get(User,p['owner_id']):raise HTTPException(503,'指定的QQ收录身份不存在')
    row=QQGroup(owner_id=p['owner_id'],bot_id=p['bot_id'],group_id=key,name=('私聊 · '+key[8:]) if private else 'QQ群 · '+key,
        synthetic=False,consent=True,enabled=True,ai_images=False,created_at=now())
    db.add(row);db.flush();return row

async def sync_contacts(db):
    """Discover only the pinned account's conversation metadata, no chat text."""
    from .service import live_allowed
    p=policy()
    if not p or not live_allowed():return {'groups':0,'private':0}
    status=await connection_status()
    if not status or not status['connected']:return {'groups':0,'private':0}
    groups=await read_api('get_group_list') if p['groups'] else []
    friends=await read_api('get_friend_list') if p['private'] else []
    names=[]
    for g in groups or []:names.append((str(g['group_id']),str(g.get('group_name') or g['group_id'])[:90]))
    for friend in friends or []:names.append(('private:'+str(friend['user_id']),'私聊 · '+str(friend.get('remark') or friend.get('nickname') or friend['user_id'])[:80]))
    with write_transaction(db,'qq:account-discovery'):
        if not db.get(User,p['owner_id']):raise HTTPException(503,'指定的QQ收录身份不存在')
        for key,name in names:
            existing=db.scalar(select(QQGroup).where(QQGroup.owner_id==p['owner_id'],QQGroup.bot_id==p['bot_id'],QQGroup.group_id==key))
            if existing:continue
            db.add(QQGroup(owner_id=p['owner_id'],bot_id=p['bot_id'],group_id=key,name=name,synthetic=False,consent=True,enabled=True,ai_images=False,created_at=now()))
        db.commit()
    return {'groups':len(groups or []),'private':len(friends or [])}
