import json
import pytest
from sqlalchemy import select,func
from app.models import BusyInterval,TimetableImport
from app.timetable import RecognizedCourse
from app.school_time import apply_defaults

def course(**changes):
    return {'title':'物理实验','weekday':2,'start_time':'14:00','end_time':'16:00','evidence':'周三14:00-16:00物理实验',**changes}
def data(**changes): return {'week_start':'2026-11-02','courses':[course()],'source':'manual',**changes}

def test_preview_does_not_write_confirm_persists_and_schedule_invalidates(system):
    call,factory,_=system
    before=call('GET','/api/users/A/state').json()
    preview=call('POST','/api/timetable/preview',json=data()).json()
    assert preview['create_count']==1
    assert '机器学习 · 实验报告' in preview['courses'][0]['task_conflicts']
    assert call('GET','/api/users/A/state').json()['busy']==before['busy']
    payload={**data(),'confirmed':True,'expected_snapshot':preview['expected_snapshot']}
    result=call('POST','/api/timetable/import',json=payload,key='courses-1')
    assert result.status_code==200,result.text
    assert result.json()['created']==1
    assert call('POST','/api/timetable/import',json=payload,key='courses-1').json()==result.json()
    after=call('GET','/api/users/A/state').json()
    assert not after['plan_valid'] and after['plan']['id']==before['plan']['id']
    record=call('GET','/api/timetable/imports').json()[0]
    assert record['courses'][0]['evidence']==course()['evidence']
    assert call('GET','/api/timetable/imports',member='B').json()==[]
    with factory() as db:
        row=db.get(BusyInterval,record['courses'][0]['busy_id'])
        assert row.weekday is None and row.start=='2026-11-04T14:00:00+08:00'
    repaired=call('POST','/api/plans').json()
    assert repaired['status'] in ('optimal','feasible')
    assert call('GET','/api/users/A/state').json()['plan_valid']

def test_duplicates_against_recurring_and_same_batch(system):
    call,_,_=system
    payload=data(courses=[course(title='高等数学',weekday=0,start_time='08:00',end_time='10:00'),course(),course()])
    preview=call('POST','/api/timetable/preview',json=payload).json()
    assert preview['skip_count']==2 and preview['create_count']==1

def test_imported_week_metadata_outside_planning_window_and_private(system):
    call,_,_=system
    payload=data(week_start='2026-12-07')
    preview=call('POST','/api/timetable/preview',json=payload).json()
    assert call('POST','/api/timetable/import',json={**payload,'confirmed':True,'expected_snapshot':preview['expected_snapshot']}).status_code==200
    state=call('GET','/api/users/A/state').json()
    assert state['timetable_imports'][0]['week_start']=='2026-12-07'
    assert state['timetable_imports'][0]['course_count']==1
    assert any(r['start'].startswith('2026-12-09') for r in state['busy'])
    assert call('GET','/api/users/B/state',member='B').json()['timetable_imports']==[]

@pytest.mark.parametrize('payload',[data(week_start='2026-11-03'),data(courses=[course(start_time='第1节')]),data(courses=[course(start_time='17:00')]),data(courses=[course(weekday=7)]),data(courses=[course(title=' ')]),data(courses=[])])
def test_validation(system,payload):
    call,_,_=system
    assert call('POST','/api/timetable/preview',json=payload).status_code==422

def test_confirmation_and_stale_preview(system):
    call,_,_=system
    preview=call('POST','/api/timetable/preview',json=data()).json()
    assert call('POST','/api/timetable/import',json={**data(),'expected_snapshot':preview['expected_snapshot']}).status_code==422
    call('POST','/api/busy',json={'title':'新课','start':'2026-11-04T14:00:00+08:00','end':'2026-11-04T15:00:00+08:00'})
    assert call('POST','/api/timetable/import',json={**data(),'confirmed':True,'expected_snapshot':preview['expected_snapshot']}).status_code==409
    assert call('POST','/api/timetable/preview',json=data()).json()['courses'][0]['conflicts']==['新课']

def test_demo_image_is_never_fake_ocr(system,monkeypatch):
    monkeypatch.delenv('AI_API_KEY',raising=False)
    call,_,_=system
    result=call('POST','/api/timetable/extract',files={'image':('demo.png',b'\x89PNG\r\n\x1a\nmock','image/png')}).json()
    assert result['mode']=='demo' and result['data']['courses']==[] and result['data']['ambiguities']
    assert call('POST','/api/timetable/extract',files={'image':('invalid.png',b'bad','image/png')}).status_code==422

