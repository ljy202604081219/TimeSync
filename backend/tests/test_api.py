from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select,func
from app.models import Task,User,PlanVersion,Meeting,Availability
from app.plans import valid_current

def event():
    return {'title':'临时实验','start':'2026-11-04T14:00:00+08:00','end':'2026-11-04T16:00:00+08:00'}
def meeting():
    return {**event(),'title':'小组讨论','members':['A','B','C','D']}
def confirms(call,id):
    out=[]
    for member in 'ABCD':
        response=call('POST',f'/api/meetings/{id}/respond',member,json={'response':'accepted','revision':1})
        assert response.status_code==200,response.text
        out.append(response.json())
    return out

def test_auth_and_privacy(system):
    call,_,client=system
    assert client.get('/api/users/A/state').status_code==401
    assert call('GET','/api/users/B/state').status_code==403
    assert call('GET','/api/plans/2').status_code==403
    assert call('GET','/api/users/A/state').json()['plan_valid']

def test_repair_preview_confirm_version_and_idempotence(system):
    call,factory,_=system
    before=call('GET','/api/users/A/state').json()
    preview=call('POST','/api/disruptions/preview',json=event()).json()
    assert preview['status']=='optimal'
    assert len(preview['changes'])==1
    assert call('GET','/api/users/A/state').json()['plan']['id']==before['plan']['id']
    payload={**event(),'expected_plan_id':preview['expected_plan_id'],'expected_snapshot':preview['expected_snapshot']}
    result=call('POST','/api/disruptions',json=payload,key='repair-1')
    assert result.status_code==200,result.text
    assert call('POST','/api/disruptions',json=payload,key='repair-1').json()==result.json()
    after=call('GET','/api/users/A/state').json()
    assert after['plan_valid'] and len(after['versions'])==len(before['versions'])+1
    assert call('GET',f"/api/plans/{before['plan']['id']}").json()['schedule']==before['schedule']

def test_stale_preview_rejected(system):
    call,_,_=system
    p=call('POST','/api/disruptions/preview',json=event()).json()
    call('POST','/api/busy',json={**event(),'title':'新课程'})
    assert call('POST','/api/disruptions',json={**event(),'expected_plan_id':p['expected_plan_id'],'expected_snapshot':p['expected_snapshot']}).status_code==409

def test_infeasible_plan_not_saved_as_current(system):
    call,factory,_=system
    with factory() as db:
        task=db.scalar(select(Task).where(Task.owner_id=='A'))
        task.deadline='2026-11-02T08:15:00+08:00';db.commit()
    result=call('POST','/api/plans').json()
    assert result['status']=='infeasible' and result['schedule']==[]
    state=call('GET','/api/users/A/state').json()
    assert state['plan']['id']!=result['id'] and not state['plan_valid']

def test_meeting_state_and_personal_linkage(system):
    call,factory,_=system
    response=call('POST','/api/meetings',json=meeting(),key='meeting1')
    assert response.status_code==200,response.text
    new=response.json();id=new['id']
    assert call('POST','/api/meetings',json=meeting(),key='meeting1').json()==new
    results=confirms(call,id)
    assert [r['status'] for r in results]==['pending','pending','pending','confirmed']
    assert all(r['changed_count']==1 for r in results[-1]['linkage'])
    with factory() as db:
        assert all(valid_current(db,db.get(User,m)) for m in 'ABCD')
    assert call('PATCH',f'/api/meetings/{id}',member='B',json={'start':event()['start']}).status_code==403
    assert call('PATCH',f'/api/meetings/{id}',json={'start':event()['start']}).status_code==409
    again=call('POST',f'/api/meetings/{id}/respond',json={'response':'accepted','revision':1})
    assert again.json()['status']=='confirmed'
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PlanVersion))==8

def test_decline_and_reinvite(system):
    call,_,_=system
    id=call('POST','/api/meetings',json=meeting()).json()['id']
    answer=call('POST',f'/api/meetings/{id}/respond',member='B',json={'response':'declined','revision':1})
    assert answer.json()['status']=='declined'
    assert call('POST',f'/api/meetings/{id}/respond',json={'response':'accepted','revision':1}).status_code==409

def test_reschedule_requires_all_confirmations(system):
    call,_,_=system
    old=call('POST','/api/meetings',json=meeting()).json()['id'];confirms(call,old)
    payload={**meeting(),'start':'2026-11-04T17:00:00+08:00','end':'2026-11-04T19:00:00+08:00','replaces_id':old}
    assert call('POST','/api/meetings',member='B',json=payload).status_code==403
    new=call('POST','/api/meetings',json=payload).json()['id']
    assert next(m for m in call('GET','/api/meetings').json() if m['id']==old)['status']=='confirmed'
    confirms(call,new)
    assert next(m for m in call('GET','/api/meetings').json() if m['id']==old)['status']=='superseded'

def test_unrepairable_meeting_generates_alternatives(system):
    call,factory,_=system
    with factory() as db:
        user=db.get(User,'A');user.window_start='2026-11-04T14:00:00+08:00';user.window_end='2026-11-04T18:00:00+08:00'
        task=db.scalar(select(Task).where(Task.owner_id=='A'));task.deadline='2026-11-04T16:00:00+08:00';db.commit()
    id=call('POST','/api/meetings',json=meeting()).json()['id']
    final=confirms(call,id)[-1]
    assert final['status']=='needs_reschedule'
    assert any(r['status']=='alternatives' for r in final['linkage'])
    with factory() as db: assert db.scalar(select(func.count()).select_from(PlanVersion))==4

def test_duplicate_concurrent_and_key_conflict(system):
    call,factory,_=system
    data={'title':'新作业','deadline':'2026-11-06T18:00:00+08:00','duration_minutes':60}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:call('POST','/api/tasks',json=data,key='same'),range(2)))
    assert all(r.status_code==200 for r in results)
    assert results[0].json()['id']==results[1].json()['id']
    assert call('POST','/api/tasks',json={**data,'title':'不同作业'},key='same').status_code==409

def test_dependencies_owner_and_validation(system):
    call,_,_=system
    data={'title':'作业','deadline':'2026-11-06T18:00:00+08:00','duration_minutes':60,'dependencies':[4]}
    assert call('POST','/api/tasks',json=data).status_code==422
    assert call('POST','/api/tasks',json={**data,'dependencies':[],'deadline':'2026-11-06'}).status_code==422
    assert call('PUT','/api/tasks/4',json={**data,'dependencies':[]}).status_code==403
    assert call('POST','/api/tasks',json={**data,'dependencies':[],'duration_minutes':61}).status_code==422

def test_shared_coordination_contains_no_private_titles(system):
    call,_,_=system
    response=call('POST','/api/coordination/candidates',json={'start':'2026-11-04T08:00:00+08:00','end':'2026-11-04T20:00:00+08:00','duration_minutes':60})
    assert response.status_code==200 and response.json()['candidates']
    assert 'title' not in str(response.json()['members'])
    assert '机器学习' not in response.text

def test_no_common_free_alternatives(system):
    call,_,_=system
    response=call('POST','/api/coordination/candidates',json={'start':'2026-11-02T08:00:00+08:00','end':'2026-11-02T12:00:00+08:00','duration_minutes':60}).json()
    assert not response['candidates'] and response['diagnostics'] and response['alternatives']
