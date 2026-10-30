from app.models import BusyInterval, Task
from sqlalchemy import select

RANGE={'start':'2026-11-04T00:00:00+08:00','end':'2026-11-05T00:00:00+08:00'}


def test_agenda_defaults_to_server_today_and_does_not_write(system,monkeypatch):
    from sqlalchemy import func
    from app.models import PlanVersion
    monkeypatch.setattr('app.agenda.now',lambda:'2026-11-04T12:30:00+08:00')
    call,factory,_=system
    with factory() as db: before=db.scalar(select(func.count()).select_from(PlanVersion))
    result=call('GET','/api/v1/agenda').json()
    assert result['start']==RANGE['start'] and result['end']==RANGE['end']
    assert result['server_time']=='2026-11-04T12:30:00+08:00'
    with factory() as db: assert db.scalar(select(func.count()).select_from(PlanVersion))==before


def test_agenda_auth_owner_and_bounded_query(system):
    call,_,client=system
    assert client.get('/api/v1/agenda',params=RANGE).status_code==401
    assert call('GET','/api/v1/agenda',params={**RANGE,'owner':'B'}).status_code==422
    a=call('GET','/api/v1/agenda',params=RANGE)
    b=call('GET','/api/v1/agenda',member='B',params=RANGE)
    assert a.status_code==200 and b.status_code==200
    assert a.json()['user_id']=='A' and b.json()['user_id']=='B'
    assert a.json()['revision']!=b.json()['revision']
    assert {e['kind'] for e in a.json()['events']}=={'course','task'}
    assert 'evidence' not in a.text and 'token' not in a.text and 'linkage' not in a.text
    for params in ({'start':RANGE['start']},{**RANGE,'limit':51},{**RANGE,'end':'2026-11-12T00:00:00+08:00'},{**RANGE,'start':'2026-11-04T00:00:00'}):
        assert call('GET','/api/v1/agenda',params=params).status_code==422


def test_agenda_etag_auth_and_changed_data(system):
    call,factory,client=system
    first=call('GET','/api/v1/agenda',params=RANGE)
    token_headers=first.request.headers
    headers={'Authorization':token_headers['authorization'],'If-None-Match':first.headers['etag']}
    same=client.get('/api/v1/agenda',params=RANGE,headers=headers)
    assert same.status_code==304 and same.content==b''
    assert same.headers['cache-control']=='private, no-cache'
    assert client.get('/api/v1/agenda',params=RANGE,headers={'If-None-Match':first.headers['etag']}).status_code==401
    with factory() as db:
        db.add(BusyInterval(owner_id='A',title='临时课',start='2026-11-04T14:00:00+08:00',end='2026-11-04T15:00:00+08:00',kind='course'))
        db.commit()
    changed=client.get('/api/v1/agenda',params=RANGE,headers=headers)
    assert changed.status_code==200 and changed.headers['etag']!=first.headers['etag']
    assert changed.json()['plan']['repair_needed']
    assert next(e for e in changed.json()['events'] if e['kind']=='task')['status']=='stale'


def test_agenda_imported_courses_outside_plan_window_and_real_times(system):
    call,factory,_=system
    with factory() as db:
        db.add(BusyInterval(owner_id='A',title='导入课程',start='2026-12-07T09:00:00+08:00',end='2026-12-07T11:00:00+08:00',kind='course'))
        db.commit()
    result=call('GET','/api/v1/agenda',params={'start':'2026-12-07T09:30:00+08:00','end':'2026-12-07T10:00:00+08:00'}).json()
    imported=next(e for e in result['events'] if e['title']=='导入课程')
    assert imported['start']=='2026-12-07T09:00:00+08:00'
    assert imported['end']=='2026-12-07T11:00:00+08:00'
    assert len({e['id'] for e in result['events']})==len(result['events'])


def test_agenda_meeting_confirmation_and_repair_integration(system):
    call,_,_=system
    meeting=call('POST','/api/meetings',json={'title':'组会','start':'2026-11-04T14:00:00+08:00','end':'2026-11-04T16:00:00+08:00','members':['A','B','C','D']}).json()
    pending=call('GET','/api/v1/agenda',params=RANGE).json()
    assert pending['pending_invitations'][0]['meeting_id']==meeting['id']
    assert all(e['kind']!='meeting' for e in pending['events'])
    for member in 'ABCD':
        result=call('POST',f"/api/meetings/{meeting['id']}/respond",member,json={'response':'accepted','revision':1}).json()
    assert result['status']=='confirmed'
    confirmed=call('GET','/api/v1/agenda',params=RANGE).json()
    assert not confirmed['pending_invitations'] and confirmed['plan']['valid']
    assert next(e for e in confirmed['events'] if e['kind']=='meeting')['status']=='confirmed'
    assert confirmed['revision']!=pending['revision']
    assert next(e for e in confirmed['events'] if e['kind']=='task')['start']!='2026-11-04T14:00:00+08:00'


def test_agenda_ddl_half_open_window_and_truncation(system):
    call,factory,_=system
    with factory() as db:
        task=db.scalar(select(Task).where(Task.owner_id=='A'))
        task.deadline='2026-11-05T00:00:00+08:00';db.commit()
    result=call('GET','/api/v1/agenda',params={**RANGE,'limit':1}).json()
    assert len(result['events'])==1 and result['truncated'] and result['event_total']>1
    assert all(e['kind']!='deadline' for e in call('GET','/api/v1/agenda',params=RANGE).json()['events'])
    tomorrow=call('GET','/api/v1/agenda',params={'start':RANGE['end'],'end':'2026-11-06T00:00:00+08:00'}).json()
    assert any(e['kind']=='deadline' and e['start']==e['end']==RANGE['end'] for e in tomorrow['events'])
