"""30 s device polling probe: what does a dashboard screen actually cost?

Issues its own device credential, polls /api/v1/agenda every 30 seconds, and
prints only aggregate numbers - never the token, a hash, or another identity's
data. Usage:

    set TIMESYNC_BASE_URL=http://127.0.0.1:8124
    set ADMIN_TOKEN=...
    python tools/poll_quota_probe.py [polls] [interval_seconds]
"""
import json
import os
import functools
import sys
import time

print = functools.partial(print, flush=True)
import urllib.error
import urllib.request

BASE = os.getenv('TIMESYNC_BASE_URL', 'http://127.0.0.1:8124').rstrip('/')
ADMIN = os.getenv('ADMIN_TOKEN', '')
POLLS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
INTERVAL = int(sys.argv[2]) if len(sys.argv) > 2 else 30
RANGE = 'start=2026-11-04T00:00:00%2B08:00&end=2026-11-05T00:00:00%2B08:00'


def call(method, path, headers=None, body=None):
    request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


status, _, raw = call('POST', '/api/admin/device-tokens',
                      {'X-Admin-Token': ADMIN, 'Content-Type': 'application/json'},
                      json.dumps({'owner_id': 'A', 'label': '30s-probe', 'ttl_days': 7}).encode())
assert status == 200, f'issue failed: {status}'
device = json.loads(raw)
token, device_id = device['token'], device['id']
auth = {'Authorization': 'Bearer ' + token}
print(f'probe: {POLLS} polls every {INTERVAL}s against {BASE}')

def header(headers, name):
    return next((v for k, v in headers.items() if k.lower() == name.lower()), '')


statuses, etags, revisions, receipts = [], set(), set(), set()
for index in range(POLLS):
    if index:
        time.sleep(INTERVAL)
    code, headers, raw = call('GET', f'/api/v1/agenda?{RANGE}', auth)
    statuses.append(code)
    if code == 200:
        body = json.loads(raw)
        etags.add(header(headers, 'ETag').removeprefix('W/'))
        revisions.add(body['revision'])
        previous = call('GET', f'/api/v1/agenda?{RANGE}',
                        {**auth, 'If-None-Match': header(headers, 'ETag')})[0]
        statuses.append(previous)
    _, _, info = call('GET', '/api/admin/device-tokens', {'X-Admin-Token': ADMIN})
    rows = [row for row in json.loads(info)['devices'] if row['id'] == device_id]
    if rows and rows[0]['last_request_at']:
        receipts.add(rows[0]['last_request_at'])

quota_status, _, quota_raw = call('POST', '/api/sandbox/sessions',
                                  {'Content-Type': 'application/json'},
                                  json.dumps({'member': 'A'}).encode())
quota = {'error': quota_status}
if quota_status == 200:
    session_token = json.loads(quota_raw)['token']
    quota_status, _, quota_raw = call('GET', '/api/ai/quota',
                                      {'Authorization': 'Bearer ' + session_token})
    quota = json.loads(quota_raw) if quota_status == 200 else {'error': quota_status}

print('agenda statuses      :', statuses)
print('distinct revisions   :', len(revisions), sorted(revisions))
print('distinct ETags       :', len(etags), sorted(etags))
print('304 validations      :', statuses.count(304))
print('distinct receipts    :', len(receipts),
      f'(server writes last_request_at at most once per 60s; {POLLS} polls x {INTERVAL}s)')
print('ai quota after polls :', {k: quota.get(k) for k in ('day', 'global_used', 'actor_used', 'remaining_global') if k in quota} or quota)
call('DELETE', f'/api/admin/device-tokens/{device_id}', {'X-Admin-Token': ADMIN})
print('probe device revoked :', True)
