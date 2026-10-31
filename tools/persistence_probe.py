"""Persistence probe against a real PostgreSQL server, phase by phase.

    phase=setup   create a sandbox session, a device credential and one task;
                  store the secrets in files under %TEMP% (never printed)
    phase=verify  after the server process was killed and restarted, prove all
                  three still authenticate and the task is still there

    set TIMESYNC_BASE_URL=http://127.0.0.1:8125
    set ADMIN_TOKEN=...
    set TIMESYNC_PG_DSN=postgresql+psycopg://postgres@127.0.0.1:55432/timesync_smoke
    python tools/persistence_probe.py setup|verify
"""
import json
import os
import pathlib
import sys
import tempfile
import urllib.error
import urllib.request

BASE = os.getenv('TIMESYNC_BASE_URL', 'http://127.0.0.1:8125').rstrip('/')
ADMIN = os.getenv('ADMIN_TOKEN', '')
STORE = pathlib.Path(tempfile.gettempdir()) / 'timesync-persistence-probe.json'
RANGE = 'start=2026-11-04T00:00:00%2B08:00&end=2026-11-05T00:00:00%2B08:00'
PHASE = sys.argv[1] if len(sys.argv) > 1 else 'setup'


def call(method, path, headers=None, body=None):
    request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def agenda(token):
    return call('GET', f'/api/v1/agenda?{RANGE}', {'Authorization': 'Bearer ' + token})[0]


if PHASE == 'setup':
    _, raw = call('POST', '/api/sandbox/sessions', {'Content-Type': 'application/json'},
                  json.dumps({'member': 'B'}).encode())
    session = json.loads(raw)['token']
    _, raw = call('POST', '/api/admin/device-tokens',
                  {'X-Admin-Token': ADMIN, 'Content-Type': 'application/json'},
                  json.dumps({'owner_id': 'B', 'label': 'persist-probe', 'ttl_days': 7}).encode())
    device = json.loads(raw)['token']
    code, raw = call('POST', '/api/tasks',
                     {'Authorization': 'Bearer ' + session, 'Idempotency-Key': 'persist-probe-1',
                      'Content-Type': 'application/json'},
                     json.dumps({'title': '持久化探针任务', 'deadline': '2026-11-06T18:00:00+08:00',
                                 'duration_minutes': 45}).encode())
    assert code == 200, raw
    STORE.write_text(json.dumps({'session': session, 'device': device}), encoding='utf-8')
    print('setup ok: session + device issued, task created; secrets kept in', STORE.name)
    print('agenda with session:', agenda(session), '| agenda with device:', agenda(device))
elif PHASE == 'verify':
    kept = json.loads(STORE.read_text(encoding='utf-8'))
    session_code, device_code = agenda(kept['session']), agenda(kept['device'])
    print('after restart -> agenda with old session:', session_code,
          '| with old device:', device_code)
    state_code, raw = call('GET', '/api/users/B/state', {'Authorization': 'Bearer ' + kept['session']})
    tasks = [t for t in json.loads(raw)['tasks'] if t['title'] == '持久化探针任务'] if state_code == 200 else []
    print('state readable:', state_code, '| probe task survived:', bool(tasks))
    STORE.unlink(missing_ok=True)
    assert session_code == 200 and device_code == 200 and tasks, 'persistence check FAILED'
    print('PERSISTENCE OK: credentials and business data survived the restart')
else:
    raise SystemExit('phase must be setup or verify')
