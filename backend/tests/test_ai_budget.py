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
