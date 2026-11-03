import asyncio
import types
import httpx
import pytest
from app import assistant
from app.models import User
from app.plans import snapshot


def test_default_budget_leaves_time_for_grounded_answer(system,monkeypatch):
    monkeypatch.delenv('ASSISTANT_TIMEOUT_SECONDS',raising=False)
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    calls=[]
    async def wait(coro,timeout):
        calls.append(timeout);return await asyncio.wait_for(coro,timeout)
    proxy=types.SimpleNamespace(**{k:getattr(asyncio,k) for k in dir(asyncio) if not k.startswith('__')})
    proxy.wait_for=wait;monkeypatch.setattr(assistant,'asyncio',proxy)
    class Provider:
        async def understand(self,*_):return assistant.Understanding(intent='agenda',date='2026-11-03')
        async def respond(self,*_):return '这是基于已记录日程的回答。'
    monkeypatch.setattr(assistant,'provider',lambda:Provider())
    with system[1]() as db:
        result=asyncio.run(assistant.chat(db,db.get(User,'A'),assistant.ChatInput(message='今天有什么安排？')))
        assert calls[0]==30 and 55<calls[1]<=60
        assert result['answer_source']=='model' and result['response_error'] is None


@pytest.mark.parametrize('failure,code,word',[
    ('timeout','timeout','超时'),('format','format','格式'),('http','http_429','繁忙'),('network','unavailable','暂不可用')])
def test_answer_failure_is_specific_and_never_changes_business_data(system,monkeypatch,failure,code,word):
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    class Provider:
        async def understand(self,*_):return assistant.Understanding(intent='agenda',date='2026-11-03')
        async def respond(self,*_):
            if failure=='timeout':raise asyncio.TimeoutError()
            if failure=='format':raise ValueError('private-not-to-log')
            if failure=='http':
                r=httpx.Response(429,request=httpx.Request('POST','https://model.invalid'))
                raise httpx.HTTPStatusError('private-not-to-log',request=r.request,response=r)
            raise httpx.ConnectError('private-not-to-log')
    monkeypatch.setattr(assistant,'provider',lambda:Provider())
    with system[1]() as db:
        user=db.get(User,'A');before=snapshot(db,user)
        result=asyncio.run(assistant.chat(db,user,assistant.ChatInput(message='今天有什么安排？')))
        assert result['response_error']==code and word in result['response_notice']
        assert result['answer_source']=='fallback' and result['facts']
        assert 'private-not-to-log' not in str(result)
        assert snapshot(db,user)==before
