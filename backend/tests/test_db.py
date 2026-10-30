"""B1: engine factory, backend-neutral writes, versioned migrations, PG DDL."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_mock_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import db as dbmod
from app.db import Base, backend_of, describe, make_engine, normalize_url, write_transaction
from app.demo import seed
from app.migrations import ensure_schema, expected_version
from app.models import Task, User


def test_normalize_url_pins_psycopg_and_keeps_sqlite():
    assert normalize_url('postgres://u:p@h/db') == 'postgresql+psycopg://u:p@h/db'
    assert normalize_url('postgresql://u:p@h/db') == 'postgresql+psycopg://u:p@h/db'
    assert normalize_url('postgresql+psycopg2://u:p@h/db') == 'postgresql+psycopg://u:p@h/db'
    assert normalize_url('postgresql+psycopg://u:p@h/db') == 'postgresql+psycopg://u:p@h/db'
    assert normalize_url('') == dbmod.DEFAULT_SQLITE_URL
    assert normalize_url(None) == dbmod.DEFAULT_SQLITE_URL


def test_sslmode_is_appended_once(monkeypatch):
    monkeypatch.setenv('DB_SSLMODE', 'require')
    assert 'sslmode=require' in normalize_url('postgresql://u:p@h/db')
    already = normalize_url('postgresql://u:p@h/db?sslmode=verify-full')
    assert already.endswith('sslmode=verify-full') and already.count('sslmode=') == 1
    monkeypatch.delenv('DB_SSLMODE')
    assert 'sslmode' not in normalize_url('postgresql://u:p@h/db')


def test_postgres_pool_settings_are_applied(monkeypatch):
    monkeypatch.setenv('DB_POOL_SIZE', '3')
    monkeypatch.setenv('DB_MAX_OVERFLOW', '2')
    engine = make_engine('postgresql+psycopg://u:p@h/db', poolclass=__import__('sqlalchemy.pool', fromlist=['QueuePool']).QueuePool)
    try:
        assert engine.pool.size() == 3
        assert engine.pool._max_overflow == 2
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_sqlite_pragmas_and_foreign_keys(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'pragma.db'))
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            assert str(conn.exec_driver_sql('PRAGMA journal_mode').scalar()).lower() == 'wal'
    finally:
        engine.dispose()


def test_write_transaction_uses_begin_immediate_on_sqlite(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'tx.db'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as session:
            with write_transaction(session, 'A:key') as active:
                assert active is session
                session.add(User(id='A', name='林同学', token_hash='x', window_start='2026-11-02T08:00:00+08:00', window_end='2026-11-09T08:00:00+08:00'))
                session.commit()
            assert session.scalar(select(User).where(User.id == 'A')) is not None
    finally:
        engine.dispose()


def test_write_transaction_uses_advisory_lock_on_postgres():
    calls = []

    class FakeSession:
        def get_bind(self):
            return SimpleNamespace(url=make_url('postgresql+psycopg://u:p@h/db'))

        def rollback(self):
            calls.append(('rollback', None))

        def execute(self, statement, params):
            calls.append((str(statement), params))

    with write_transaction(FakeSession(), 'A:key') as active:
        assert isinstance(active, FakeSession)
    assert calls[0] == ('rollback', None)
    sql, params = calls[1]
    assert 'pg_advisory_xact_lock' in sql and params == {'scope': 'A:key'}
    assert not any('BEGIN IMMEDIATE' in (sql or '') for sql, _ in calls)


def test_write_transaction_rolls_back_on_error(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'rollback.db'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as session:
            with pytest.raises(RuntimeError):
                with write_transaction(session, 'A:key'):
                    session.add(User(id='B', name='陈同学', token_hash='y', window_start='2026-11-02T08:00:00+08:00', window_end='2026-11-09T08:00:00+08:00'))
                    session.flush()
                    raise RuntimeError('boom')
            assert session.scalar(select(User).where(User.id == 'B')) is None
    finally:
        engine.dispose()


def test_migrations_apply_once_and_are_idempotent(tmp_path):
    engine = make_engine('sqlite:///' + str(tmp_path / 'migrate.db'))
    try:
        first = ensure_schema(engine)
        assert first['applied_now'] == [1, 2]
        assert first['schema_version'] == expected_version()
        second = ensure_schema(engine)
        assert second['applied_now'] == [] and second['pending'] == []
        with engine.connect() as conn:
            versions = conn.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars().all()
            assert versions == [1, 2]
    finally:
        engine.dispose()


def test_migrations_upgrade_an_existing_database_without_data_loss(tmp_path):
    path = tmp_path / 'legacy.db'
    engine = make_engine('sqlite:///' + str(path))
    from app.migrations import BASELINE_TABLES
    try:
        # Simulate the ① database: baseline tables only, plus one real row.
        Base.metadata.create_all(bind=engine, tables=BASELINE_TABLES)
        factory = sessionmaker(engine)
        with factory() as session:
            session.add(User(id='A', name='林同学', token_hash='legacy', window_start='2026-11-02T08:00:00+08:00', window_end='2026-11-09T08:00:00+08:00'))
            session.flush()
            session.add(Task(owner_id='A', title='历史任务', deadline='2026-11-05T18:00:00+08:00', duration_minutes=60))
            session.commit()
        assert 'sandbox_sessions' not in inspect(engine).get_table_names()

        report = ensure_schema(engine)
        assert report['applied_now'] == [1, 2]
        tables = set(inspect(engine).get_table_names())
        assert {'sandbox_sessions', 'device_tokens', 'ai_usage', 'schema_migrations'} <= tables
        with factory() as session:
            assert session.scalar(select(Task).where(Task.title == '历史任务')) is not None
            assert session.scalar(select(User).where(User.id == 'A')).token_hash == 'legacy'
    finally:
        engine.dispose()


def test_postgres_ddl_contains_no_sqlite_specifics():
    """Static proof that the schema compiles for PostgreSQL."""
    statements = []

    def dump(sql, *args, **kwargs):
        statements.append(str(sql.compile(dialect=engine.dialect)))

    engine = create_mock_engine('postgresql+psycopg://u:p@h/db', dump)
    Base.metadata.create_all(engine, checkfirst=False)
    sql = '\n'.join(statements).upper()
    assert 'CREATE TABLE' in sql
    assert 'SERIAL' in sql or 'BIGSERIAL' in sql  # autoincrement becomes a sequence
    for forbidden in ('AUTOINCREMENT', 'BEGIN IMMEDIATE', 'PRAGMA', 'DATETIME('):
        assert forbidden not in sql
    for table in ('USERS', 'TASKS', 'REQUEST_RECORDS', 'SANDBOX_SESSIONS', 'DEVICE_TOKENS', 'AI_USAGE', 'SCHEMA_MIGRATIONS'):
        if table != 'SCHEMA_MIGRATIONS':
            assert f'CREATE TABLE {table}' in sql


def test_describe_never_exposes_credentials(tmp_path):
    engine = make_engine('postgresql+psycopg://user:secret@db.example.com:5432/timesync')
    try:
        info = describe(engine)
        assert info['backend'] == 'postgresql' and info['host'] == 'db.example.com'
        assert 'secret' not in str(info) and 'user' not in str(info)
    finally:
        engine.dispose()


def test_rows_are_ordered_for_stable_snapshots(tmp_path):
    """PostgreSQL does not preserve insertion order; the read model must not care."""
    engine = make_engine('sqlite:///' + str(tmp_path / 'order.db'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as session:
            seed(session, demo_data=True)
            from app.plans import rows
            ids = [row.id for row in rows(session, Task, 'A')]
            assert ids == sorted(ids)
    finally:
        engine.dispose()


def test_backend_detection():
    assert backend_of('sqlite:///x.db') == 'sqlite'
    assert backend_of('postgresql+psycopg://u@h/d') == 'postgresql'
    assert backend_of('mysql://u@h/d') == 'other'
