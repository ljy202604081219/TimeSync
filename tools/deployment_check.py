"""Deployment acceptance check: run against the real HTTPS URL after deploy.

Prints a pass/fail line per check and a final verdict. Credentials are read
from the environment or created internally and never printed.

    set TIMESYNC_BASE_URL=https://timesync-xxxx.onrender.com
    set ADMIN_TOKEN=<the platform-generated admin token>
    python tools/deployment_check.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

RAW = os.getenv('TIMESYNC_BASE_URL', '').rstrip('/')
# A deployed address must be reached over TLS; a loopback rehearsal is plain http.
BASE = RAW if any(host in RAW for host in ('://127.0.0.1', '://localhost', '://[::1]')) \
    else RAW.replace('http://', 'https://')
ADMIN = os.getenv('ADMIN_TOKEN', '')
RANGE = 'start=2026-11-04T00:00:00%2B08:00&end=2026-11-05T00:00:00%2B08:00'
results = []


def call(method, path, headers=None, body=None):
    request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def header(headers, name):
    """HTTP/1.1 header names are case-insensitive; uvicorn sends them lowercase."""
    return next((value for key, value in headers.items() if key.lower() == name.lower()), '')


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(f'{"PASS" if ok else "FAIL"}  {name}  {detail}')


LOCAL = any(host in BASE for host in ('://127.0.0.1', '://localhost', '://[::1]'))
if not (BASE.startswith('https://') or LOCAL):
    raise SystemExit('TIMESYNC_BASE_URL must be the deployed https:// address '
                     '(http://127.0.0.1:8000 is accepted for a local rehearsal)')
if LOCAL:
    print('NOTE: local rehearsal; TLS, DNS and cold-start behaviour are not exercised.')
print('checking', BASE)

code, _, _ = call('GET', '/api/health')
check('health 200', code == 200, str(code))
code, _, raw = call('GET', '/api/ready')
check('ready 200 + schema v2', code == 200 and json.loads(raw).get('schema_version') == 2, str(code))
code, _, raw = call('GET', '/api/auth/config')
config = json.loads(raw) if code == 200 else {}
check('auth/config advertises sandbox', code == 200 and config.get('sandbox_mode') is True, str(code))
check('legacy demo entry closed', call('GET', '/api/demo/accounts')[0] == 404)

code, _, raw = call('POST', '/api/sandbox/sessions', {'Content-Type': 'application/json'},
                    json.dumps({'member': 'A'}).encode())
session = json.loads(raw).get('token', '') if code == 200 else ''
check('sandbox login 200', code == 200 and len(session) >= 40, str(code))
web_auth = {'Authorization': 'Bearer ' + session}
code, headers, raw = call('GET', f'/api/v1/agenda?{RANGE}', web_auth)
etag = header(headers, 'ETag')
check('web agenda 200 + ETag', code == 200 and etag.startswith('W/'), f'{code} {etag[:18]}...')
code, _, _ = call('GET', f'/api/v1/agenda?{RANGE}', {**web_auth, 'If-None-Match': etag})
check('304 on If-None-Match', code == 304, str(code))

code, _, raw = call('POST', '/api/admin/device-tokens',
                    {'X-Admin-Token': ADMIN, 'Content-Type': 'application/json'},
                    json.dumps({'owner_id': 'A', 'label': 'deploy-check', 'ttl_days': 7}).encode())
device = json.loads(raw) if code == 200 else {}
device_auth = {'Authorization': 'Bearer ' + device.get('token', '')}
code, d_headers, d_raw = call('GET', f'/api/v1/agenda?{RANGE}', device_auth)
check('device agenda 200, same ETag', code == 200 and header(d_headers, 'ETag') == etag, str(code))
code, _, _ = call('POST', '/api/tasks',
                  {**device_auth, 'Idempotency-Key': 'deploy-check-write', 'Content-Type': 'application/json'},
                  json.dumps({'title': '部署自检', 'deadline': '2026-11-06T18:00:00+08:00',
                              'duration_minutes': 60}).encode())
check('device write rejected 403', code == 403, str(code))

bad = call('GET', f'/api/v1/agenda?{RANGE}', {'Authorization': 'Bearer not-a-token'})[0]
check('unknown token 401', bad == 401, str(bad))
call('DELETE', f"/api/admin/device-tokens/{device.get('id', '')}", {'X-Admin-Token': ADMIN})
revoked = call('GET', f'/api/v1/agenda?{RANGE}', device_auth)[0]
check('revoked device 401 immediately', revoked == 401, str(revoked))
call('DELETE', '/api/sandbox/session', web_auth)
logged_out = call('GET', f'/api/v1/agenda?{RANGE}', web_auth)[0]
check('logged-out session 401 immediately', logged_out == 401, str(logged_out))

failed = [name for name, ok, _ in results if not ok]
print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
sys.exit(1 if failed else 0)
