import json
import asyncio
import httpx
import pytest
from app import ai_config, ai

@pytest.fixture
def config(tmp_path,monkeypatch):
    target=tmp_path/'.env'
    target.write_text('DEMO_MODE=true\n',encoding='utf8')
    monkeypatch.setattr(ai_config,'ENV_FILE',target)
    for name in ('AI_API_KEY','AI_MODEL','AI_BASE_URL','AI_PROVIDER'): monkeypatch.delenv(name,raising=False)
    # Register restoration before save() changes process configuration.
    for name,value in {'AI_API_KEY':'','AI_MODEL':'mimo-v2.6-pro','AI_BASE_URL':ai_config.BASE,'AI_PROVIDER':'mimo'}.items(): monkeypatch.setenv(name,value)
    monkeypatch.setenv('ASSISTANT_MODE','mock')
    return target

def client_mock(monkeypatch,status=200,content='{"ok":true}',capture=None):
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,headers,json):
            if capture is not None: capture.update(url=url,headers=headers,payload=json)
            return httpx.Response(status,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':content}}]})
    monkeypatch.setattr(ai_config.httpx,'AsyncClient',lambda **kwargs:Client())

def test_save_test_secret_not_returned(system,config,monkeypatch):
    client_mock(monkeypatch)
    call,_,_=system
    result=call('POST','/api/ai/test-and-save',json={'api_key':'private-test-credential'} )
    assert result.status_code==200 and result.json()['tested']
    assert 'private-test-credential' not in result.text
    assert 'private-test-credential' in config.read_text()
    assert call('GET','/api/ai/settings').json()['has_key']
    assert result.json()['assistant_mode']=='auto'
    assert "ASSISTANT_MODE='auto'" in config.read_text()
    from app import assistant
    assert isinstance(assistant.provider(),assistant.CompatibleProvider)
    assert 'private-test-credential' not in call('GET','/api/ai/settings').text
    assert call('POST','/api/ai/demo').json()['mode']=='demo'
    assert 'private-test-credential' not in config.read_text()

def test_failed_test_preserves_configuration(system,config,monkeypatch):
    before=config.read_text();client_mock(monkeypatch,status=401)
    call,_,_=system
    result=call('POST','/api/ai/test-and-save',json={'api_key':'private-test-credential'})
    assert result.status_code==502 and '401' in result.text
    assert 'private-test-credential' not in result.text and config.read_text()==before

def test_settings_require_admin_and_origin(system,config):
    call,_,client=system
    assert call('GET','/api/ai/settings',member='B').status_code==403
    assert client.get('/api/ai/settings').status_code==401
    assert call('POST','/api/ai/test-and-save',json={'base_url':'http://localhost.evil/v1','api_key':'test'}).status_code==400
    from app.main import local_ai_admin
    from app.auth import Principal, WEB_SCOPES
    from starlette.requests import Request
    from types import SimpleNamespace
    from fastapi import HTTPException
    request=Request({'type':'http','client':('127.0.0.1',1),'server':('127.0.0.1',8000),'scheme':'http','path':'/','headers':[(b'origin',b'https://evil.example')]})
    # A sandbox session may never configure the model endpoint, even as member A.
    sandbox=Principal(user=SimpleNamespace(id='A'),kind='session',scope=WEB_SCOPES)
    with pytest.raises(HTTPException): local_ai_admin(request,sandbox)
    workstation=Principal(user=SimpleNamespace(id='A'),kind='user',scope=WEB_SCOPES)
    with pytest.raises(HTTPException): local_ai_admin(request,workstation)  # cross-origin

def test_actual_mimo_payload_for_image(config,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','private-test-credential')
    capture={}
    content=json.dumps({'title':'报告','deadline':'2026-11-05T18:00:00+08:00','requirements':'PDF','priority':None,'evidence':'2026年11月5日18:00','ambiguities':[]})
    client_mock(monkeypatch,content=content,capture=capture)
    result=asyncio.run(ai.extract('',b'fake-image-for-mock','image/png'))
    assert result['mode']=='live'
    assert capture['url']==ai_config.BASE+'/chat/completions'
    assert capture['headers']=={'api-key':'private-test-credential'}
    assert capture['payload']['thinking']=={'type':'disabled'}
    assert capture['payload']['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')

def test_switching_endpoint_cannot_reuse_old_key(config,monkeypatch):
    monkeypatch.setenv('AI_API_KEY','existing-test-key')
    with pytest.raises(ValueError): ai_config.resolved(ai_config.SettingsInput(base_url='https://token-plan-sgp.xiaomimimo.com/v1'))
