"""B2: sandbox sessions, device credentials, scope limits and revocation."""
import pytest
from sqlalchemy import select, update

from app.models import DeviceToken, SandboxSession

ADMIN = 'test-admin-token-0123456789'
RANGE = {'start': '2026-11-04T00:00:00+08:00', 'end': '2026-11-05T00:00:00+08:00'}


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv('SANDBOX_MODE', 'true')
    return monkeypatch


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv('ADMIN_TOKEN', ADMIN)
    return {'X-Admin-Token': ADMIN}


def issue(client, admin_headers, owner='A', label='宿舍屏'):
    response = client.post('/api/admin/device-tokens', json={'owner_id': owner, 'label': label}, headers=admin_headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_sandbox_disabled_by_default(system):
    call, _, client = system
    assert client.post('/api/sandbox/sessions', json={'member': 'A'}).status_code == 404


def test_sandbox_session_grants_business_access_without_permanent_token(system, sandbox):
    _, _, client = system
    created = client.post('/api/sandbox/sessions', json={'member': 'A'})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body['user']['id'] == 'A' and body['expires_in_seconds'] > 0
    assert '共享演示沙箱' in body['notice']

    headers = {'Authorization': 'Bearer ' + body['token']}
    me = client.get('/api/me', headers=headers)
    assert me.status_code == 200 and me.json()['credential'] == 'session'
    assert client.get('/api/v1/agenda', params=RANGE, headers=headers).status_code == 200
    assert client.get('/api/sandbox/session', headers=headers).json()['remaining_minutes'] > 0
    assert client.post('/api/tasks', json={'title': '会话任务', 'deadline': '2026-11-06T18:00:00+08:00', 'duration_minutes': 60},
                       headers={**headers, 'Idempotency-Key': 'session-task'}).status_code == 200
    # A session may never configure the model endpoint.
    assert client.get('/api/ai/settings', headers=headers).status_code == 403


def test_sandbox_session_expiry_and_revocation(system, sandbox):
    _, factory, client = system
    token = client.post('/api/sandbox/sessions', json={'member': 'B'}).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    assert client.get('/api/v1/agenda', params=RANGE, headers=headers).status_code == 200

    with factory() as db:
        db.execute(update(SandboxSession).values(expires_at='2020-01-01T00:00:00+08:00'))
        db.commit()
    expired = client.get('/api/v1/agenda', params=RANGE, headers=headers)
    assert expired.status_code == 401 and '过期' in expired.json()['detail']

    fresh = client.post('/api/sandbox/sessions', json={'member': 'B'}).json()['token']
    fresh_headers = {'Authorization': 'Bearer ' + fresh}
    assert client.delete('/api/sandbox/session', headers=fresh_headers).json()['revoked']
    assert client.get('/api/v1/agenda', params=RANGE, headers=fresh_headers).status_code == 401


def test_permanent_tokens_stop_working_when_demo_login_is_off(system, monkeypatch):
    call, _, client = system
    monkeypatch.setenv('DEMO_MODE', 'false')
    monkeypatch.delenv('LEGACY_TOKEN_AUTH', raising=False)
    assert call('GET', '/api/me').status_code == 401
    assert client.get('/api/demo/accounts').status_code == 404


def test_admin_endpoint_requires_configured_and_correct_token(system, monkeypatch):
    _, _, client = system
    monkeypatch.delenv('ADMIN_TOKEN', raising=False)
    assert client.post('/api/admin/device-tokens', json={'owner_id': 'A'}).status_code == 503
    monkeypatch.setenv('ADMIN_TOKEN', 'short')
    assert client.post('/api/admin/device-tokens', json={'owner_id': 'A'}).status_code == 503
    monkeypatch.setenv('ADMIN_TOKEN', ADMIN)
    assert client.post('/api/admin/device-tokens', json={'owner_id': 'A'}).status_code == 403
    assert client.post('/api/admin/device-tokens', json={'owner_id': 'A'}, headers={'X-Admin-Token': 'wrong-token-0123456789'}).status_code == 403


def test_device_token_reads_agenda_only_same_etag(system, admin):
    call, factory, client = system
    issued = issue(client, admin, 'A')
    assert issued['scope'] == 'agenda:read' and issued['token'] not in str(issued.get('id'))
    device = {'Authorization': 'Bearer ' + issued['token'], 'If-None-Match': ''}

    web = call('GET', '/api/v1/agenda', params=RANGE)
    read = client.get('/api/v1/agenda', params=RANGE, headers=device)
    assert read.status_code == 200 and read.headers['etag'] == web.headers['etag']
    assert read.json()['user_id'] == 'A'
    assert read.json()['revision'] == web.json()['revision']

    cached = client.get('/api/v1/agenda', params=RANGE, headers={**device, 'If-None-Match': read.headers['etag']})
    assert cached.status_code == 304 and cached.content == b''
    # The device receipt must not change the content revision.
    assert web.json()['revision'] == read.json()['revision']

    with factory() as db:
        token = db.scalar(select(DeviceToken))
        assert token.last_request_at is not None
        assert token.token_hash != issued['token']

    for method, path, kwargs in [
        ('get', '/api/me', {}),
        ('get', '/api/users/A/state', {}),
        ('get', '/api/devices', {}),
        ('get', '/api/ai/quota', {}),
        ('get', '/api/ai/settings', {}),
    ]:
        assert getattr(client, method)(path, headers=device, **kwargs).status_code == 403, path
    assert client.post('/api/tasks', json={'title': '设备写入', 'deadline': '2026-11-06T18:00:00+08:00', 'duration_minutes': 60},
                       headers={**device, 'Idempotency-Key': 'device-write'}).status_code == 403
    assert client.post('/api/meetings', json={'title': '设备会议', 'start': '2026-11-04T14:00:00+08:00', 'end': '2026-11-04T15:00:00+08:00'},
                       headers={**device, 'Idempotency-Key': 'device-meeting'}).status_code == 403


def test_device_expiry_and_revocation_take_effect_immediately(system, admin):
    _, factory, client = system
    issued = issue(client, admin, 'A')
    headers = {'Authorization': 'Bearer ' + issued['token']}
    assert client.get('/api/v1/agenda', params=RANGE, headers=headers).status_code == 200

    assert client.delete(f"/api/admin/device-tokens/{issued['id']}", headers=admin).json()['revoked']
    revoked = client.get('/api/v1/agenda', params=RANGE, headers=headers)
    assert revoked.status_code == 401 and '撤销' in revoked.json()['detail']

    other = issue(client, admin, 'B', label='书房屏')
    assert client.get('/api/v1/agenda', params=RANGE, headers={'Authorization': 'Bearer ' + other['token']}).json()['user_id'] == 'B'
    with factory() as db:
        db.execute(update(DeviceToken).values(expires_at='2020-01-01T00:00:00+08:00'))
        db.commit()
    expired = client.get('/api/v1/agenda', params=RANGE, headers={'Authorization': 'Bearer ' + other['token']})
    assert expired.status_code == 401 and '过期' in expired.json()['detail']


def test_device_listing_is_owner_scoped_and_never_leaks_tokens(system, admin):
    call, _, client = system
    a = issue(client, admin, 'A', '宿舍屏')
    b = issue(client, admin, 'B', '实验室屏')

    listed = call('GET', '/api/devices')
    assert listed.status_code == 200
    devices = listed.json()['devices']
    assert [row['id'] for row in devices] == [a['id']]
    assert all(row['owner_id'] == 'A' for row in devices)
    assert a['token'] not in listed.text and 'token_hash' not in listed.text

    admin_view = client.get('/api/admin/device-tokens', headers=admin).json()['devices']
    assert {row['owner_id'] for row in admin_view} == {'A', 'B'}
    assert a['token'] not in str(admin_view) and b['token'] not in str(admin_view)

    revoked = client.delete(f"/api/admin/device-tokens/{b['id']}", headers=admin).json()
    assert revoked['status'] == 'revoked' and revoked['revoked_at']


def test_unknown_token_rejected(system):
    _, _, client = system
    assert client.get('/api/v1/agenda', params=RANGE, headers={'Authorization': 'Bearer not-a-real-token'}).status_code == 401
    assert client.get('/api/v1/agenda', params=RANGE, headers={'Authorization': 'Basic abc'}).status_code == 401
