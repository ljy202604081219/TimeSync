from types import SimpleNamespace
from app.timeutil import expand,dt
from app.ai import Extraction
from sqlalchemy import select
from app.models import BusyInterval


def test_negotiation_alternatives_never_start_before_requested_seconds(system):
    call,_,_=system
    start='2026-11-02T08:00:30+08:00'
    response=call('POST','/api/coordination/candidates',json={'start':start,'end':'2026-11-02T10:00:00+08:00','duration_minutes':60}).json()
    assert not response['candidates'] and response['alternatives']
    assert all(dt(r['start'])>=dt(start) and dt(r['start']).minute%15==0 for r in response['alternatives'])

def test_weekly_available_seconds_not_rounded_outward():
    row=SimpleNamespace(start='2026-11-02T08:00:30+08:00',end='2026-11-02T09:00:45+08:00',weekday=0)
    ranges=expand([row],'2026-11-09T08:00:00+08:00','2026-11-10T08:00:00+08:00')
    assert ranges==[(dt('2026-11-09T08:00:30+08:00'),dt('2026-11-09T09:00:45+08:00'))]

def test_window_more_than_14_days_rejected(system):
    call,_,_=system
    assert call('PUT','/api/settings/window',json={'start':'2026-11-01T00:00:00+08:00','end':'2026-11-15T00:01:00+08:00'}).status_code==422

def test_invitation_conflict_added_before_final_confirmation(system):
    call,_,_=system
    meeting=call('POST','/api/meetings',json={'title':'讨论','start':'2026-11-04T14:00:00+08:00','end':'2026-11-04T15:00:00+08:00','members':['A','B','C','D']}).json()
    for member in 'ABC':
        assert call('POST',f"/api/meetings/{meeting['id']}/respond",member,json={'response':'accepted','revision':1}).json()['status']=='pending'
    call('POST','/api/busy',member='D',json={'title':'临时课','start':meeting['start'],'end':meeting['end']})
    final=call('POST',f"/api/meetings/{meeting['id']}/respond",member='D',json={'response':'accepted','revision':1}).json()
    assert final['status']=='needs_reschedule'

def test_live_evidence_mismatch_clears_deadline(system,monkeypatch):
    import httpx,json
    monkeypatch.setenv('AI_API_KEY','test-only')
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs):
            data={'title':'报告','deadline':'2027-11-05T18:00:00+08:00','requirements':'PDF','priority':None,'evidence':'2026年11月5日18:00','ambiguities':[]}
            return httpx.Response(200,request=httpx.Request('POST','https://example.test'),json={'choices':[{'message':{'content':json.dumps(data)}}]})
    monkeypatch.setattr('app.ai.httpx.AsyncClient',lambda **kwargs:Client())
    call,_,_=system
    result=call('POST','/api/extract',data={'text':'2026年11月5日18:00提交报告'}).json()
    assert result['mode']=='live' and result['data']['deadline'] is None and result['data']['ambiguities']
