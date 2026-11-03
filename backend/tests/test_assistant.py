import asyncio
import pytest
import httpx
from sqlalchemy import select, func
from app import assistant
from app.models import Task, User, PlanVersion, BusyInterval, AssistantProposal
from app.plans import snapshot, valid_current


@pytest.fixture(autouse=True)
def deterministic_assistant(monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','mock')
    monkeypatch.setenv('AI_API_KEY','')
    monkeypatch.setattr(assistant,'now',lambda:'2026-11-02T09:00:00+08:00')


def ask(call,message,conversation_id=None,member='A'):
    response=call('POST','/api/v1/assistant/chat',member=member,json={'message':message,'conversation_id':conversation_id})
    assert response.status_code==200,response.text
    return response.json()


def test_today_agenda_real_course_and_no_business_write(system):
    call,factory,_=system
    with factory() as db: before=snapshot(db,db.get(User,'A'))
    r=ask(call,'今天有什么安排？')
    assert r['mode']=='mock' and '非真实' in r['label'] and '高等数学' in r['answer']
    assert r['facts']['start']=='2026-11-02T00:00:00+08:00'
    with factory() as db: assert snapshot(db,db.get(User,'A'))==before


def test_tomorrow_free_and_three_turn_references(system):
    call,_,_=system
    a=ask(call,'明天什么时候有空？');ident=a['conversation_id']
    b=ask(call,'那我可以安排两个小时吗？',ident)
    c=ask(call,'如果安排到晚上呢？',ident)
    assert b['facts']['start'].startswith('2026-11-03')
    assert '120 分钟' in b['answer'] and '120 分钟' in c['answer']
    assert c['facts']['start']=='2026-11-03T18:00:00+08:00'
    assert all(x['minutes']>=120 for x in c['facts']['free'])


def test_upcoming_deadlines(system):
    call,_,_=system
    r=ask(call,'本周有哪些即将到期的任务？')
    assert '机器学习' in r['answer'] and '阅读与整理文献' in r['answer']


@pytest.mark.parametrize('message',['2026-02-30有什么安排','2026-13-02什么时候有空'])
def test_invalid_date_no_hallucination(system,message):
    assert '无效' in ask(system[0],message)['answer']


def test_nonexistent_task(system):
    r=ask(system[0],'为什么安排《不存在的任务》？')
    assert '未找到任务' in r['answer'] and r['proposal'] is None


def test_conflict_detection_uses_current_events(system):
    call,_,_=system
    call('POST','/api/busy',json={'title':'撞课测试','kind':'course','start':'2026-11-04T14:00:00+08:00','end':'2026-11-04T15:00:00+08:00'})
    r=ask(call,'周三有冲突吗？')
    assert '撞课测试' in r['answer'] and '实验报告' in r['answer'] and r['facts']['plan']['repair_needed']


def test_explanation_and_risk_do_not_invent_causality(system):
    r=ask(system[0],'为什么把机器学习 · 实验报告安排在这个时间？')
    assert '减少改动任务数' in r['answer'] and '不声称' in r['answer']
    assert '风险提示' in ask(system[0],'哪些任务可能无法按时完成？')['answer']


def test_no_availability_is_not_free(system):
    r=ask(system[0],'2026-12-01下午有空吗？')
    assert '不能把' in r['answer'] and not r['facts']['free']


def test_change_requires_preview_and_explicit_confirmation(system):
    call,factory,_=system
    with factory() as db:before=snapshot(db,db.get(User,'A'))
    r=ask(call,'周三14:00-16:00临时增加实验，请修复计划')
    assert r['proposal']['can_confirm'] and r['proposal']['preview']['changes']
    with factory() as db:assert snapshot(db,db.get(User,'A'))==before
    pid=r['proposal']['id']
    assert call('POST',f'/api/v1/assistant/proposals/{pid}/confirm',json={'confirmed':False}).status_code==422
    accepted=call('POST',f'/api/v1/assistant/proposals/{pid}/confirm',key='once',json={'confirmed':True})
    assert accepted.status_code==200,accepted.text
    assert call('POST',f'/api/v1/assistant/proposals/{pid}/confirm',key='once',json={'confirmed':True}).json()==accepted.json()
    with factory() as db:
        assert snapshot(db,db.get(User,'A'))!=before and valid_current(db,db.get(User,'A'))
        assert db.scalar(select(func.count()).select_from(BusyInterval).where(BusyInterval.title=='助手录入的临时事件'))==1


def test_modify_ddl_resolves_task_and_regenerates_valid_plan(system):
    call,factory,_=system
    r=ask(call,'修改《机器学习 · 实验报告》的DDL为2026-11-06 18:00')
    assert r['proposal']['action']=='update_task' and r['proposal']['can_confirm']
    pid=r['proposal']['id']
    with factory() as db:assert db.scalar(select(Task).where(Task.owner_id=='A',Task.title=='机器学习 · 实验报告')).deadline.startswith('2026-11-05')
    res=call('POST',f'/api/v1/assistant/proposals/{pid}/confirm',json={'confirmed':True})
    assert res.status_code==200,res.text
    with factory() as db:
        assert db.scalar(select(Task).where(Task.owner_id=='A',Task.title=='机器学习 · 实验报告')).deadline.startswith('2026-11-06')
        assert valid_current(db,db.get(User,'A'))


def test_add_task_no_write_before_confirmation(system):
    call,factory,_=system
    r=ask(call,'新增任务《高数复习》，截止2026-11-06 18:00，耗时2小时')
    assert r['proposal']['action']=='create_task'
    with factory() as db:assert db.scalar(select(Task).where(Task.title=='高数复习')) is None
    result=call('POST',f'/api/v1/assistant/proposals/{r["proposal"]["id"]}/confirm',json={'confirmed':True})
    assert result.status_code==200,result.text
    with factory() as db:assert valid_current(db,db.get(User,'A'))


def test_infeasible_update_cannot_commit(system):
    call,factory,_=system
    r=ask(call,'修改《机器学习 · 实验报告》的DDL为2026-11-02 08:15')
    assert not r['proposal']['can_confirm']
    res=call('POST',f'/api/v1/assistant/proposals/{r["proposal"]["id"]}/confirm',json={'confirmed':True})
    assert res.status_code==409


def test_stale_preview_rejected(system):
    call,_,_=system
    r=ask(call,'重新排程')
    call('POST','/api/busy',json={'title':'新约束','start':'2026-11-03T14:00:00+08:00','end':'2026-11-03T16:00:00+08:00'})
    assert call('POST',f'/api/v1/assistant/proposals/{r["proposal"]["id"]}/confirm',json={'confirmed':True}).status_code==409


def test_cross_user_history_and_proposal_isolation(system):
    call,_,_=system
    a=ask(call,'重新排程')
    assert call('POST','/api/v1/assistant/chat',member='B',json={'message':'继续','conversation_id':a['conversation_id']}).status_code==404
    assert call('POST',f'/api/v1/assistant/proposals/{a["proposal"]["id"]}/confirm',member='B',json={'confirmed':True}).status_code==404
    assert call('GET','/api/v1/assistant/conversations/latest',member='B').json()['messages']==[]
    assert call('DELETE',f'/api/v1/assistant/conversations/{a["conversation_id"]}',member='B').status_code==404


def test_clear_and_unsupported_destructive_request(system):
    call,factory,_=system
    a=ask(call,'删除所有任务')
    assert a['proposal'] is None
    assert call('DELETE',f'/api/v1/assistant/conversations/{a["conversation_id"]}').status_code==200
    assert not call('GET','/api/v1/assistant/conversations/latest').json()['messages']
    with factory() as db:assert len(list(db.scalars(select(Task).where(Task.owner_id=='A'))))==3


@pytest.mark.parametrize('error,status',[(asyncio.TimeoutError(),504),(httpx.ConnectError('test secret must not leak'),502)])
def test_model_failure_no_paid_calls_or_secret_leaks(system,monkeypatch,error,status):
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only-placeholder')
    async def fail(*args):raise error
    monkeypatch.setattr(assistant.ai,'call_model',fail)
    r=system[0]('POST','/api/v1/assistant/chat',json={'message':'今天有什么安排？'})
    assert r.status_code==status and 'secret' not in r.text and '没有修改' in r.text


def test_real_provider_contract_uses_only_current_owner_data(system,monkeypatch):
    call,_,_=system;seen=[]
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only-placeholder')
    async def model(system,content):
        import json
        seen.append(json.loads(content));return {'intent':'agenda','date':'2026-11-02T00:00:00+08:00'}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    r=ask(call,'今天有什么安排？')
    assert r['mode']=='live' and len(seen[0]['tasks'])==3
    assert len(set(t['id'] for t in seen[0]['tasks']))==3
    assert 'token' not in str(seen)


def test_anonymous_and_device_credentials_cannot_use_assistant(system,monkeypatch):
    _,_,client=system
    assert client.post('/api/v1/assistant/chat',json={'message':'今天有什么安排'}).status_code==401
    from app import devices
    with system[1]() as db:issued=devices.issue_device(db,'A','test',30,created_by='test')
    token=issued['token']
    assert client.post('/api/v1/assistant/chat',headers={'Authorization':'Bearer '+token},json={'message':'今天有什么安排'}).status_code==403


def test_move_task_is_a_solver_constraint_and_confirmed_version(system):
    call,factory,_=system
    r=ask(call,'把《机器学习 · 实验报告》移到明天18:00')
    assert r['proposal']['action']=='move_task' and r['proposal']['can_confirm']
    target=r['proposal']['payload']['task_id']
    assert next(s for s in r['proposal']['preview']['schedule'] if s['task_id']==target)['start']=='2026-11-03T18:00:00+08:00'
    assert any('按你指定' in c['reason'] for c in r['proposal']['preview']['changes'] if c['task_id']==target)
    response=call('POST',f'/api/v1/assistant/proposals/{r["proposal"]["id"]}/confirm',json={'confirmed':True})
    assert response.status_code==200,response.text
    with factory() as db:assert valid_current(db,db.get(User,'A'))


def test_move_into_course_rejected_without_breaking_old_plan(system):
    call,factory,_=system
    with factory() as db:before=snapshot(db,db.get(User,'A'))
    r=ask(call,'把《机器学习 · 实验报告》移到周三08:00')
    assert not r['proposal']['can_confirm']
    assert call('POST',f'/api/v1/assistant/proposals/{r["proposal"]["id"]}/confirm',json={'confirmed':True}).status_code==409
    with factory() as db:assert snapshot(db,db.get(User,'A'))==before


def test_weekday_and_week_evening_queries_have_correct_boundaries(system):
    call,_,_=system
    a=ask(call,'下周三有什么安排')
    assert a['facts']['start'].startswith('2026-11-11')
    b=ask(call,'本周晚上什么时候有空')
    from app.timeutil import dt
    assert all(dt(f['start']).hour>=18 and dt(f['end']).hour<=22 and dt(f['start']).date()==dt(f['end']).date() for f in b['facts']['free'])


def test_expired_proposal_is_rejected(system):
    call,factory,_=system
    r=ask(call,'重新排程')
    with factory() as db:
        db.get(AssistantProposal,r['proposal']['id']).expires_at='2020-01-01T00:00:00+08:00';db.commit()
    assert call('POST',f'/api/v1/assistant/proposals/{r["proposal"]["id"]}/confirm',json={'confirmed':True}).status_code==409


def test_new_plan_alone_invalidates_preview_even_when_constraints_unchanged(system):
    call,_,_=system
    r=ask(call,'重新排程')
    assert call('POST','/api/plans').status_code==200
    response=call('POST',f'/api/v1/assistant/proposals/{r["proposal"]["id"]}/confirm',json={'confirmed':True})
    assert response.status_code==409 and '版本' in response.text


def test_project_managed_service_for_all_members_without_returning_key(system,monkeypatch):
    call,_,_=system
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','project-test-key-do-not-return')
    for member in 'ABCD':
        response=call('GET','/api/v1/assistant/status',member=member)
        data=response.json()
        assert response.status_code==200 and data['configured'] and data['mode']=='live'
        assert data['requires_user_key'] is False and data['managed_by']=='project'
        assert 'project-test-key-do-not-return' not in response.text
        assert call('GET','/api/me',member=member).json()['ai_configuration_allowed'] is False


def test_service_status_detects_forced_mock_even_with_key(system,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','placeholder')
    data=system[0]('GET','/api/v1/assistant/status').json()
    assert data['configured'] and data['mode']=='mock' and '规则演示' in data['label']


def test_only_opted_in_local_maintainer_sees_configuration_entry(system,monkeypatch):
    call,_,_=system
    monkeypatch.setenv('AI_ADMIN_UI','true')
    assert call('GET','/api/me').json()['ai_configuration_allowed']
    assert not call('GET','/api/me',member='B').json()['ai_configuration_allowed']


def test_provider_auth_error_is_actionable_without_leaking_secret(system,monkeypatch):
    monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','placeholder')
    async def fail(*args):
        response=httpx.Response(401,request=httpx.Request('POST','https://example.test'),text='secret response')
        response.raise_for_status()
    monkeypatch.setattr(assistant.ai,'call_model',fail)
    res=system[0]('POST','/api/v1/assistant/chat',json={'message':'今天有什么安排？'})
    assert res.status_code==502 and '鉴权失败' in res.text and 'secret' not in res.text
