from app.intervals import intersect,subtract,candidates
from app.ai import demo_extract,extract
from app.timeutil import dt
import pytest

def test_intersection():
    assert intersect([(0,3),(4,9)],[(2,5),(7,10)])==[(2,3),(4,5),(7,9)]
    assert intersect([(0,2)],[(2,3)])==[]
    assert subtract([(0,10)],[(2,4),(3,6)])==[(0,2),(6,10)]

def test_candidate_rounding_and_preference():
    a=dt('2026-11-02T08:00:30+08:00');b=dt('2026-11-02T10:00:00+08:00')
    out=candidates({'A':[(a,b)],'B':[(a,b)]},60)
    assert dt(out[0]['start'])==dt('2026-11-02T08:15:00+08:00')

def test_demo_never_invents_date_time():
    assert demo_extract('周五交作业').deadline is None
    assert demo_extract('2026年11月5日提交').deadline is None
    assert demo_extract('2026年11月5日18:00提交').deadline=='2026-11-05T18:00:00+08:00'
    assert demo_extract('2026年2月30日18:00').deadline is None
    assert demo_extract('',True).deadline is None
    assert demo_extract('2026年11月4日10:00布置，2026年11月5日18:00提交').deadline is None

def test_extraction_api_demo_and_image(system,monkeypatch):
    monkeypatch.delenv('AI_API_KEY',raising=False)
    call,_,_=system
    result=call('POST','/api/extract',data={'text':'作业\n2026年11月5日18:00 提交报告'}).json()
    assert result['mode']=='demo' and result['data']['deadline']
    assert call('POST','/api/extract',files={'image':('bad.png',b'not an image','image/png')}).status_code==422
    image=call('POST','/api/extract',files={'image':('screen.png',b'\x89PNG\r\n\x1a\n'+'fake'.encode(),'image/png')}).json()
    assert image['mode']=='demo' and image['data']['deadline'] is None

def test_live_model_invalid_json_is_rejected(system,monkeypatch):
    import httpx
    monkeypatch.setenv('AI_API_KEY','test-only')
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,*args,**kwargs):
            return httpx.Response(200,request=httpx.Request('POST','https://example.test'),json={'choices':[{'message':{'content':'{"title":"bad"}'}}]})
    monkeypatch.setattr('app.ai.httpx.AsyncClient',lambda **kwargs:Client())
    call,_,_=system
    assert call('POST','/api/extract',data={'text':'通知'}).status_code==502
