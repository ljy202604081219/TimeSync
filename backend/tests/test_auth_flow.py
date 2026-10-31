"""B4: the login closure the web UI depends on (contract: docs/contracts/auth-flow.md).

Covers discovery (``/api/auth/config``), login, logout, expiry, the machine
readable 401/403/429 codes, and the rule that an expired credential is rejected
before any ETag/304 decision can hide it.
"""
import pytest
from sqlalchemy import update

from app.models import DeviceToken, SandboxSession

ADMIN = 'test-admin-token-0123456789'
RANGE = {'start': '2026-11-04T00:00:00+08:00', 'end': '2026-11-05T00:00:00+08:00'}


def cloud(monkeypatch):
    """The deployed shape: no permanent demo tokens, sandbox login on."""
    monkeypatch.setenv('DEMO_MODE', 'false')
    monkeypatch.setenv('SANDBOX_MODE', 'true')
    monkeypatch.delenv('LEGACY_TOKEN_AUTH', raising=False)


def test_cloud_deployment_advertises_the_sandbox_flow(system, monkeypatch):
    _, _, client = system
    cloud(monkeypatch)
    found = client.get('/api/auth/config')
    assert found.status_code == 200
    body = found.json()
    assert body['sandbox_mode'] is True
    assert body['demo_mode'] is False and body['legacy_token_auth'] is False
    assert body['login_path'] == '/api/sandbox/sessions'
    assert body['logout_path'] == '/api/sandbox/session'
    assert body['session_ttl_minutes'] >= 5
    assert body['credential_header'] == 'Authorization: Bearer <token>'
    assert [m['id'] for m in body['members']] == ['A', 'B', 'C', 'D']
    assert set(body['members'][0]) == {'id', 'name'}
    # Discovery must never leak credentials or hashes: members carry id and name
    # only, and no value looks like an issued secret (43-char urlsafe token).
    assert 'token_hash' not in found.text
    assert all(set(m) == {'id', 'name'} for m in body['members'])
    # And the old entry point really is gone in this shape.
    assert client.get('/api/demo/accounts').status_code == 404


def test_local_launcher_advertises_the_demo_flow(system, monkeypatch):
    _, _, client = system
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.setenv('SANDBOX_MODE', 'false')
    body = client.get('/api/auth/config').json()
    assert body['demo_mode'] is True and body['sandbox_mode'] is False
    assert body['login_path'] is None
    assert len(body['members']) == 4


def test_login_walk_produces_a_usable_session_then_ends_it(system, monkeypatch):
    _, _, client = system
    cloud(monkeypatch)

    login = client.post('/api/sandbox/sessions', json={'member': 'C'})
    assert login.status_code == 200, login.text
    body = login.json()
    assert body['kind'] == 'session' and body['user'] == {'id': 'C', 'name': '王同学'}
    assert body['expires_in_seconds'] == body['expires_in_seconds'] > 0
    headers = {'Authorization': 'Bearer ' + body['token']}

    who = client.get('/api/sandbox/session', headers=headers)
    assert who.status_code == 200 and who.json()['remaining_minutes'] > 0
    assert client.get('/api/me', headers=headers).json()['credential'] == 'session'

    assert client.delete('/api/sandbox/session', headers=headers).status_code == 200
    after = client.get('/api/v1/agenda', params=RANGE, headers=headers)
    assert after.status_code == 401
    assert after.json()['code'] == 'session_revoked'
    assert after.headers['www-authenticate'] == 'Bearer'


def test_missing_and_unknown_credentials_have_distinct_codes(system):
    _, _, client = system
    missing = client.get('/api/v1/agenda', params=RANGE)
    assert missing.status_code == 401 and missing.json()['code'] == 'auth_missing'
    assert missing.headers['www-authenticate'] == 'Bearer'

    unknown = client.get('/api/v1/agenda', params=RANGE, headers={'Authorization': 'Bearer nope'})
    assert unknown.status_code == 401 and unknown.json()['code'] == 'auth_invalid'

    wrong_scheme = client.get('/api/v1/agenda', params=RANGE, headers={'Authorization': 'Basic abc'})
    assert wrong_scheme.status_code == 401 and wrong_scheme.json()['code'] == 'auth_missing'


