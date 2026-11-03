"""Semantic understanding and grounded prose, with no real model requests."""
import asyncio
import json

import pytest
from sqlalchemy import select, func

from app import assistant
from app.models import User, BusyInterval, AssistantThread, AiUsage
from app.plans import snapshot


@pytest.fixture(autouse=True)
def live_mock(monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','auto')
    monkeypatch.setenv('AI_API_KEY','test-only')
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    monkeypatch.setattr(assistant,'now',lambda:'2026-11-02T09:00:00+08:00')


def ask(system,message,ident=None,member='A'):
    r=system[0]('POST','/api/v1/assistant/chat',member=member,json={'message':message,'conversation_id':ident})
    assert r.status_code==200,r.text
    return r.json()


def event(start='18:15',end='18:45',day='2026-11-08',evidence=None):
    return {'intent':'change','action':'create_event','date':day+'T00:00:00+08:00','period':'evening',
            'payload':{'title':'慢跑','start':day+'T'+start+':00+08:00','end':day+'T'+end+':00+08:00','kind':'unavailable'},
            'evidence':evidence or {'title':'慢跑','date':'这个礼拜天','start':'傍晚六点一刻','end':'跑半小时'}}


def test_semantic_quarter_hour_and_half_hour_then_relative_revision(system,monkeypatch):
    plans=iter([event(),event('18:45','19:15',evidence={'start':'往后挪半小时','end':'往后挪半小时'}),
                event('18:45','19:15','2026-11-09',{'date':'下个周一','start':'下个周一','end':'下个周一'})])
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'已整理为待确认方案，请核对卡片。'}
        return next(plans)
    monkeypatch.setattr(assistant.ai,'call_model',model)
    with system[1]() as db:before=snapshot(db,db.get(User,'A'))
    a=ask(system,'这个礼拜天傍晚六点一刻去操场慢跑，跑半小时')
    assert a['answer_source']=='model' and a['proposal']['can_confirm']
    assert a['proposal']['payload']['start']=='2026-11-08T18:15:00+08:00'
    b=ask(system,'往后挪半小时',a['conversation_id'])
    assert b['proposal']['payload']['start']=='2026-11-08T18:45:00+08:00'
    assert b['proposal']['payload']['end']=='2026-11-08T19:15:00+08:00'
    c=ask(system,'换成下个周一吧',a['conversation_id'])
    assert c['proposal']['payload']['start']=='2026-11-09T18:45:00+08:00'
    with system[1]() as db:assert snapshot(db,db.get(User,'A'))==before


def test_move_preserves_known_duration_when_model_reuses_old_end_evidence(system,monkeypatch):
    plans=iter([event(),event('18:45','19:15',evidence={'start':'往后挪半小时','end':'跑半小时'}),
                event('18:45','19:15','2026-11-09',{'date':'下个周一','start':'傍晚六点一刻','end':'跑半小时'})])
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'请核对待确认方案。'}
        return next(plans)
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'这个礼拜天傍晚六点一刻去操场慢跑，跑半小时')
    b=ask(system,'往后挪半小时',a['conversation_id'])
    assert b['proposal']['payload']['end']=='2026-11-08T19:15:00+08:00'
    c=ask(system,'换成下个周一吧',a['conversation_id'])
    assert c['proposal']['payload']['start']=='2026-11-09T18:45:00+08:00'
    assert c['proposal']['payload']['end']=='2026-11-09T19:15:00+08:00'


def test_model_prose_receives_only_authorized_facts_and_history(system,monkeypatch):
    seen=[]
    async def model(_system,content):
        data=json.loads(content);seen.append(data)
        if 'trusted_facts' not in data:return {'intent':'advice','date':'2026-11-02T00:00:00+08:00'}
        return {'answer':'今天先核对实验报告的DDL，再留出连续时间完成它。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'今天有点忙，帮我理理先做什么')
    b=ask(system,'那我应该先做哪一步？',a['conversation_id'])
    assert b['answer_source']=='model' and b['proposal'] is None
    assert b['answer'].startswith('今天先核对')
    answer_calls=[d for d in seen if 'trusted_facts' in d]
    assert len(answer_calls)==2 and answer_calls[-1]['history']
    assert all(t['id'] in {1,2,3} for t in answer_calls[0]['trusted_facts']['tasks'])
    with system[1]() as db:
        assert all(t['id'] in [x.id for x in db.scalars(select(assistant.Task).where(assistant.Task.owner_id=='A'))] for t in answer_calls[0]['trusted_facts']['tasks'])
    assert 'Bearer' not in str(seen) and 'test-only' not in str(seen)
    bcall=ask(system,'今天有什么安排？',member='B')
    assert all(t['id'] not in {1,2,3} for t in bcall['facts']['tasks'])


@pytest.mark.parametrize('failure',[asyncio.TimeoutError(),ValueError('bad JSON')])
def test_answer_failure_retains_verified_result_and_releases_guard(system,monkeypatch,failure):
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):raise failure
        return {'intent':'agenda','date':'2026-11-02T00:00:00+08:00'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'今天有什么安排？')
    assert a['answer_source']=='fallback' and '高等数学' in a['answer'] and a['response_notice']
    with system[1]() as db:
        assert db.scalar(select(func.count()).select_from(AiUsage).where(AiUsage.status=='reserved'))==0


