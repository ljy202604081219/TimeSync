"""Conversation memory and partial requests; no paid model requests."""
import json

import pytest
from sqlalchemy import delete, select

from app import assistant
from app.models import AssistantThread, Availability, Task, User
from app.plans import snapshot


@pytest.fixture(autouse=True)
def model_mode(monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','auto')
    monkeypatch.setenv('AI_API_KEY','test-only')
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    monkeypatch.setattr(assistant,'now',lambda:'2026-11-02T15:00:00+08:00')


def ask(system,message,ident=None):
    r=system[0]('POST','/api/v1/assistant/chat',json={'message':message,'conversation_id':ident})
    assert r.status_code==200,r.text
    return r.json()


def test_actual_homework_fields_survive_supplements_question_and_rename(system,monkeypatch):
    with system[1]() as db:
        db.execute(delete(Availability).where(Availability.owner_id=='A'));db.commit()
        before=snapshot(db,db.get(User,'A'))
    plans=iter([
        {'intent':'change','action':'create_task','payload':{'title':'数学作业','deadline':'2026-11-03T09:00:00+08:00'}},
        {'intent':'change','action':'create_task','payload':{'duration_minutes':72,'priority':3}},
        {'intent':'help'},
        {'intent':'change','action':'create_task','payload':{'title':'高数作业'}},
    ])
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'请核对信息，缺项会保留，保存需确认。'}
        return next(plans)
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'明天早上9点交数学作业')
    assert a['proposal'] is None
    b=ask(system,'耗时1.2小时 高',a['conversation_id'])
    assert b['proposal']['can_confirm']
    assert b['proposal']['payload']['data']['duration_minutes']==75
    assert b['proposal']['payload']['data']['priority']==3
    assert any('72分钟' in note and '75分钟' in note for note in b['proposal']['preview']['diagnostics'])
    c=ask(system,'顺便问一下，怎么安排时间更合适？',a['conversation_id'])
    assert c['proposal'] is None
    d=ask(system,'名字叫高数作业',a['conversation_id'])
    data=d['proposal']['payload']['data']
    assert data['title']=='高数作业' and data['deadline']=='2026-11-03T09:00:00+08:00'
    assert data['duration_minutes']==75 and data['priority']==3
    with system[1]() as db:assert snapshot(db,db.get(User,'A'))==before
    p=d['proposal'];key='memory-confirm'
    saved=system[0]('POST',f'/api/v1/assistant/proposals/{p["id"]}/confirm',key=key,json={'confirmed':True})
    assert saved.status_code==200,saved.text
    with system[1]() as db:
        thread=db.get(AssistantThread,a['conversation_id'])
        assert thread.context['last_applied']['title']=='高数作业'
        assert 'pending_action' not in thread.context
        assert thread.messages[-1]['event']=='applied'
        count=len(thread.messages)
        task=db.scalar(select(Task).where(Task.owner_id=='A',Task.title=='高数作业'))
        assert task.duration_minutes==75 and task.priority==3
    assert system[0]('POST',f'/api/v1/assistant/proposals/{p["id"]}/confirm',key=key,json={'confirmed':True}).json()==saved.json()
    with system[1]() as db:assert len(db.get(AssistantThread,a['conversation_id']).messages)==count
    async def saved_model(_system,content):
        data=json.loads(content)
        if 'trusted_facts' in data:
            assert data['execution_result']['applied'] and data['execution_result']['title']=='高数作业'
            assert any(m.get('event')=='applied' for m in data['history'])
            return {'answer':'高数作业已保存为待办，预计72分钟、优先级高，排程预留75分钟。'}
        assert data['previous_context']['last_applied']['applied']
        assert 'pending_action' not in data['previous_context']
        return {'intent':'agenda'}
    monkeypatch.setattr(assistant.ai,'call_model',saved_model)
    state=ask(system,'刚才保存好了吗？',a['conversation_id'])
    assert state['answer_source']=='model' and '已保存' in state['answer']


