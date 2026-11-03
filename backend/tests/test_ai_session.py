"""Connection reuse and model routing without live requests or private data."""
import asyncio
import json
import httpx
import pytest
from app import ai,assistant
from app.models import User
from app.plans import snapshot


@pytest.fixture
def model_client(monkeypatch):
    clients=[];calls=[]
    monkeypatch.setenv('AI_API_KEY','private-test-only')
    monkeypatch.setenv('AI_PROVIDER','mimo');monkeypatch.setenv('AI_MODEL','mimo-v2.6-pro')
    monkeypatch.setenv('AI_BASE_URL','https://api.xiaomimimo.com/v1')
    class Client:
        def __init__(self,**_):self.closed=False;clients.append(self)
        async def __aenter__(self):return self
        async def __aexit__(self,*_):self.closed=True
        async def post(self,url,headers,json):
            calls.append({'client':self,'payload':json})
            body=__import__('json').loads(json['messages'][1]['content'])
            content='{"answer":"从多人协调页面选择候选时间。"}' if 'trusted_facts' in body else '{"intent":"help"}'
            return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':content}}]})
    monkeypatch.setattr(ai.httpx,'AsyncClient',Client)
    return clients,calls


def test_one_connection_for_both_calls_and_normal_model_restored(model_client):
    clients,calls=model_client
    async def run():
        async with ai.model_session('mimo-v2.6-flash'):
            await ai.call_model('system','{}');await ai.call_model('system','{}')
        assert ai._session_client.get() is None and ai._session_model.get() is None
        await ai.call_model('system','{}')
    asyncio.run(run())
    assert len(clients)==2 and all(c.closed for c in clients)
    assert [c['payload']['model'] for c in calls]==['mimo-v2.6-flash','mimo-v2.6-flash','mimo-v2.6-pro']
    assert calls[0]['client'] is calls[1]['client']
    assert calls[0]['payload']['thinking']=={'type':'disabled'}


def test_parallel_turns_do_not_share_clients_or_model_overrides(model_client):
    clients,calls=model_client
    async def turn(model):
        async with ai.model_session(model):
            await asyncio.sleep(0)
            await ai.call_model('system','{}')
            assert ai._session_model.get()==model
    async def run():await asyncio.gather(turn('mimo-v2.6-pro'),turn('mimo-v2.6-flash'))
    asyncio.run(run())
    assert len(clients)==2 and calls[0]['client'] is not calls[1]['client']
    assert {c['payload']['model'] for c in calls}=={'mimo-v2.6-pro','mimo-v2.6-flash'}


def test_cancelled_turn_closes_connection_and_restores_context(model_client):
    async def run():
        with pytest.raises(asyncio.CancelledError):
            async with ai.model_session('mimo-v2.6-flash'):raise asyncio.CancelledError()
        assert ai._session_client.get() is None and ai._session_model.get() is None
    asyncio.run(run());assert model_client[0][0].closed


def test_assistant_only_override_keeps_two_verified_stages_and_does_not_write_schedule(system,model_client,monkeypatch):
    clients,calls=model_client
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('ASSISTANT_MODEL','mimo-v2.6-flash')
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    with system[1]() as db:
        user=db.get(User,'A');before=snapshot(db,user)
        result=asyncio.run(assistant.chat(db,user,assistant.ChatInput(message='怎么创建多人会议？')))
        assert result['answer_source']=='model' and result['facts']
        assert snapshot(db,user)==before and len(clients)==1 and clients[0].closed
        assert len(calls)==2 and all(c['payload']['model']=='mimo-v2.6-flash' for c in calls)
        assert 'private-test-only' not in json.dumps(result,ensure_ascii=False)
