"""One-call grounded reads; stale/wrong ranges and writes retain validation."""
import asyncio
import json
import pytest
from app import assistant
from app.models import User,AssistantThread,BusyInterval,Task
from app.plans import snapshot


@pytest.fixture(autouse=True)
def live_model(monkeypatch):
    monkeypatch.setenv('AI_API_KEY','test-only');monkeypatch.setenv('ASSISTANT_MODE','auto')
    monkeypatch.setenv('ASSISTANT_MODEL','');monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    monkeypatch.setattr(assistant,'now',lambda:'2026-11-02T09:00:00+08:00')


def ask(system,message='今天有什么安排？',ident=None,member='A'):
    r=system[0]('POST','/api/v1/assistant/chat',member=member,json={'message':message,'conversation_id':ident})
    assert r.status_code==200,r.text
    return r.json()


def test_authorized_calendar_question_finishes_in_one_call_without_writes(system,monkeypatch):
    calls=[]
    async def model(_system,content):
        d=json.loads(content);calls.append(d)
        assert '高等数学' in str(d['query_context']['events'])
        return {'intent':'agenda','date':'2026-11-02','draft_answer':'今天上午有高等数学，具体时间见日历。','memory':'用户偏好早上学习。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    with system[1]() as db:before=snapshot(db,db.get(User,'A'))
    result=ask(system)
    assert len(calls)==1 and result['answer_source']=='model'
    assert result['answer']=='今天上午有高等数学，具体时间见日历。' and result['facts'] and not result['proposal']
    with system[1]() as db:
        assert snapshot(db,db.get(User,'A'))==before
        context=db.get(AssistantThread,result['conversation_id']).context
        assert 'draft_answer' not in context and context['memory']=='用户偏好早上学习。'


def test_wrong_date_hint_requeries_actual_model_date_instead_of_using_ungrounded_draft(system,monkeypatch):
    calls=[]
    async def model(_system,content):
        d=json.loads(content);calls.append(d)
        if 'trusted_facts' not in d:
            return {'intent':'free','date':'2026-12-01','period':'afternoon','draft_answer':'错误范围的回答必须丢弃'}
        assert d['trusted_facts']['start']=='2026-12-01T12:00:00+08:00'
        assert 'draft_answer' not in d['understanding']
        return {'answer':'12月1日下午有已记录日程之间的参考空档，需核对本人是否方便。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=ask(system,'十二月一日下午有空吗？')
    assert len(calls)==2 and '错误范围' not in result['answer']


def test_schedule_change_cannot_use_draft_or_skip_confirmation(system,monkeypatch):
    calls=[]
    async def model(_system,content):
        d=json.loads(content);calls.append(d)
        if 'trusted_facts' in d:return {'answer':'请核对慢跑时间，确认后才会保存。'}
        return {'action':'create_event','date':'2026-11-08','payload':{'title':'慢跑','start':'2026-11-08T18:15:00+08:00','end':'2026-11-08T18:45:00+08:00'},
                'evidence':{'title':'慢跑','date':'2026年11月8日','start':'18:15','end':'18:45'},'draft_answer':'已经保存了'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    with system[1]() as db:before=snapshot(db,db.get(User,'A'))
    result=ask(system,'2026年11月8日18:15至18:45慢跑')
    assert len(calls)==2 and result['proposal'] and '已经保存了' not in result['answer']
    with system[1]() as db:assert snapshot(db,db.get(User,'A'))==before
    assert system[0]('POST','/api/v1/assistant/proposals/'+result['proposal']['id']+'/confirm',json={'confirmed':True}).status_code==200


def test_data_changed_during_model_wait_invalidates_draft(system,monkeypatch):
    calls=[]
    async def model(_system,content):
        d=json.loads(content);calls.append(d)
        if 'trusted_facts' not in d:
            with system[1]() as db:
                db.add(BusyInterval(owner_id='A',title='后来加入的实验',start='2026-11-02T15:00:00+08:00',end='2026-11-02T16:00:00+08:00',kind='unavailable'));db.commit()
            return {'intent':'agenda','date':'2026-11-02','draft_answer':'旧结果'}
        assert any(e['title']=='后来加入的实验' for e in d['trusted_facts']['events'])
        return {'answer':'最新日历增加了15:00至16:00的实验。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=ask(system)
    assert len(calls)==2 and result['answer']!='旧结果'


def test_single_pass_context_and_history_never_include_other_owner(system,monkeypatch):
    seen=[]
    async def model(_system,content):
        d=json.loads(content);seen.append(d)
        assert all(t['id'] not in (1,2,3) for t in d['query_context']['tasks'])
        assert not d['recent_history']
        return {'intent':'agenda','date':'2026-11-02','draft_answer':'这是B自己的日历结果。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=ask(system,member='B')
    assert len(seen)==1 and result['answer_source']=='model'


def test_missing_task_still_uses_server_diagnostic_not_first_draft(system,monkeypatch):
    seen=[]
    async def model(_system,content):
        d=json.loads(content);seen.append(d)
        if 'trusted_facts' not in d:return {'intent':'agenda','date':'2026-11-02','task_query':'不存在的课程任务','draft_answer':'编造的任务安排'}
        assert '未找到任务' in d['server_guidance']
        return {'answer':'没有找到这个任务，请核对名称。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=ask(system,'不存在的课程任务安排在哪？')
    assert len(seen)==2 and '编造' not in result['answer']


def test_literal_time_range_does_not_turn_into_an_invented_task_deadline(system,monkeypatch):
    async def model(_system,content):
        d=json.loads(content)
        if 'trusted_facts' in d:return {'answer':'20点到21点的复习日程已整理，请核对后确认。'}
        return {'action':'create_task','date':'2026-11-08','payload':{'title':'高数复习','deadline':'2026-11-08T21:00:00+08:00','duration_minutes':60}}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=ask(system,'帮我2026年11月8日晚上8点到9点添加“高数复习”')
    p=result['proposal']
    assert p['action']=='create_event' and p['payload']['start']=='2026-11-08T20:00:00+08:00'
    assert p['payload']['end']=='2026-11-08T21:00:00+08:00' and 'deadline' not in p['payload']
    assert system[0]('POST','/api/v1/assistant/proposals/'+p['id']+'/confirm',json={'confirmed':True}).status_code==200


def test_free_time_question_with_learning_subject_does_not_require_existing_task(system,monkeypatch):
    seen=[]
    async def model(_system,content):
        d=json.loads(content);seen.append(d)
        assert d['query_context']['free'] or d['query_context']['observed_gaps']
        return {'intent':'free','date':'2026-11-02','task_query':'高数复习','draft_answer':'可以参考日历中已有的空档学习高数，不需要先创建同名任务。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=ask(system,'今天有空复习高数吗？')
    assert len(seen)==1 and result['answer_source']=='model' and not result['applied']


def test_known_task_explanation_can_use_same_grounded_context_once(system,monkeypatch):
    calls=[]
    async def model(_system,content):
        d=json.loads(content);calls.append(d)
        assert d['query_context']['schedule'] and 'plan_reason' in d['query_context']
        return {'intent':'explain','date':'2026-11-02','task_query':'实验报告','draft_answer':'系统结合截止时间、固定课程和尽量保留原安排的目标生成计划。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=ask(system,'为什么把实验报告放在这个时间？')
    assert len(calls)==1 and result['answer_source']=='model'