def test_more_than_four_turns_and_memory_reach_both_model_stages(system,monkeypatch):
    seen=[]
    async def model(_system,content):
        data=json.loads(content);seen.append(data)
        if 'trusted_facts' in data:return {'answer':'记得你说晚上八点之后更方便，具体安排仍以日历为准。'}
        return {'intent':'help','memory':'用户偏好晚上八点后学习。'} if not data['previous_context'] else {'intent':'help'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    ident=ask(system,'我更喜欢晚上八点之后学习')['conversation_id']
    for i in range(14):ask(system,f'再聊第{i}个问题',ident)
    parses=[x for x in seen if 'recent_history' in x]
    responses=[x for x in seen if 'trusted_facts' in x]
    assert len(parses[-1]['recent_history'])>24
    assert parses[-1]['recent_history'][0]['content']=='我更喜欢晚上八点之后学习'
    assert '八点' in parses[-1]['previous_context']['memory']
    assert '八点' in responses[-1]['understanding']['memory']
    assert len(responses[-1]['history'])>24
    with system[1]() as db:
        thread=db.get(AssistantThread,ident)
        assert len(thread.messages)==30 and thread.messages[0]['created_at']
    assert system[0]('GET','/api/v1/assistant/conversations/latest',member='B').json()['messages']==[]


@pytest.mark.parametrize('pending',['replace','cancel'])
def test_new_or_cancelled_request_does_not_inherit_old_deadline(system,monkeypatch,pending):
    plans=iter([
        {'intent':'change','action':'create_task','payload':{'title':'旧作业','deadline':'2026-11-03T09:00:00+08:00'}},
        {'intent':'change','action':'create_task' if pending=='replace' else 'none','pending':pending,'payload':{'title':'另一项任务','duration_minutes':60} if pending=='replace' else {}},
    ])
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'已按本轮要求处理待确认事项。'}
        return next(plans)
    monkeypatch.setattr(assistant.ai,'call_model',model)
    a=ask(system,'明天早上9点交旧作业')
    b=ask(system,'取消刚才的' if pending=='cancel' else '另加一个任务，耗时1小时',a['conversation_id'])
    assert b['proposal'] is None
    with system[1]() as db:
        context=db.get(AssistantThread,a['conversation_id']).context
        if pending=='cancel':assert 'pending_action' not in context
        else:assert 'deadline' not in context['pending_payload']


def test_event_can_refer_to_earlier_user_time_evidence():
    u=assistant.Understanding(intent='change',action='create_event',date='2026-11-08',
        payload={'title':'慢跑','start':'2026-11-08T18:15:00+08:00','end':'2026-11-08T18:45:00+08:00'},
        evidence={'date':'周日','start':'傍晚六点一刻','end':'半小时','title':'慢跑'})
    result=assistant.grounded_event(u,'就按之前说的来',{},[{'role':'user','content':'周日傍晚六点一刻慢跑半小时'}])
    assert result.payload['start']=='2026-11-08T18:15:00+08:00'
    assert result.payload['end']=='2026-11-08T18:45:00+08:00'


def test_history_is_bounded_without_discarding_newest_message():
    history=[{'role':'user','content':str(i)+'x'*1200} for i in range(140)]
    sent=assistant.conversation_history(history)
    assert sent[-1]==history[-1] and len(sent)<120
    assert sum(len(json.dumps(m,ensure_ascii=False)) for m in sent)<=64000


def test_only_missing_task_fields_are_requested(system,monkeypatch):
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):raise ValueError('fallback for deterministic question')
        return {'intent':'change','action':'create_task','payload':{'title':'数学作业','deadline':'2026-11-03T09:00:00+08:00'}}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    r=ask(system,'明天早上9点交数学作业')
    assert '预计耗时' in r['answer'] and '优先级' not in r['answer'] and '补充任务名称' not in r['answer']


def test_model_extras_nulls_and_action_as_intent_do_not_reject_valid_task(system,monkeypatch):
    with system[1]() as db:db.execute(delete(Availability).where(Availability.owner_id=='A'));db.commit()
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'请核对任务卡片。'}
        return {'intent':'create_task','action':'create_task','period':None,'memory':{'preference':'晚上学习'},
                'explanation':'extra model commentary','payload':{'title':'高数作业','deadline':'2026-11-03T09:00:00+08:00','duration_minutes':72,'priority':3}}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    r=ask(system,'建高数作业，明早9点交，1.2小时，高优先级')
    assert r['proposal']['can_confirm'] and r['proposal']['payload']['data']['duration_minutes']==75


def test_cancelled_draft_cannot_still_be_confirmed(system,monkeypatch):
    plans=iter([
        {'intent':'change','action':'create_event','date':'2026-11-08','payload':{'title':'备忘','start':'2026-11-08T18:00:00+08:00','end':'2026-11-08T19:00:00+08:00'}},
        {'intent':'help','pending':'cancel'},
    ])
    async def model(_system,content):
        if 'trusted_facts' in json.loads(content):return {'answer':'请核对当前操作。'}
        return next(plans)
    monkeypatch.setattr(assistant.ai,'call_model',model)
    r=ask(system,'添加周日18点到19点的备忘日程')
    assert r['proposal']['can_confirm']
    ask(system,'取消刚才的',r['conversation_id'])
    p=r['proposal']
    assert system[0]('POST',f'/api/v1/assistant/proposals/{p["id"]}/confirm',json={'confirmed':True}).status_code==404
