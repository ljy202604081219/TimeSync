"""B3: readiness probe and a static audit of the deployment configuration.

These checks cannot prove a container boots (that needs Docker). They do guarantee
that the files agree with the documented contract: single worker, PORT expanded,
secrets ignored, health check path correct, no placeholder values left behind.
"""
import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy.orm import sessionmaker

from app import main as app_main
from app.db import Base, make_engine
from app.migrations import ensure_schema, expected_version

ROOT = Path(__file__).resolve().parents[2]


def read(name):
    return (ROOT / name).read_text(encoding='utf8')


def test_readiness_ok_after_migrations(tmp_path, monkeypatch):
    engine = make_engine('sqlite:///' + str(tmp_path / 'ready.db'))
    ensure_schema(engine)
    monkeypatch.setattr(app_main, 'engine', engine)
    from fastapi.testclient import TestClient
    client = TestClient(app_main.app)
    try:
        response = client.get('/api/ready')
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['status'] == 'ok'
        assert body['schema_version'] == expected_version()
        assert body['database']['backend'] == 'sqlite'
        assert 'password' not in response.text and 'sqlite:///' not in response.text
    finally:
        engine.dispose()


def test_readiness_reports_behind_without_migrations(tmp_path, monkeypatch):
    engine = make_engine('sqlite:///' + str(tmp_path / 'behind.db'))
    Base.metadata.create_all(engine)  # tables exist, but no schema_migrations
    monkeypatch.setattr(app_main, 'engine', engine)
    from fastapi.testclient import TestClient
    client = TestClient(app_main.app)
    try:
        response = client.get('/api/ready')
        assert response.status_code == 503
        assert response.json()['status'] == 'behind'
        assert 'python -m app.migrate' in response.json()['next']
    finally:
        engine.dispose()


def test_readiness_hides_database_errors(monkeypatch):
    class Broken:
        def connect(self):
            raise RuntimeError('could not connect to postgresql://user:secret@host/db')

    monkeypatch.setattr(app_main, 'engine', Broken())
    from fastapi.testclient import TestClient
    client = TestClient(app_main.app)
    response = client.get('/api/ready')
    assert response.status_code == 503
    assert 'secret' not in response.text and 'postgresql://' not in response.text


def test_health_does_not_touch_the_database(monkeypatch):
    class Broken:
        def connect(self):
            raise AssertionError('health must not open a database connection')

    monkeypatch.setattr(app_main, 'engine', Broken())
    from fastapi.testclient import TestClient
    assert TestClient(app_main.app).get('/api/health').status_code == 200


def test_dockerfile_is_multi_stage_and_unprivileged():
    text = read('Dockerfile')
    assert 'FROM node:22-bookworm-slim AS web' in text
    assert 'FROM python:3.12-slim AS runtime' in text
    assert 'pnpm install --frozen-lockfile' in text
    assert 'COPY --from=web /src/frontend/dist ./frontend/dist' in text
    assert 'USER timesync' in text
    assert 'HEALTHCHECK' in text and '/api/health' in text
    assert 'ENTRYPOINT ["/bin/sh", "/app/docker/start.sh"]' in text
    from_lines = [line for line in text.splitlines() if line.strip().upper().startswith('FROM ')]
    assert not any('alpine' in line.lower() for line in from_lines)
    assert '--workers 2' not in text and '--workers 4' not in text


def test_start_script_expands_port_and_runs_single_worker():
    text = read('docker/start.sh')
    assert '${PORT:=8000}' in text
    assert '--host 0.0.0.0' in text
    assert '--port "$PORT"' in text
    assert '--workers "$WEB_CONCURRENCY"' in text
    assert '127.0.0.1' not in text
    assert 'python -m app.migrate' in text


def test_dockerignore_keeps_secrets_and_data_out():
    patterns = {line.strip() for line in read('.dockerignore').splitlines() if line.strip() and not line.startswith('#')}
    for required in ('.env', '.venv', '*.db', '.demo-tokens.json', 'frontend/node_modules', '**/__pycache__'):
        assert required in patterns, required


def test_render_blueprint_has_no_literal_secrets():
    blueprint = yaml.safe_load(read('render.yaml'))
    service = blueprint['services'][0]
    assert service['type'] == 'web' and service['runtime'] == 'docker'
    assert service['plan'] == 'free'
    assert service['healthCheckPath'] == '/api/health'
    assert service['dockerfilePath'] == './Dockerfile'

    env = {item['key']: item for item in service['envVars']}
    assert env['DATABASE_URL'].get('sync') is False
    assert env['AI_API_KEY'].get('sync') is False
    assert env['ADMIN_TOKEN'].get('generateValue') is True
    assert env['DEMO_MODE']['value'] == 'false'
    assert env['LEGACY_TOKEN_AUTH']['value'] == 'false'
    assert env['SANDBOX_MODE']['value'] == 'true'
    assert env['WEB_CONCURRENCY']['value'] == '1'
    # Every literal value must be a flag, a number or a public URL.
    for key, item in env.items():
        if 'value' in item:
            assert re.fullmatch(r'[A-Za-z0-9_./:\-+=*]*', str(item['value'])), (key, item['value'])


def test_env_template_documents_every_flag_the_code_reads():
    template = read('.env.example')
    names = set()
    for source in (ROOT / 'backend' / 'app').glob('*.py'):
        text = source.read_text(encoding='utf8')
        names |= set(re.findall(r"os\.getenv\('([A-Z0-9_]+)'", text))
        names |= set(re.findall(r"(?:flag|number|text)\('([A-Z0-9_]+)'", text))
    documented = {line.split('=', 1)[0].strip() for line in template.splitlines() if '=' in line and not line.strip().startswith('#')}
    missing = sorted(name for name in names if name not in documented and name != 'PYTHONUNBUFFERED')
    assert not missing, f'undocumented environment variables: {missing}'


def test_env_template_contains_no_real_secret():
    template = read('.env.example')
    for line in template.splitlines():
        if line.startswith('#'):
            continue
        key, _, value = line.partition('=')
        if key in ('ADMIN_TOKEN', 'AI_API_KEY'):
            assert value == '', f'{key} must ship empty'
        assert not re.match(r'^(sk|pk|ghp)_', value), line


def test_pnpm_workspace_placeholder_is_resolved():
    text = read('frontend/pnpm-workspace.yaml')
    assert 'set this to true or false' not in text
    assert 'onlyBuiltDependencies' in text


def test_requirements_pin_the_verified_stack():
    text = read('backend/requirements.txt')
    for expected in ('fastapi==0.162.0', 'starlette==0.52.1', 'SQLAlchemy==2.0.55', 'psycopg[binary]==3.3.6'):
        assert expected in text, expected
    assert '0.119.1' not in text


def test_compose_file_targets_a_throwaway_database():
    text = read('docker-compose.yml')
    assert 'postgres:17-alpine' in text
    assert 'TIMESYNC_TEST_DATABASE_URL' in text
    assert 'timesync-pg' in text
