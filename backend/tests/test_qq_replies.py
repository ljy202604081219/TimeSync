import asyncio
import httpx
import pytest
from sqlalchemy import select,func
from app import assistant
from app.models import RequestRecord,QQMessage,QQGroup,BusyInterval,AssistantThread
from app.integrations.qq import replies,service,account
from app.integrations.qq.schemas import Event
from app.timeutil import dt

ANCHOR='2026-11-03T09:00:00+08:00'

@pytest.fixture(autouse=True)
def reply_setup(monkeypatch):
    for k,v in {'QQ_MANAGED_BOT_ID':'888001','QQ_CAPTURE_OWNER_ID':'A','QQ_CAPTURE_PRIVATE':'true','QQ_CAPTURE_SELF':'true',
        'QQ_CAPTURE_ALL_GROUPS':'true','QQ_REPLY_ENABLED':'true','QQ_REPLY_PEER_ID':'777001','QQ_LIVE_ENABLED':'true','QQ_PUBLIC_DEMO':'false','SANDBOX_MODE':'false',
        'QQ_EVENT_SECRET':'synthetic-reply-secret-1234567890','ASSISTANT_MODE':'mock','AI_API_KEY':''}.items():monkeypatch.setenv(k,v)
    for module in (replies,service,assistant):monkeypatch.setattr(module,'now',lambda:ANCHOR)

def incoming(system,text='今天有什么安排？',mid='one',**kw):
    event={'post_type':'message','message_type':'private','self_id':'888001','user_id':'777001','message_id':mid,
        'time':int(dt(ANCHOR).timestamp()),'message':[{'type':'text','data':{'text':text}}],**kw}
    r=system[2].post('/api/v1/qq/events',headers={'Authorization':'Bearer synthetic-reply-secret-1234567890'},json=event)
    assert r.status_code==200,r.text
    return r

def drain(factory):
    with factory() as db:
        ids=db.scalars(select(RequestRecord.id).where(RequestRecord.key.like('qq-reply:%')).order_by(RequestRecord.id)).all()
        for ident in ids:asyncio.run(replies.process(db,ident))

def test_real_assistant_path_memory_idempotence_and_no_other_owner(system,monkeypatch):
    sent=[]
    async def send(peer,text):sent.append((peer,text));return str(len(sent))
    monkeypatch.setattr(replies,'send_private',send)
    incoming(system);incoming(system);drain(system[1]);drain(system[1])
    assert len(sent)==1 and sent[0][0]=='777001' and '程序设计' in sent[0][1]
    incoming(system,'那明天呢？','two');drain(system[1])
    assert len(sent)==2
    with system[1]() as db:
        threads=list(db.scalars(select(AssistantThread)));assert len(threads)==1 and threads[0].owner_id=='A'
        assert len(threads[0].messages)==4
        assert db.scalar(select(func.count()).select_from(QQMessage))==2
    assert system[0]('GET','/api/v1/qq/messages',member='B').json()==[]

def test_other_peer_groups_self_and_history_never_queue_replies(system):
    incoming(system,mid='other',user_id='777002')
    incoming(system,mid='group',message_type='group',group_id='555001')
    incoming(system,mid='self',post_type='message_sent',user_id='888001',target_id='777001')
    incoming(system,mid='history',time=int(dt(ANCHOR).timestamp())-3600)
    with system[1]() as db:assert db.scalar(select(func.count()).select_from(RequestRecord).where(RequestRecord.key.like('qq-reply:%')))==0

def test_default_off_and_public_sandbox_never_reply(monkeypatch):
    monkeypatch.setenv('QQ_REPLY_ENABLED','false');assert replies.policy() is None
    monkeypatch.setenv('QQ_REPLY_ENABLED','true');monkeypatch.setenv('SANDBOX_MODE','true');assert replies.policy() is None
    monkeypatch.setenv('SANDBOX_MODE','false');monkeypatch.setenv('QQ_CAPTURE_PRIVATE','false');assert replies.policy() is None