def test_vision_mapping_and_missing_times(system,monkeypatch):
    import httpx
    monkeypatch.setenv('AI_API_KEY','fake-test-key')
    capture={}
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,headers,json):
            capture.update(json)
            result={'courses':[course(start_time=None,end_time=None,ambiguities=['只有第1-2节，未给作息']),course(title='英语',weekday=1,evidence='',ambiguities=[])],'ambiguities':['第1-16周，单双周需核对']}
            return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':__import__('json').dumps(result)}}]})
    monkeypatch.setattr('app.ai.httpx.AsyncClient',lambda **kwargs:Client())
    call,_,_=system
    result=call('POST','/api/timetable/extract',data={'notes':'第一节08:00-08:45'},files={'image':('demo.png',b'\x89PNG\r\n\x1a\nmock','image/png')}).json()
    assert result['mode']=='live'
    assert result['data']['courses'][0]['start_time'] is None
    assert result['data']['courses'][1]['start_time'] is None
    assert '08:00' in capture['messages'][1]['content'][0]['text']
    assert capture['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert call('GET','/api/timetable/imports').json()==[]


@pytest.mark.parametrize('number,start,end',[
    (1,'08:00','08:45'),(2,'08:55','09:40'),(3,'10:00','10:45'),(4,'10:55','11:40'),
    (5,'14:30','15:15'),(6,'15:15','16:00'),(7,'16:10','16:55'),(8,'16:55','17:40'),
    (9,'19:00','19:45'),(10,'19:55','20:40'),(11,'20:50','21:35')])
def test_user_huda_period_times(number,start,end):
    row=RecognizedCourse(**course(start_time=None,end_time=None,evidence=f'周三 第{number}节 物理实验',ambiguities=[]))
    apply_defaults(row)
    assert (row.start_time,row.end_time)==(start,'21:35' if number==9 else end)
    assert row.evidence==f'周三 第{number}节 物理实验'
    assert '湖大' in row.time_basis


def test_huda_profile_authentication_and_exact_times(system):
    call,_,client=system
    assert client.get('/api/timetable/profile').status_code==401
    profile=call('GET','/api/timetable/profile').json()
    assert len(profile['periods'])==11 and profile['evening_end']=='21:35'
    assert profile['periods'][5]['start']=='15:15' and profile['periods'][7]['start']=='16:55'


def test_extraction_uses_huda_mapping_evening_rule_and_opt_out(system,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','fake-test-key')
    async def model(*args):
        return {'courses':[
            course(start_time='08:00',end_time='09:30',evidence='周三 第1-2节 物理实验',ambiguities=[]),
            course(start_time='19:00',end_time='20:30',evidence='周三 19：00 物理实验',ambiguities=[]),
            course(start_time='19:00',end_time='20:40',evidence='周三 19:00–20:40 物理实验',ambiguities=[]),
            course(start_time=None,end_time=None,period_start=5,period_end=8,evidence='周三第5至8节物理实验',ambiguities=[]),
            course(start_time=None,end_time=None,evidence='',period_start=1,period_end=2,ambiguities=[]),
        ],'ambiguities':[]}
    monkeypatch.setattr('app.timetable.call_model',model)
    call,_,_=system
    def extract(enabled):
        response=call('POST','/api/timetable/extract',data={'use_school_schedule':str(enabled).lower()},files={'image':('demo.png',b'\x89PNG\r\n\x1a\nmock','image/png')})
        assert response.status_code==200,response.text
        return response.json()['data']['courses']
    rows=extract(True)
    assert (rows[0]['start_time'],rows[0]['end_time'])==('08:00','09:40')
    assert rows[1]['end_time']=='21:35' and rows[1]['time_basis']
    assert rows[2]['end_time']=='21:35' and rows[2]['time_basis']
    assert (rows[3]['start_time'],rows[3]['end_time'])==('14:30','17:40')
    assert rows[4]['start_time'] is None and rows[4]['end_time'] is None
    disabled=extract(False)
    assert disabled[0]['end_time']=='09:30' and disabled[1]['end_time']=='20:30'
    assert disabled[3]['start_time'] is None
    assert call('GET','/api/timetable/imports').json()==[]
