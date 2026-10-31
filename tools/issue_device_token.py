"""Issue a real device token against the deployed TimeSync service.

Usage:
    python tools/issue_device_token.py [--label ljy-main-device]

Requires in .env.deploy:
    TIMESYNC_BASE_URL=https://<service>.onrender.com
    ADMIN_TOKEN=<platform-generated admin token>

The token value is written to .pytest-tmp/device-token.txt and is never printed
to stdout in full.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / '.env.deploy'
OUT_FILE = ROOT / '.pytest-tmp' / 'device-token.txt'


def load_env() -> dict:
    values = {}
    for line in ENV_FILE.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def call(base: str, method: str, path: str, headers: dict, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        base.rstrip('/') + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main() -> int:
    label = 'ljy-main-device'
    if '--label' in sys.argv:
        label = sys.argv[sys.argv.index('--label') + 1]

    values = load_env()
    base = values.get('TIMESYNC_BASE_URL', '')
    admin = values.get('ADMIN_TOKEN', '')
    if not base.startswith('https://'):
        print('TIMESYNC_BASE_URL is missing or not https in .env.deploy')
        return 2
    if not admin:
        print('ADMIN_TOKEN is missing in .env.deploy')
        return 2

    status, raw = call(
        base,
        'POST',
        '/api/admin/device-tokens',
        {
            'X-Admin-Token': admin,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        {'label': label},
    )
    if status != 200:
        print('issue_failed_status=' + str(status))
        print(raw[:300].decode('utf-8', 'ignore'))
        return 1

    body = json.loads(raw)
    token = body.get('token', '')
    if not token:
        print('issue_failed_no_token')
        return 1

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        'base_url=' + base.rstrip('/') + '\n'
        'label=' + str(body.get('label', label)) + '\n'
        'device_id=' + str(body.get('id', '')) + '\n'
        'expires_at=' + str(body.get('expires_at', '')) + '\n'
        'token=' + token + '\n',
        encoding='utf-8',
    )
    try:
        OUT_FILE.chmod(0o600)
    except OSError:
        pass

    masked = token[:6] + '...' + token[-4:] if len(token) > 12 else '***'
    print('device_token_issued=true')
    print('device_id=' + str(body.get('id', '')))
    print('label=' + str(body.get('label', label)))
    print('expires_at=' + str(body.get('expires_at', '')))
    print('token_preview=' + masked)
    print('token_file=' + str(OUT_FILE))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
