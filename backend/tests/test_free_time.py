from sqlalchemy import delete,select,func
from app import main,assistant
from app.models import Availability,Task,User,BusyInterval,ScheduledTask,PlanVersion
from app.plans import compute,valid_current
from app.timeutil import dt

DAY='2026-11-03T09:07:00+08:00'

def setup_day(factory):
    with factory() as db:
        for cls in (ScheduledTask,PlanVersion,Task,BusyInterval,Availability):
            db.execute(delete(cls))
        user=db.get(User,'A');user.window_start='2026-11-03T08:00:00+08:00';user.window_end='2026-11-04T22:00:00+08:00'
        db.add(BusyInterval(owner_id='A',title='本人课程',start='2026-11-03T10:00:00+08:00',end='2026-11-03T12:00:00+08:00',kind='course'))
        db.add(Task(owner_id='A',title='已有任务',deadline='2026-11-03T22:00:00+08:00',duration_minutes=60,priority=2,dependencies=[],source='manual'))
        db.commit()

def test_unconfigured_is_not_no_free_time_and_applying_preserves_tasks(system,monkeypatch):
    call,factory,_=system;setup_day(factory)
    monkeypatch.setattr(main,'now',lambda:DAY);monkeypatch.setattr(assistant,'now',lambda:DAY)
    with factory() as db:
        result=compute(db,db.get(User,'A'))
        assert result['availability_status']=='missing' and '不代表' in result['diagnostics'][0]
        facts=assistant.collect(db,db.get(User,'A'),assistant.Understanding(intent='free',date=DAY))
        assert not facts['free'] and facts['observed_gaps']
        assert '参考空档' in assistant.answer(assistant.Understanding(intent='free'),facts)
    response=call('GET','/api/availability/suggestions');assert response.status_code==200
    assert response.headers['Cache-Control']=='no-store'
    suggestions=response.json();assert suggestions['configuration_status']=='missing'
    slots=suggestions['eligible_slots'];assert slots[0]['start']=='2026-11-03T09:15:00+08:00'
    assert all(dt(s['end'])<=dt('2026-11-03T10:00:00+08:00') or dt(s['start'])>=dt('2026-11-03T12:00:00+08:00') for s in slots)
    before=call('GET','/api/availability/suggestions',member='B').json()
    saved=call('POST','/api/availability/apply-suggestions',key='allow-once',json={'slots':[{'start':slots[-1]['start'],'end':slots[-1]['end']}]})
    assert saved.status_code==200,saved.text
    assert saved.json()['plan'] and saved.json()['availability_added']==1
    repeat=call('POST','/api/availability/apply-suggestions',key='allow-once',json={'slots':[{'start':slots[-1]['start'],'end':slots[-1]['end']}]})
    assert repeat.json()==saved.json()
    assert call('GET','/api/availability/suggestions',member='B').json()==before
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Task))==1
        assert db.scalar(select(func.count()).select_from(Availability))==1
        assert db.scalar(select(func.count()).select_from(PlanVersion))==1
        assert valid_current(db,db.get(User,'A'))

def test_apply_rejects_outside_window_atomically_and_requires_auth(system,monkeypatch):
    call,factory,client=system;setup_day(factory)
    assert client.get('/api/availability/suggestions').status_code==401
    response=call('POST','/api/availability/apply-suggestions',json={'slots':[
        {'start':'2026-11-03T13:00:00+08:00','end':'2026-11-03T14:00:00+08:00'},
        {'start':'2026-11-08T13:00:00+08:00','end':'2026-11-08T14:00:00+08:00'}]})
    assert response.status_code==422
    with factory() as db:assert db.scalar(select(func.count()).select_from(Availability))==0

def test_configured_outside_window_explains_wrong_range(system):
    call,factory,_=system;setup_day(factory)
    with factory() as db:
        db.add(Availability(owner_id='A',kind='available',start='2026-11-08T13:00:00+08:00',end='2026-11-08T14:00:00+08:00'));db.flush()
        result=compute(db,db.get(User,'A'))
        assert result['availability_status']=='outside_window'
        assert '没有覆盖' in result['diagnostics'][0]
