"""B2: AI budget, concurrency guard and request-size protection."""
import json

import httpx
import pytest
from sqlalchemy import func, select

from app import ai_budget
from app.models import AiUsage

TEXT = '2026年11月5日18:00提交报告'
LIVE = {'title': '报告', 'deadline': '2026-11-05T18:00:00+08:00', 'requirements': 'PDF',
        'priority': None, 'evidence': '2026年11月5日18:00', 'ambiguities': []}


def mock_model(monkeypatch, status=200, content=None):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return httpx.Response(
                status,
                request=httpx.Request('POST', 'https://api.xiaomimimo.com/v1/chat/completions'),
                json={'choices': [{'message': {'content': json.dumps(content or LIVE)}}]},
            )

    monkeypatch.setattr('app.ai.httpx.AsyncClient', lambda **kwargs: Client())


@pytest.fixture
def live_ai(monkeypatch):
    monkeypatch.setenv('AI_BUDGET_ENABLED','true')  # legacy opt-in limits remain testable
    monkeypatch.setenv('AI_API_KEY', 'budget-test-key')
    mock_model(monkeypatch)
    return monkeypatch


def usage_rows(factory):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(AiUsage)) or 0


def test_budget_blocks_after_limit_with_retry_after(system, live_ai):
    call, factory, _ = system
    live_ai.setenv('AI_DAILY_BUDGET', '1')
    live_ai.setenv('AI_ACTOR_DAILY_BUDGET', '5')
    first = call('POST', '/api/extract', data={'text': TEXT})
    assert first.status_code == 200, first.text
    second = call('POST', '/api/extract', data={'text': TEXT})
    assert second.status_code == 429
    assert int(second.headers['Retry-After']) > 0
    assert '额度' in second.json()['detail']
    assert usage_rows(factory) == 1


def test_budget_is_global_across_sessions(system, live_ai):
    call, factory, client = system
    live_ai.setenv('AI_DAILY_BUDGET', '2')
    live_ai.setenv('SANDBOX_MODE', 'true')
    tokens = [client.post('/api/sandbox/sessions', json={'member': member}).json()['token'] for member in ('A', 'B', 'C')]
    results = []
    for token in tokens:
        results.append(client.post('/api/extract', data={'text': TEXT}, headers={'Authorization': 'Bearer ' + token}))
    assert [r.status_code for r in results] == [200, 200, 429]
    assert usage_rows(factory) == 2


def test_failed_attempt_is_counted_and_not_hidden_as_success(system, live_ai):
    call, factory, _ = system
    live_ai.setenv('AI_DAILY_BUDGET', '1')
    mock_model(live_ai, status=401)
    failed = call('POST', '/api/extract', data={'text': TEXT})
    assert failed.status_code == 502 and '未保存任何任务' in failed.json()['detail']
    blocked = call('POST', '/api/extract', data={'text': TEXT})
    assert blocked.status_code == 429
    with factory() as db:
        assert db.scalar(select(AiUsage)).status == 'error'


def test_concurrency_guard_rejects_parallel_calls(system, live_ai):
    call, factory, _ = system
    live_ai.setenv('AI_MAX_CONCURRENCY', '1')
    with factory() as db:
        ai_budget.reserve(db, 'session:A:test', 'extract')
    busy = call('POST', '/api/extract', data={'text': TEXT})
    assert busy.status_code == 429 and '正在处理中' in busy.json()['detail']


def test_demo_mode_costs_nothing_and_records_nothing(system, monkeypatch):
    call, factory, _ = system
    monkeypatch.delenv('AI_API_KEY', raising=False)
    monkeypatch.setenv('AI_DAILY_BUDGET', '0')
    for _ in range(2):
        assert call('POST', '/api/extract', data={'text': TEXT}).json()['mode'] == 'demo'
    assert usage_rows(factory) == 0


def test_quota_status_reports_remaining(system, live_ai):
    call, _, _ = system
    live_ai.setenv('AI_DAILY_BUDGET', '3')
    live_ai.setenv('AI_ACTOR_DAILY_BUDGET', '2')
    call('POST', '/api/extract', data={'text': TEXT})
    status = call('GET', '/api/ai/quota').json()
    assert status['global'] == {'limit': 3, 'used': 1, 'remaining': 2}
    assert status['actor']['remaining'] == 1
    assert status['resets_in_seconds'] > 0 and status['max_concurrency'] >= 1


def test_ledger_persists_across_process_restart(system, live_ai):
    """Rows live in the database, so a Render restart cannot reset the budget."""
    call, factory, _ = system
    live_ai.setenv('AI_DAILY_BUDGET', '5')
    call('POST', '/api/extract', data={'text': TEXT})
    with factory() as db:
        row = db.scalar(select(AiUsage))
        assert row is not None and row.status == 'ok' and row.day
    # A completely new engine/session sees the same ledger.
    from sqlalchemy.orm import sessionmaker
    from app.db import make_engine
    engine = make_engine(call.url)
    try:
        with sessionmaker(engine)() as db:
            assert db.scalar(select(func.count()).select_from(AiUsage)) == 1
    finally:
        engine.dispose()