def test_expired_session_reports_session_expired(system, monkeypatch):
    _, factory, client = system
    cloud(monkeypatch)
    token = client.post('/api/sandbox/sessions', json={'member': 'A'}).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    with factory() as db:
        db.execute(update(SandboxSession).values(expires_at='2020-01-01T00:00:00+08:00'))
        db.commit()
    expired = client.get('/api/v1/agenda', params=RANGE, headers=headers)
    assert expired.status_code == 401 and expired.json()['code'] == 'session_expired'
    # Logging out an already-expired session must not 500.
    assert client.delete('/api/sandbox/session', headers=headers).status_code == 401


def test_expired_device_credential_is_rejected_before_any_304(system, monkeypatch):
    """A cached device must not keep a 304 alive after its credential died."""
    call, factory, client = system
    monkeypatch.setenv('ADMIN_TOKEN', ADMIN)
    issued = client.post('/api/admin/device-tokens', json={'owner_id': 'A'},
                         headers={'X-Admin-Token': ADMIN}).json()
    device = {'Authorization': 'Bearer ' + issued['token']}
    first = client.get('/api/v1/agenda', params=RANGE, headers=device)
    assert first.status_code == 200
    cached = client.get('/api/v1/agenda', params=RANGE,
                        headers={**device, 'If-None-Match': first.headers['etag']})
    assert cached.status_code == 304

    with factory() as db:
        db.execute(update(DeviceToken).values(expires_at='2020-01-01T00:00:00+08:00'))
        db.commit()
    stale = client.get('/api/v1/agenda', params=RANGE,
                       headers={**device, 'If-None-Match': first.headers['etag']})
    assert stale.status_code == 401 and stale.json()['code'] == 'device_expired'


def test_device_credential_is_refused_on_writes_with_a_typed_code(system, monkeypatch):
    _, _, client = system
    monkeypatch.setenv('ADMIN_TOKEN', ADMIN)
    issued = client.post('/api/admin/device-tokens', json={'owner_id': 'A'},
                         headers={'X-Admin-Token': ADMIN}).json()
    device = {'Authorization': 'Bearer ' + issued['token'], 'Idempotency-Key': 'device-write'}
    refused = client.post('/api/tasks', headers=device,
                          json={'title': '设备写入', 'deadline': '2026-11-06T18:00:00+08:00',
                                'duration_minutes': 60})
    assert refused.status_code == 403 and refused.json()['code'] == 'device_forbidden'


def test_sandbox_disabled_is_typed_too(system, monkeypatch):
    _, _, client = system
    monkeypatch.setenv('SANDBOX_MODE', 'false')
    body = client.post('/api/sandbox/sessions', json={'member': 'A'})
    assert body.status_code == 404 and body.json()['code'] == 'sandbox_disabled'


def test_sandbox_capacity_limit_is_429_with_retry_after(system, monkeypatch):
    _, _, client = system
    monkeypatch.setenv('SANDBOX_MODE', 'true')
    monkeypatch.setenv('SANDBOX_MAX_ACTIVE_SESSIONS', '1')
    assert client.post('/api/sandbox/sessions', json={'member': 'A'}).status_code == 200
    full = client.post('/api/sandbox/sessions', json={'member': 'B'})
    assert full.status_code == 429
    assert full.json()['code'] == 'sandbox_full' and full.headers['retry-after'] == '30'


@pytest.mark.parametrize('path', ['/api/v1/agenda'])
def test_error_envelope_keeps_detail_for_existing_clients(system, path):
    _, _, client = system
    body = client.get(path, params=RANGE if 'agenda' in path else None).json()
    assert isinstance(body['detail'], str) and body['detail']
    assert body['code'] == 'auth_missing'
