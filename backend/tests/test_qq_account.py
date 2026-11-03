import asyncio
import pytest
from sqlalchemy import select
from app.models import QQGroup,QQMessage
from app.integrations.qq import account
from app.integrations.qq.schemas import Event
from app.integrations.qq.adapter import normalize

@pytest.fixture(autouse=True)
def pinned(monkeypatch):
    for key,value in {'QQ_MANAGED_BOT_ID':'888001','QQ_CAPTURE_OWNER_ID':'A','QQ_MANAGED_NICKNAME':'合成测试小号',
        'QQ_CAPTURE_ALL_GROUPS':'true','QQ_CAPTURE_PRIVATE':'true','QQ_CAPTURE_SELF':'true',
        'QQ_LIVE_ENABLED':'true','QQ_PUBLIC_DEMO':'false','SANDBOX_MODE':'false','QQ_EVENT_SECRET':'synthetic-auth-only-1234567890'}.items():monkeypatch.setenv(key,value)
    monkeypatch.setattr(account,'_checked',0)

def event(**kwargs):
    return Event(time=1793667600,message_type='private',post_type='message',self_id='888001',user_id='777001',
        message_id='private-1',message=[{'type':'text','data':{'text':'合成测试'}}],**kwargs)

def test_incoming_self_and_wrong_account_capture(system):
    call,factory,client=system;headers={'Authorization':'Bearer synthetic-auth-only-1234567890'}
    incoming=event().model_dump()
    assert client.post('/api/v1/qq/events',headers=headers,json=incoming).status_code==200
    assert client.post('/api/v1/qq/events',headers=headers,json=incoming).json()['results'][0]['duplicate']
    outgoing={**incoming,'post_type':'message_sent','user_id':'888001','target_id':'777001','message_id':'private-2'}
    assert client.post('/api/v1/qq/events',headers=headers,json=outgoing).status_code==200
    assert client.post('/api/v1/qq/events',headers=headers,json={**incoming,'self_id':'888002'}).status_code==403
    assert call('GET','/api/v1/qq/messages',member='B').json()==[]
    with factory() as db:
        groups=list(db.scalars(select(QQGroup).where(QQGroup.bot_id=='888001')))
        assert len(groups)==1 and groups[0].group_id=='private:777001' and groups[0].owner_id=='A'
        messages=list(db.scalars(select(QQMessage)));assert len(messages)==2
        assert messages[-1].raw_text.startswith('【小号发出】')
        ident=groups[0].id
    assert call('PATCH',f'/api/v1/qq/groups/{ident}',json={'enabled':False}).status_code==200
    assert client.post('/api/v1/qq/events',headers=headers,json={**incoming,'message_id':'private-3'}).status_code==403

def test_unpinned_or_disabled_scope_cannot_capture(system,monkeypatch):
    _,factory,_=system
    with factory() as db:
        monkeypatch.setenv('QQ_CAPTURE_PRIVATE','false');assert account.ensure_conversation(db,event()) is None
        monkeypatch.setenv('QQ_MANAGED_BOT_ID','888002');assert account.ensure_conversation(db,event()) is None
    outgoing=Event.model_validate({**event().model_dump(),'user_id':'888001','target_id':'777001'})
    assert normalize(outgoing) is None

@pytest.mark.parametrize('online,bot,connected',[(True,888001,True),(False,888001,False),(True,888002,False)])
def test_online_status_checks_health_and_account(monkeypatch,online,bot,connected):
    async def read(action,payload=None):
        return {'user_id':bot,'nickname':'合成测试小号'} if action=='get_login_info' else {'online':online,'good':True}
    monkeypatch.setattr(account,'read_api',read)
    result=asyncio.run(account.connection_status());assert result['connected']==connected

def test_account_api_never_allows_sending():
    with pytest.raises(ValueError):asyncio.run(account.read_api('send_private_msg',{}))