def test_send_timeout_does_not_repeat_and_echo_is_not_reprocessed(system,monkeypatch):
    called=[]
    async def send(peer,text):
        called.append(text)
        incoming(system,text,mid='echo',post_type='message_sent',user_id='888001',target_id='777001')
        raise httpx.ReadTimeout('synthetic timeout')
    monkeypatch.setattr(replies,'send_private',send)
    incoming(system);drain(system[1]);drain(system[1])
    assert len(called)==1
    with system[1]() as db:
        job=db.scalar(select(RequestRecord).where(RequestRecord.key.like('qq-reply:%')));assert job.response['state']=='uncertain'
        echo=db.scalar(select(QQMessage).where(QQMessage.message_id=='echo'));assert echo.status=='ignored' and '回执' in echo.error

def test_confirmation_uses_original_proposal_and_saves_once(system,monkeypatch):
    sent=[]
    async def send(peer,text):sent.append(text);return str(len(sent))
    monkeypatch.setattr(replies,'send_private',send)
    with system[1]() as db:before=db.scalar(select(func.count()).select_from(BusyInterval))
    incoming(system,'明天19点到20点安排跑步','proposal');drain(system[1])
    assert '待确认安排' in sent[-1],sent[-1]
    with system[1]() as db:assert db.scalar(select(func.count()).select_from(BusyInterval))==before
    incoming(system,'确认','confirmation');drain(system[1]);drain(system[1])
    assert '已保存' in sent[-1]
    with system[1]() as db:assert db.scalar(select(func.count()).select_from(BusyInterval))==before+1


def test_private_auto_add_sends_saved_receipt_without_confirmation(system,monkeypatch):
    monkeypatch.delenv('ASSISTANT_AUTO_CREATE',raising=False)
    sent=[]
    async def send(peer,text):sent.append(text);return str(len(sent))
    monkeypatch.setattr(replies,'send_private',send)
    with system[1]() as db:before=db.scalar(select(func.count()).select_from(BusyInterval))
    incoming(system,'明天19点到20点安排跑步','auto-add');drain(system[1]);drain(system[1])
    assert len(sent)==1 and '已添加' in sent[0] and '待确认安排' not in sent[0] and '回复“确认”' not in sent[0]
    with system[1]() as db:assert db.scalar(select(func.count()).select_from(BusyInterval))==before+1

def test_stop_during_generation_prevents_send(system,monkeypatch):
    called=[]
    async def chat(db,user,data):
        group=db.scalar(select(QQGroup).where(QQGroup.group_id=='private:777001'));group.enabled=False;db.commit()
        return {'answer':'synthetic','mode':'mock','proposal':None}
    async def send(*args):called.append(args);return 'none'
    monkeypatch.setattr(assistant,'chat',chat);monkeypatch.setattr(replies,'send_private',send)
    incoming(system);drain(system[1]);assert not called

def test_sender_rechecks_account_and_sends_text_segments(monkeypatch):
    async def identity(action):return {'user_id':'888001'}
    monkeypatch.setattr(account,'read_api',identity);monkeypatch.setenv('QQ_ONEBOT_API_URL','http://127.0.0.1:3000')
    seen=[]
    def handler(request):
        import json
        seen.append(json.loads(request.content));assert request.url.path=='/send_private_msg'
        return httpx.Response(200,json={'status':'ok','retcode':0,'data':{'message_id':123}})
    original=httpx.AsyncClient
    monkeypatch.setattr(replies.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    assert asyncio.run(replies.send_private('777001','[CQ:at,qq=123]'))=='123'
    assert seen[0]['message']==[{'type':'text','data':{'text':'[CQ:at,qq=123]'}}]
    with pytest.raises(ValueError):asyncio.run(replies.send_private('777002','not allowed'))
    async def wrong(action):return {'user_id':'888002'}
    monkeypatch.setattr(account,'read_api',wrong)
    with pytest.raises(ValueError):asyncio.run(replies.send_private('777001','not allowed'))
