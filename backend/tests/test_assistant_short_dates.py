"""Short calendar dates and fragmented QQ drafts, using synthetic data only."""
import asyncio
import json
import pytest
from app import assistant
from app.models import BusyInterval,AssistantThread
from sqlalchemy import select


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(assistant,'now',lambda:'2026-11-03T16:00:00+08:00')


@pytest.mark.parametrize('text',['12.3','12/3','12-3','12月3日','12月3号','2026.12.3'])
def test_calendar_notation_resolves_month_day_not_previous_date(text):
    date,_,period=assistant.date_range(text,{'date':'2026-11-04T00:00:00+08:00','period':'evening'})
    assert date=='2026-12-03T00:00:00+08:00' and period=='day'


@pytest.mark.parametrize('text',['耗时1.2小时','12.5分钟','deepseekv4.1','明天8.30到9.30','v12.3','力学12.5','高数1.2'])
def test_decimal_duration_model_version_and_clock_range_are_not_calendar_dates(text):
    assert assistant.calendar_date(text,{}) is None


def test_invalid_calendar_date_is_not_invented():
    with pytest.raises(ValueError):assistant.date_range('添加2.30晚上八点到九点',{})


def test_full_dotted_date_is_not_left_in_event_title():
    text='添加2026.12.3晚上八点到九点的实验课'
    day,_,period=assistant.date_range(text,{})
    parsed=assistant._event_request(text,{},day,period,None)
    assert parsed.payload['title']=='实验课'


def test_old_event_body_mislabeled_task_is_recovered_without_changing_original_context():
    old={**pending(),'pending_action':'create_task'}
    recovered=assistant.recover_event_draft([],old)
    assert recovered['pending_action']=='create_event' and old['pending_action']=='create_task'


def test_explicit_day_wins_over_wrong_model_iso_date_and_generic_time_evidence():
    previous={'date':'2026-11-04T00:00:00+08:00'}
    u=assistant.Understanding(action='create_event',date='2026-11-04',
        payload={'title':'合成实验课','start':'2026-11-04T20:00:00+08:00','end':'2026-11-04T21:00:00+08:00','kind':'course'},
        evidence={'date':'12.3','start':'八点','end':'九点'})
    result=assistant.grounded_event(u,'添加12.3晚上八点到九点的合成实验课',previous)
    assert result.date=='2026-12-03T00:00:00+08:00'
    assert result.payload['start']=='2026-12-03T20:00:00+08:00'
    assert result.payload['end']=='2026-12-03T21:00:00+08:00'


def test_model_event_payload_with_wrong_task_action_is_not_asked_for_deadline(monkeypatch):
    async def model(*_):return {'action':'create_task','date':'2026-12-03','payload':{
        'title':'合成实验课','start':'2026-12-03T20:00:00+08:00','end':'2026-12-03T21:00:00+08:00','kind':'course'},
        'evidence':{'time':'12.3晚上八点到九点的合成实验课'}}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=asyncio.run(assistant.CompatibleProvider().understand('添加12.3晚上八点到九点的合成实验课',{},[],[]))
    assert result.action=='create_event' and result.payload['start']=='2026-12-03T20:00:00+08:00'


def pending():
    return {'date':'2026-12-03T00:00:00+08:00','period':'evening','pending_action':'create_event',
            'pending_payload':{'title':'合成实验课','_date':'2026-12-03T00:00:00+08:00','start':'2026-12-03T20:00:00+08:00','end':'2026-12-03T21:00:00+08:00','kind':'course'}}


def test_date_only_revision_preserves_name_and_clock_even_if_model_says_replace(monkeypatch):
    async def model(*_):return {'action':'create_event','date':'2026-12-05','pending':'replace','payload':{'kind':'course'}}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=asyncio.run(assistant.CompatibleProvider().understand('调整到12.5',pending(),[],[]))
    assert result.pending=='continue' and result.payload['title']=='合成实验课'
    assert result.payload['start']=='2026-12-05T20:00:00+08:00' and result.payload['end']=='2026-12-05T21:00:00+08:00'


