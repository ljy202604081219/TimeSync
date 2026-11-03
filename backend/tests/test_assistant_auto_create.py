"""Default automatic additions: one model call, atomic writes and safe retries."""
import json
from sqlalchemy import select,func,delete
import pytest
from app import assistant
from app.models import BusyInterval,Task,AssistantThread,AssistantProposal,Availability,Meeting,MeetingInvitation


@pytest.fixture(autouse=True)
def automatic_default(monkeypatch):
    monkeypatch.delenv('ASSISTANT_AUTO_CREATE',raising=False)
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only')
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    monkeypatch.setattr(assistant,'now',lambda:'2026-11-02T09:00:00+08:00')


def event():
    return {'action':'create_event','date':'2026-11-08','payload':{'title':'高数复习','start':'2026-11-08T18:00:00+08:00','end':'2026-11-08T19:00:00+08:00','kind':'unavailable'}}


def fake_model(monkeypatch,result):
    calls=[]
    async def model(_system,content):
        data=json.loads(content);calls.append(data)
        assert 'trusted_facts' not in data,'Automatic additions must not call a prose model'
        return result() if callable(result) else result
    monkeypatch.setattr(assistant.ai,'call_model',model)
    return calls


def ask(system,text='2026年11月8日18点到19点添加“高数复习”',request_id='new-event',member='A',conversation=None):
    return system[0]('POST','/api/v1/assistant/chat',member=member,json={'message':text,'conversation_id':conversation,'request_id':request_id})


def count(db,model,owner='A'):
    return db.scalar(select(func.count()).select_from(model).where(model.owner_id==owner))


def test_default_direct_add_is_committed_once_with_receipt_and_memory(system,monkeypatch):
    calls=fake_model(monkeypatch,{**event(),'memory':'用户偏好晚饭前复习。'})
    with system[1]() as db:before=count(db,BusyInterval)
    r=ask(system);assert r.status_code==200,r.text
    d=r.json();assert d['applied'] and d['proposal'] is None and d['answer_source']=='receipt'
    assert '已添加' in d['answer'] and '确认' not in d['answer'] and len(calls)==1
    assert d['applied_result']['title']=='高数复习' and d['applied_result']['id']
    assert any(e['title']=='高数复习' for e in d['facts']['events'])
    with system[1]() as db:
        assert count(db,BusyInterval)==before+1
        assert count(db,AssistantProposal)==0
        thread=db.get(AssistantThread,d['conversation_id'])
        assert thread.context['last_applied']['applied'] and 'pending_action' not in thread.context
        assert thread.context['memory']=='用户偏好晚饭前复习。'
        assert thread.messages[-1]['event']=='applied' and thread.messages[-1]['applied_result']
    repeated=ask(system)
    assert repeated.status_code==200 and repeated.json()==d and len(calls)==1
    with system[1]() as db:
        assert count(db,BusyInterval)==before+1
        assert len(db.get(AssistantThread,d['conversation_id']).messages)==2


def test_same_request_id_for_different_body_is_rejected_without_extra_model_call(system,monkeypatch):
    calls=fake_model(monkeypatch,event())
    assert ask(system).status_code==200
    r=ask(system,text='换成另外一个请求')
    assert r.status_code==409 and len(calls)==1


def test_legacy_header_idempotency_also_prevents_duplicate_additions(system,monkeypatch):
    calls=fake_model(monkeypatch,event());body={'message':'2026年11月8日18点到19点添加“高数复习”'}
    a=system[0]('POST','/api/v1/assistant/chat',key='same-header',json=body)
    b=system[0]('POST','/api/v1/assistant/chat',key='same-header',json=body)
    assert a.status_code==b.status_code==200 and a.json()==b.json() and len(calls)==1


def test_missing_end_is_asked_once_then_supplement_is_saved_directly(system,monkeypatch):
    answers=iter([{'action':'create_event','date':'2026-11-03','payload':{'title':'数学课','start':'2026-11-03T20:00:00+08:00'}},
                  {'action':'create_event','pending':'replace','payload':{'end':'2026-11-03T21:00:00+08:00'}}])
    calls=fake_model(monkeypatch,lambda:next(answers))
    with system[1]() as db:before=count(db,BusyInterval)
    a=ask(system,'明天晚上八点上数学课','incomplete').json()
    assert not a['applied'] and '结束' in a['answer']
    with system[1]() as db:assert count(db,BusyInterval)==before
    b=ask(system,'九点结束','supplement',conversation=a['conversation_id']).json()
    assert b['applied'] and b['applied_result']['end']=='2026-11-03T21:00:00+08:00' and len(calls)==2