def test_prose_failure_does_not_lose_valid_confirmation_card(system,monkeypatch):
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'unusable':'text'}
        return event()
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'这个礼拜天傍晚六点一刻去操场慢跑，跑半小时')
    assert a['answer_source']=='fallback' and a['proposal']['can_confirm']
    assert system[0]('POST',f'/api/v1/assistant/proposals/{a["proposal"]["id"]}/confirm',json={'confirmed':True}).status_code==200


@pytest.mark.parametrize('bad_evidence',[{'start':'八点','end':'八点'},{'start':'八点','end':'不存在的证据'}])
def test_semantic_event_does_not_accept_invented_end(system,monkeypatch,bad_evidence):
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'几点结束？请补充后再核对保存。'}
        return event('20:00','22:00','2026-11-02',{'title':'慢跑','date':'今晚',**bad_evidence})
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'今晚八点慢跑')
    assert a['proposal'] is None and '22:00' not in a['answer']
    with system[1]() as db:
        thread=db.get(AssistantThread,a['conversation_id'])
        assert not thread.context['pending_payload'].get('end')


def test_recorded_gaps_are_not_misreported_as_configured_free_time(system,monkeypatch):
    async def model(_system,content):
        data=json.loads(content)
        if 'trusted_facts' in data:
            f=data['trusted_facts']
            assert not f['availability_configured'] and not f['free'] and f['observed_gaps']
            return {'answer':'这天下午没有已记录日程，可以考虑复习；尚未配置可用时间，需要你确认是否方便。'}
        return {'intent':'free','date':'2026-12-01T00:00:00+08:00','period':'afternoon'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'12月1日下午我能复习吗？')
    assert '需要你确认' in a['answer'] and a['proposal'] is None


def test_suggestion_is_not_overridden_by_literal_clock_parser(system,monkeypatch):
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'可以把跑步作为备选，但还需要核对你的时间，没有创建安排。'}
        return {'intent':'advice','date':'2026-11-03T00:00:00+08:00'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'想听听建议，明天八点跑步怎么样')
    assert a['proposal'] is None and a['answer_source']=='model'


def test_model_date_only_and_naive_iso_times_normalize_to_shanghai(system,monkeypatch):
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'请核对周日晚的慢跑安排。'}
        result=event();result['date']='2026-11-08'
        result['payload']['start']='2026-11-08T18:15:00'
        result['payload']['end']='2026-11-08T18:45:00'
        return result
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'这个礼拜天傍晚六点一刻去操场慢跑，跑半小时')
    assert a['proposal']['can_confirm']
    assert a['proposal']['payload']['start']=='2026-11-08T18:15:00+08:00'


def test_invalid_pending_times_do_not_block_corrected_semantic_input():
    u=assistant.Understanding.model_validate(event())
    previous={'date':'2026-11-08T00:00:00+08:00','pending_action':'create_event',
              'pending_payload':{'_date':'2026-11-08T00:00:00+08:00','title':'慢跑','start':'bad','end':'bad'}}
    result=assistant.grounded_event(u,'这个礼拜天傍晚六点一刻去操场慢跑，跑半小时',previous)
    assert result.payload['start']=='2026-11-08T18:15:00+08:00'
    assert result.payload['end']=='2026-11-08T18:45:00+08:00'


def test_general_today_advice_does_not_silently_exclude_morning(system,monkeypatch):
    async def model(_system,content):
        data=json.loads(content)
        if 'trusted_facts' in data:
            assert data['trusted_facts']['start']=='2026-11-02T00:00:00+08:00'
            assert any(e['title']=='高等数学' for e in data['trusted_facts']['events'])
            return {'answer':'上午有高等数学，建议结合剩余时间安排学习。'}
        return {'intent':'advice','date':'2026-11-02','period':'evening'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'结合今天安排给些建议')
    assert a['answer_source']=='model'