def test_day_and_new_end_time_are_not_overwritten_by_old_duration():
    u=assistant.Understanding(action='create_event',date='2026-12-05',payload={'kind':'course'})
    result=assistant.grounded_event(u,'12.5 晚上8点到10点',pending())
    assert result.payload['start']=='2026-12-05T20:00:00+08:00'
    assert result.payload['end']=='2026-12-05T22:00:00+08:00'


def test_name_only_revision_keeps_time_without_requiring_separate_evidence_key():
    u=assistant.Understanding(action='create_event',payload={'title':'合成力学一'},evidence={'time':'合成力学一'})
    result=assistant.grounded_event(u,'合成力学一',pending())
    assert result.payload['title']=='合成力学一' and result.payload['start']=='2026-12-03T20:00:00+08:00'


def test_damaged_draft_recovers_only_user_times_since_last_save_and_keeps_latest_name():
    history=[{'role':'user','content':'添加明天晚上八点到九点的高数复习','created_at':assistant.now()},
             {'role':'assistant','content':'已添加','event':'applied'},
             {'role':'user','content':'添加12.3晚上八点到九点的合成实验课','created_at':assistant.now()},
             {'role':'user','content':'调整到12.5','created_at':assistant.now()},
             {'role':'user','content':'合成力学一','created_at':assistant.now()},
             {'role':'assistant','content':'模型猜测3月1日凌晨1点到6点'},
             {'role':'user','content':'12.5 晚上8点到10点','created_at':assistant.now()}]
    old={'date':'2026-11-04T00:00:00+08:00','pending_action':'create_event','pending_payload':{'title':'合成力学一','kind':'course'}}
    result=assistant.recover_event_draft(history,old)
    assert result['date']=='2026-12-05T00:00:00+08:00' and result['pending_payload']['title']=='合成力学一'
    assert result['pending_payload']['start']=='2026-12-05T20:00:00+08:00' and result['pending_payload']['end']=='2026-12-05T22:00:00+08:00'
    assert old['date']=='2026-11-04T00:00:00+08:00'  # Recovery does not mutate the stored object.


def test_cancellation_stops_draft_history_recovery():
    history=[{'role':'user','content':'添加12.3晚上八点到九点的“合成课程”','created_at':assistant.now()},
             {'role':'user','content':'取消，算了','created_at':assistant.now()}]
    old={'pending_action':'create_event','pending_payload':{'title':'新事项'}}
    assert assistant.recover_event_draft(history,old)==old


def test_qq_style_new_event_does_not_conflict_with_unrelated_november_event(system,monkeypatch):
    monkeypatch.delenv('ASSISTANT_AUTO_CREATE',raising=False);monkeypatch.setenv('ASSISTANT_MODE','auto');monkeypatch.setenv('AI_API_KEY','test-only')
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    with system[1]() as db:
        db.add(BusyInterval(owner_id='A',title='合成旧复习',start='2026-11-04T20:00:00+08:00',end='2026-11-04T21:00:00+08:00',kind='unavailable'));db.commit()
    async def model(*_):return {'action':'create_event','date':'2026-11-04','pending':'replace','payload':{'title':'合成实验课','start':'2026-11-04T20:00:00+08:00','end':'2026-11-04T21:00:00+08:00','kind':'course'},'evidence':{'date':'12.3','start':'八点','end':'九点'}}
    monkeypatch.setattr(assistant.ai,'call_model',model)
    result=system[0]('POST','/api/v1/assistant/chat',json={'message':'添加12.3晚上八点到九点的合成实验课','request_id':'short-date-add'})
    assert result.status_code==200,result.text
    data=result.json();assert data['applied'] and data['applied_result']['start']=='2026-12-03T20:00:00+08:00'
    with system[1]() as db:
        event=db.scalar(select(BusyInterval).where(BusyInterval.owner_id=='A',BusyInterval.title=='合成实验课'))
        assert event.start=='2026-12-03T20:00:00+08:00'