def test_fixed_course_conflict_is_reported_without_writing(system,monkeypatch):
    fake_model(monkeypatch,{'action':'create_event','date':'2026-11-02','payload':{'title':'复习','start':'2026-11-02T08:00:00+08:00','end':'2026-11-02T09:00:00+08:00'}})
    with system[1]() as db:before=count(db,BusyInterval)
    r=ask(system,'今天八点到九点添加复习').json()
    assert not r['applied'] and '暂未添加' in r['answer'] and '高等数学' in r['answer']
    with system[1]() as db:assert count(db,BusyInterval)==before


def test_confirmed_meeting_cannot_be_changed_by_auto_add(system,monkeypatch):
    fake_model(monkeypatch,event())
    with system[1]() as db:
        meeting=Meeting(organizer_id='A',title='已确认组会',start='2026-11-08T18:00:00+08:00',end='2026-11-08T19:00:00+08:00',status='confirmed')
        db.add(meeting);db.flush();ident=meeting.id
        db.add(MeetingInvitation(meeting_id=ident,member_id='A',status='accepted'));db.commit();before=count(db,BusyInterval)
    r=ask(system).json();assert not r['applied'] and '组会' in r['answer']
    with system[1]() as db:
        assert count(db,BusyInterval)==before and db.get(Meeting,ident).start=='2026-11-08T18:00:00+08:00'


@pytest.mark.parametrize('available',[True,False])
def test_task_auto_add_reuses_solver_or_preserves_unscheduled_todo(system,monkeypatch,available):
    result={'action':'create_task','date':'2026-11-02','payload':{'title':'新实验报告','deadline':'2026-11-06T18:00:00+08:00','duration_minutes':60}}
    fake_model(monkeypatch,result)
    with system[1]() as db:
        if not available:db.execute(delete(Availability).where(Availability.owner_id=='A'));db.commit()
        before=count(db,Task)
    response=ask(system,'添加任务“新实验报告”，截止2026年11月6日18点，耗时1小时').json()
    assert response['applied'] and response['applied_result']['title']=='新实验报告'
    assert response['applied_result']['requires_scheduling'] is (not available)
    assert bool(response['applied_result']['plan_id']) is available
    with system[1]() as db:assert count(db,Task)==before+1


def test_suggestion_does_not_add_event_and_other_owner_isolated(system,monkeypatch):
    calls=[]
    async def model(_system,content):
        d=json.loads(content);calls.append(d)
        if 'trusted_facts' in d:return {'answer':'可以把慢跑作为建议，目前没有创建。'}
        return {'intent':'advice','date':'2026-11-03','draft_answer':'可以把慢跑作为建议，目前没有创建。'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    with system[1]() as db:before=count(db,BusyInterval)
    r=ask(system,'明天晚上跑步怎么样？').json()
    assert not r['applied']
    with system[1]() as db:assert count(db,BusyInterval)==before
    fake_model(monkeypatch,event());a=ask(system,request_id='same-owner-key').json();b=ask(system,request_id='same-owner-key',member='B').json()
    assert a['applied'] and b['applied'] and a['conversation_id']!=b['conversation_id']
    assert system[0]('GET','/api/v1/assistant/conversations/latest',member='B').json()['conversation_id']==b['conversation_id']


def test_failed_final_validation_rolls_back_automatic_add(system,monkeypatch):
    fake_model(monkeypatch,event())
    with system[1]() as db:before=count(db,BusyInterval)
    from fastapi import HTTPException
    def changed(*_):raise HTTPException(409,'日程已变化，没有保存')
    monkeypatch.setattr(assistant,'apply_proposal',changed)
    r=ask(system);assert r.status_code==409
    with system[1]() as db:
        assert count(db,BusyInterval)==before and count(db,AssistantThread)==0 and count(db,AssistantProposal)==0


def test_fully_explicit_addition_saves_without_model_but_does_not_claim_ai(system,monkeypatch):
    async def forbidden(*_):raise AssertionError('Clear direct addition must not wait for a model')
    monkeypatch.setattr(assistant.ai,'call_model',forbidden)
    text='添加明天晚上八点到九点的“高数复习”'
    result=ask(system,text,'direct').json()
    assert result['applied'] and result['mode']=='direct' and '未调用模型' in result['label']
    assert result['applied_result']['start']=='2026-11-03T20:00:00+08:00'
    assert result['applied_result']['end']=='2026-11-03T21:00:00+08:00'
    assert ask(system,text,'direct').json()==result


@pytest.mark.parametrize('message',[
    '如果添加明天晚上八点到九点的“高数复习”会冲突吗？',
    '帮我想想明天晚上八点到九点的“高数复习”',
    '不要添加明天晚上八点到九点的“高数复习”',
    '添加明天晚上的“高数复习”',
    '添加明天八点到九点的“高数复习”',
    '添加任务“高数复习”，截止2026-11-06 18:00，耗时1小时',
])
def test_uncertain_or_non_event_text_stays_with_mimo(message):
    assert assistant.direct_event(message) is None
