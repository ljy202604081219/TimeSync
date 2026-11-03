import pytest
from sqlalchemy import select,delete,func
from app import assistant
from app.models import Task,User,Availability,PlanVersion,ScheduledTask,BusyInterval,Meeting,MeetingInvitation
from app.plans import snapshot,valid_current

@pytest.fixture(autouse=True)
def rules(monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','mock');monkeypatch.setenv('AI_API_KEY','')
    monkeypatch.setattr(assistant,'now',lambda:'2026-11-02T09:00:00+08:00')

@pytest.fixture
def unplanned(system):
    with system[1]() as db:
        plans=select(PlanVersion.id).where(PlanVersion.owner_id=='A')
        db.execute(delete(ScheduledTask).where(ScheduledTask.plan_id.in_(plans)))
        db.execute(delete(PlanVersion).where(PlanVersion.owner_id=='A'))
        db.execute(delete(Task).where(Task.owner_id=='A'))
        db.execute(delete(Availability).where(Availability.owner_id=='A'));db.commit()
    return system

def ask(system,message,ident=None):
    r=system[0]('POST','/api/v1/assistant/chat',json={'message':message,'conversation_id':ident})
    assert r.status_code==200,r.text
    return r.json()

def confirm(system,p,**kwargs):
    return system[0]('POST',f'/api/v1/assistant/proposals/{p["id"]}/confirm',json={'confirmed':True},**kwargs)

def test_personal_event_without_tasks_or_availability_is_previewed_then_saved(unplanned):
    call,factory,_=unplanned
    with factory() as db:before=snapshot(db,db.get(User,'A'))
    r=ask(unplanned,'帮我添加明天14点到16点的自习日程')
    p=r['proposal'];assert p['action']=='create_event' and p['can_confirm'] and p['preview']['save_only']
    assert p['payload']['title']=='自习' and p['payload']['start']=='2026-11-03T14:00:00+08:00'
    with factory() as db:assert snapshot(db,db.get(User,'A'))==before
    saved=confirm(unplanned,p,key='event-once');assert saved.status_code==200,saved.text
    assert saved.json()['event']['title']=='自习' and saved.json()['plan'] is None
    assert confirm(unplanned,p,key='event-once').json()==saved.json()
    with factory() as db:assert db.scalar(select(func.count()).select_from(BusyInterval).where(BusyInterval.owner_id=='A',BusyInterval.title=='自习'))==1
    agenda=call('GET','/api/v1/agenda?start=2026-11-03T12:00:00%2B08:00&end=2026-11-03T18:00:00%2B08:00').json()
    assert any(e['title']=='自习' and e['kind']=='unavailable' for e in agenda['events'])

def test_incomplete_event_keeps_context_for_chinese_clock_followup(unplanned):
    first=ask(unplanned,'帮我添加明天的自习日程')
    assert first['proposal'] is None and first['conversation_id'] and '开始' in first['answer']
    second=ask(unplanned,'上午九点到十点',first['conversation_id'])
    assert second['proposal']['payload']['title']=='自习'
    assert second['proposal']['payload']['start']=='2026-11-03T09:00:00+08:00'
    assert second['proposal']['payload']['end']=='2026-11-03T10:00:00+08:00'
    assert second['proposal']['can_confirm']

def test_missing_title_can_be_completed_in_next_turn(unplanned):
    first=ask(unplanned,'帮我添加明天14点到16点的日程')
    assert first['proposal'] is None
    second=ask(unplanned,'自习',first['conversation_id'])
    assert second['proposal']['payload']['title']=='自习' and second['proposal']['can_confirm']

def test_start_plus_explicit_duration_completes_without_inventing_end(unplanned):
    first=ask(unplanned,'添加明天14点的自习日程')
    assert first['proposal'] is None
    second=ask(unplanned,'持续两小时',first['conversation_id'])
    assert second['proposal']['payload']['end']=='2026-11-03T16:00:00+08:00'

def test_existing_course_conflict_is_not_silently_saved(unplanned):
    r=ask(unplanned,'添加明天10点到11点的自习日程')
    assert not r['proposal']['can_confirm'] and r['proposal']['preview']['event_conflicts']
    assert confirm(unplanned,r['proposal']).status_code==409

def test_event_conflicting_with_task_uses_existing_repair_solver(system):
    r=ask(system,'添加周三14:00到16:00的《自习》日程')
    assert r['proposal']['can_confirm'] and not r['proposal']['preview']['save_only']
    assert r['proposal']['preview']['changes']
    res=confirm(system,r['proposal']);assert res.status_code==200,res.text
    assert res.json()['plan']['id']
    with system[1]() as db:assert valid_current(db,db.get(User,'A'))

def test_confirmed_meeting_is_not_overridden(unplanned):
    with unplanned[1]() as db:
        m=Meeting(organizer_id='A',title='已有会议',start='2026-11-03T14:00:00+08:00',end='2026-11-03T15:00:00+08:00',status='confirmed');db.add(m);db.flush()
        db.add(MeetingInvitation(meeting_id=m.id,member_id='A',status='accepted'));db.commit()
    r=ask(unplanned,'添加明天14点到15点的自习日程')
    assert not r['proposal']['can_confirm']
    assert any('会议' in e['reason'] for e in r['proposal']['preview']['event_conflicts'])

def test_new_task_can_be_saved_before_availability_is_configured(unplanned):
    r=ask(unplanned,'新增任务《高数复习》，截止2026-11-06 18:00，耗时2小时')
    assert r['proposal']['can_confirm'] and r['proposal']['preview']['save_only']
    res=confirm(unplanned,r['proposal']);assert res.status_code==200,res.text
    assert res.json()['task']['title']=='高数复习' and res.json()['plan'] is None

def test_real_provider_event_action_contract_without_paid_request(unplanned,monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only')
    async def model(*args):return {'intent':'change','date':'2026-11-03T00:00:00+08:00','action':'create_event','payload':{'title':'自习','start':'2026-11-03T14:00:00+08:00','end':'2026-11-03T16:00:00+08:00','kind':'unavailable'}}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    r=ask(unplanned,'帮我安排明天14:00到16:00的自习')
    assert r['mode']=='live' and r['proposal']['can_confirm']

def test_event_suggestion_cannot_be_confirmed_by_another_identity(unplanned):
    r=ask(unplanned,'添加明天14点到16点的自习日程')
    assert confirm(unplanned,r['proposal'],member='B').status_code==404


def test_actual_course_statement_asks_end_and_keeps_evening_for_reply(unplanned):
    first=ask(unplanned,'今天晚上上实验课 八点\n')
    assert first['proposal'] is None and '20:00' in first['answer'] and '结束' in first['answer']
    assert '未找到任务' not in first['answer'] and '22:00' not in first['answer']
    second=ask(unplanned,'九点半',first['conversation_id'])
    p=second['proposal'];assert p['can_confirm']
    assert p['payload']['title']=='实验课' and p['payload']['kind']=='course'
    assert p['payload']['start']=='2026-11-02T20:00:00+08:00'
    assert p['payload']['end']=='2026-11-02T21:30:00+08:00'


def test_wrong_model_intent_and_invented_duration_cannot_override_user(unplanned,monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only')
    async def bad_model(*args):
        return {'intent':'agenda','task_query':'实验课','duration_minutes':120,'clarification':'已创建，默认22:00结束','payload':{'title':'实验课','start':'2026-11-02T20:00:00+08:00','end':'2026-11-02T22:00:00+08:00'}}
    monkeypatch.setattr(assistant.ai,'call_model',bad_model)
    first=ask(unplanned,'今天晚上上实验课 八点')
    assert first['proposal'] is None and '22:00' not in first['answer'] and '已创建' not in first['answer']
    second=ask(unplanned,'九点半',first['conversation_id'])
    assert second['proposal']['payload']['end'].endswith('T21:30:00+08:00')
    with unplanned[1]() as db:
        assert db.scalar(select(func.count()).select_from(BusyInterval).where(BusyInterval.title=='实验课'))==0


def test_model_created_event_cannot_invent_end_without_literal_evidence(unplanned,monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only')
    async def guessed(*args):return {'intent':'change','action':'create_event','clarification':'已创建','payload':{'title':'跑步','start':'2026-11-02T20:00:00+08:00','end':'2026-11-02T22:00:00+08:00'}}
    monkeypatch.setattr(assistant.ai,'call_model',guessed)
    result=ask(unplanned,'今晚八点跑步')
    assert result['proposal'] is None and '20:00' in result['answer'] and '22:00' not in result['answer']


def test_course_without_clock_does_not_invent_evening_start(unplanned):
    r=ask(unplanned,'周五晚上上实践课')
    assert r['proposal'] is None and '开始' in r['answer'] and '20:00' not in r['answer']


def test_query_is_not_misinterpreted_as_a_calendar_write(unplanned):
    r=ask(unplanned,'今天晚上八点有什么安排？')
    assert r['proposal'] is None and 'pending_action' not in unplanned[0]('GET','/api/v1/assistant/conversations/latest').text


def test_old_failed_conversation_can_continue_with_end_time(unplanned):
    from app.models import AssistantThread
    import uuid
    ident=str(uuid.uuid4())
    with unplanned[1]() as db:
        db.add(AssistantThread(id=ident,owner_id='A',revision=1,updated_at=assistant.now(),messages=[{'role':'user','content':'今天晚上上实验课 八点'},{'role':'assistant','content':'未找到任务“实验课”'}],context={'date':'2026-11-02T00:00:00+08:00','period':'evening','task_query':'实验课','clarification':'已创建，默认22:00结束'}));db.commit()
    r=ask(unplanned,'九点半',ident)
    assert r['proposal']['payload']['title']=='实验课'
    assert r['proposal']['payload']['start'].endswith('T20:00:00+08:00')
    assert r['proposal']['payload']['end'].endswith('T21:30:00+08:00')


def test_invalid_model_intent_does_not_block_literal_course_capture(unplanned,monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only')
    async def wrong_schema(*args):return {'intent':'record_schedule','title':'实验课','end_time':'22:00'}
    monkeypatch.setattr(assistant.ai,'call_model',wrong_schema)
    first=ask(unplanned,'今天晚上上实验课 八点')
    assert first['proposal'] is None and '20:00' in first['answer'] and '22:00' not in first['answer']
    second=ask(unplanned,'九点半',first['conversation_id'])
    assert second['proposal']['payload']['end'].endswith('T21:30:00+08:00')
