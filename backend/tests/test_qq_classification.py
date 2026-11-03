import pytest
from sqlalchemy import select,func
from app.models import Task,BusyInterval
from app.integrations.qq import service
from app.integrations.qq.classification import recommendation
from test_qq import group,event,receive,process,notices,confirm

@pytest.mark.parametrize('category,extraction,title,deadline,expected',[
    ('course',{},'高数课',None,'event'),
    ('report',{'evidence':'明天8点上实验报告课'},'实验报告课',None,'event'),
    ('important',{'evidence':'明天8点上课'},'通知',None,'event'),
    ('important',{'start':'2026-11-03T08:00:00+08:00'},'通知',None,'event'),
    ('report',{'evidence':'请提交课程报告'},'课程报告',None,'task'),
    ('assignment',{},'高数作业','2026-11-04T18:00:00+08:00','task'),
    ('important',{},'注意事项',None,''),
    ('important',{'entry_type':'notice'},'注意事项',None,'acknowledge'),
])
def test_recommendation_uses_activity_instead_of_always_ddl(category,extraction,title,deadline,expected):
    assert recommendation(category,extraction,title,deadline)['mode']==expected


@pytest.fixture(autouse=True)
def isolated_classification(monkeypatch):
    monkeypatch.setenv('QQ_MANAGED_BOT_ID','');monkeypatch.setenv('QQ_REPLY_ENABLED','false')
    monkeypatch.setenv('QQ_PROCESSOR_ENABLED','false');monkeypatch.setenv('AI_API_KEY','test-only')
    monkeypatch.setenv('QQ_AI_MODE','auto');monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    monkeypatch.setattr(service,'now',lambda:'2026-11-02T10:00:00+08:00')


def test_class_confirm_creates_course_without_ddl_task(system,monkeypatch):
    async def model(prompt,content):
        assert '正常上课course' in prompt and 'entry_type' in prompt
        return {'category':'course','entry_type':'event','title':'机械制图课','deadline':None,
            'start':'2026-11-03T08:00:00+08:00','end':'2026-11-03T09:40:00+08:00',
            'confidence':0.95,'evidence':'明天08:00—09:40上课'}
    monkeypatch.setattr(service.ai,'call_model',model)
    g=group(system);m=receive(system,g,event('《机械制图课》明天08:00—09:40上课。'))
    assert process(system,m['id'])['status']=='processed'
    notice=notices(system)[0];assert notice['suggested_mode']=='event' and notice['deadline'] is None
    with system[1]() as db:before=db.scalar(select(func.count()).select_from(Task))
    saved=confirm(system,notice['id'],mode='event');assert saved.status_code==200,saved.text
    with system[1]() as db:
        assert db.scalar(select(func.count()).select_from(Task))==before
        course=db.get(BusyInterval,saved.json()['busy_id']);assert course.kind=='course'
        assert course.end=='2026-11-03T09:40:00+08:00'


def test_legacy_course_notice_gets_event_recommendation_without_reextract(system,monkeypatch):
    async def model(*_):return {'category':'report','title':'实验报告课','confidence':0.8,'deadline':None,'evidence':'明天上实验报告课，开始时间8点'}
    monkeypatch.setattr(service.ai,'call_model',model)
    g=group(system);m=receive(system,g,event('明天上实验报告课，开始时间8点'))
    process(system,m['id']);notice=notices(system)[0]
    assert notice['suggested_mode']=='event' and notice['category']=='report'
    assert notice['extraction']['end'] is None  # No invented course duration.


def test_cancel_and_linked_task_preserve_existing_semantics():
    assert recommendation('course',{},operation='cancel')['mode']=='acknowledge'
    assert recommendation('course_change',{},has_task=True)['mode']=='task'


def test_explicit_demo_class_is_event_and_does_not_invent_duration():
    from app.integrations.qq.filters import demo_extract
    result=demo_extract('明天08:00上实验报告课','2026-11-02T10:00:00+08:00')
    assert result.category=='course' and result.entry_type=='event' and result.deadline is None
    assert result.start=='2026-11-03T08:00:00+08:00' and result.end is None