def test_oversized_body_is_rejected_before_parsing(system, monkeypatch):
    call, _, client = system
    monkeypatch.setenv('MAX_REQUEST_BYTES', str(64 * 1024))
    payload = 'x' * (70 * 1024)
    response = client.post('/api/extract', content=payload, headers={
        'Authorization': 'Bearer ' + call.tokens['A'],
        'Content-Type': 'application/x-www-form-urlencoded',
    })
    assert response.status_code == 413
    assert 'MB' in response.json()['detail']


def test_oversized_body_rejected_even_without_token(system, monkeypatch):
    _, _, client = system
    monkeypatch.setenv('MAX_REQUEST_BYTES', str(64 * 1024))
    response = client.post('/api/extract', content='x' * (70 * 1024))
    assert response.status_code == 413


def test_no_default_daily_limit_beyond_old_demo_caps(system,live_ai):
    call,factory,_=system
    live_ai.delenv('AI_BUDGET_ENABLED',raising=False)
    for _ in range(24):
        response=call('POST','/api/extract',data={'text':TEXT})
        assert response.status_code==200,response.text
    data=call('GET','/api/ai/quota').json()
    assert data['enabled'] is False
    assert data['global']['limit'] is None and data['actor']['remaining'] is None
    assert usage_rows(factory)==24


def test_disabling_daily_limits_keeps_inflight_tracking(system,live_ai):
    call,factory,_=system
    live_ai.setenv('AI_BUDGET_ENABLED','false')
    with factory() as db:reservation=ai_budget.reserve(db,'assistant:A','assistant')
    response=call('POST','/api/extract',data={'text':TEXT})
    assert response.status_code==429 and '正在处理' in response.text
    with factory() as db:ai_budget.settle(db,reservation,'ok')
    assert call('POST','/api/extract',data={'text':TEXT}).status_code==200


@pytest.mark.parametrize('kind',['qq','assistant'])
def test_interrupted_bounded_request_is_reclaimed_without_disabling_guard(system,monkeypatch,kind):
    monkeypatch.setenv('AI_BUDGET_ENABLED','false');monkeypatch.setenv('AI_MAX_CONCURRENCY','1')
    clock=['2026-11-03T10:00:00+08:00'];monkeypatch.setattr(ai_budget,'now',lambda:clock[0])
    with system[1]() as db:
        abandoned=ai_budget.reserve(db,'qq:A',kind)
        clock[0]='2026-11-03T10:01:00+08:00'
        with pytest.raises(__import__('fastapi').HTTPException):ai_budget.reserve(db,'new','qq')
        clock[0]='2026-11-03T10:01:31+08:00'
        assert ai_budget.status(db,'new')['inflight']==0
        assert db.get(AiUsage,abandoned,populate_existing=True).status=='reserved'  # GET is read-only.
        replacement=ai_budget.reserve(db,'new','qq')
        assert replacement!=abandoned
        assert db.get(AiUsage,abandoned,populate_existing=True).status=='cancelled'
        assert ai_budget.status(db,'new')['inflight']==1


def test_active_reservation_across_midnight_still_occupies_slot(system,monkeypatch):
    monkeypatch.setenv('AI_BUDGET_ENABLED','false');monkeypatch.setenv('AI_MAX_CONCURRENCY','1')
    clock=['2026-11-03T23:59:50+08:00'];monkeypatch.setattr(ai_budget,'now',lambda:clock[0])
    with system[1]() as db:
        ai_budget.reserve(db,'qq:A','qq');clock[0]='2026-11-04T00:00:05+08:00'
        assert ai_budget.status(db,'qq:A')['inflight']==1
        with pytest.raises(__import__('fastapi').HTTPException):ai_budget.reserve(db,'next','qq')


def test_cancelled_assistant_releases_shared_ai_slot(system,monkeypatch):
    import asyncio
    from app import assistant
    from app.models import User
    monkeypatch.setenv('AI_BUDGET_ENABLED','false')
    class CancelledProvider:
        async def understand(self,*_):raise asyncio.CancelledError()
    monkeypatch.setattr(assistant,'provider',lambda:CancelledProvider())
    with system[1]() as db:
        with pytest.raises(asyncio.CancelledError):asyncio.run(assistant.chat(db,db.get(User,'A'),assistant.ChatInput(message='今天有什么安排？')))
        assert db.scalar(select(AiUsage).order_by(AiUsage.id.desc())).status=='cancelled'
        assert ai_budget.status(db,'A')['inflight']==0


def test_assistant_reports_busy_slot_instead_of_model_failure(system,monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from app import assistant
    from app.models import User
    monkeypatch.setenv('AI_BUDGET_ENABLED','false');monkeypatch.setenv('AI_MAX_CONCURRENCY','1')
    class NeverCalledProvider:
        async def understand(self,*_):raise AssertionError('No call while another request is active')
    monkeypatch.setattr(assistant,'provider',lambda:NeverCalledProvider())
    with system[1]() as db:
        ai_budget.reserve(db,'other','qq')
        with pytest.raises(HTTPException) as failure:asyncio.run(assistant.chat(db,db.get(User,'A'),assistant.ChatInput(message='今天有什么安排？')))
        assert failure.value.status_code==429 and '正在处理' in failure.value.detail
