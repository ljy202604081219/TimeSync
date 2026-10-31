"""Database engine, pooling and backend-neutral write transactions.

SQLite stays the zero-configuration local path; PostgreSQL (Neon/Render) is the
cloud path. Nothing here may assume one backend's locking or transaction rules:
SQLite keeps ``BEGIN IMMEDIATE`` plus the in-process write lock, PostgreSQL uses
one transaction-scoped advisory lock for *all* business writes.

Why one global key instead of a per-user key: business invariants are not
owner-scoped. Two members confirming the same meeting take two different
idempotency keys, so a per-key lock let both transactions read "the other
member is still pending" and commit, leaving every invitation accepted while
the meeting itself stayed ``pending``. The first release therefore serialises
all business mutations behind ``pg_advisory_xact_lock(BUSINESS_LOCK_KEY)``.
The cost is that CP-SAT planning inside a mutation blocks other writers for the
duration of that transaction; with four demo users this is acceptable and it is
documented in docs/backend-03-handoff.md as the scaling limit.

Environment (all optional, see .env.example):
  DATABASE_URL        sqlite:///./timesync.db | postgresql+psycopg://user:pass@host/db
  DB_SSLMODE          appended to a PostgreSQL URL when it is not already given
  DB_POOL_SIZE        PostgreSQL pool size, default 5
  DB_MAX_OVERFLOW     PostgreSQL pool overflow, default 5
  DB_POOL_TIMEOUT     seconds to wait for a pool slot, default 30
  DB_POOL_RECYCLE     recycle pooled connections after N seconds, default 1800
  DB_CONNECT_TIMEOUT  connect timeout in seconds, default 10
  DB_LOCK_TIMEOUT_MS  how long a writer waits for the business write lock
                      before giving up with a retryable 503, default 15000
"""
import os
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / '.env')

DEFAULT_SQLITE_URL = 'sqlite:///./timesync.db'
# Serializes local SQLite writers. On PostgreSQL the database itself serializes;
# this lock is kept because the first release runs a single uvicorn worker.
WRITE_LOCK = RLock()
# int64 constant ("TSNC"). One lock for the whole business-write domain, see the
# module docstring. Changing this value is a breaking change for rolling
# deployments: old and new workers would stop excluding each other.
BUSINESS_LOCK_KEY = 0x54534E43


class BusinessLockTimeout(RuntimeError):
    """The business write lock could not be taken in time. Retryable (503)."""


class Base(DeclarativeBase):
    pass


def env_int(name, default, minimum=0):
    try:
        return max(minimum, int(str(os.getenv(name, '')).strip()))
    except ValueError:
        return default


def normalize_url(url):
    """Accept the URLs hosting panels hand out and pin one PostgreSQL driver."""
    url = (url or '').strip() or DEFAULT_SQLITE_URL
    for prefix in ('postgres://', 'postgresql://', 'postgresql+psycopg2://'):
        if url.startswith(prefix):
            url = 'postgresql+psycopg://' + url[len(prefix):]
            break
    sslmode = os.getenv('DB_SSLMODE', '').strip()
    if backend_of(url) == 'postgresql' and sslmode and 'sslmode=' not in url:
        url += ('&' if '?' in url else '?') + 'sslmode=' + sslmode
    return url


def backend_of(url):
    url = str(url)
    if url.startswith('sqlite'):
        return 'sqlite'
    if url.startswith('postgresql'):
        return 'postgresql'
    return 'other'


def make_engine(url, **overrides):
    url = normalize_url(url)
    backend = backend_of(url)
    kwargs = dict(overrides)
    if backend == 'sqlite':
        kwargs.setdefault('connect_args', {'check_same_thread': False, 'timeout': 30})
    elif backend == 'postgresql':
        connect_args = {
            'connect_timeout': env_int('DB_CONNECT_TIMEOUT', 10, 1),
            'application_name': 'timesync',
        }
        connect_args.update(kwargs.pop('connect_args', {}))
        kwargs.setdefault('connect_args', connect_args)
        # Managed PostgreSQL drops idle connections; pre-ping turns that into a
        # transparent reconnect instead of an error on the first request after idle.
        kwargs.setdefault('pool_pre_ping', True)
        kwargs.setdefault('pool_size', env_int('DB_POOL_SIZE', 5, 1))
        kwargs.setdefault('max_overflow', env_int('DB_MAX_OVERFLOW', 5, 0))
        kwargs.setdefault('pool_timeout', env_int('DB_POOL_TIMEOUT', 30, 1))
        kwargs.setdefault('pool_recycle', env_int('DB_POOL_RECYCLE', 1800, 60))
    engine = create_engine(url, **kwargs)
    if backend == 'sqlite':
        @event.listens_for(engine, 'connect')
        def configure(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA journal_mode=WAL')
    return engine


engine = make_engine(os.getenv('DATABASE_URL', DEFAULT_SQLITE_URL))
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def session():
    with SessionLocal() as db:
        yield db


def lock_timeout_ms():
    return env_int('DB_LOCK_TIMEOUT_MS', 15000, 500)


def _acquire_postgres_business_lock(db):
    """Take the one transaction-scoped business lock, bounded by a timeout.

    ``pg_advisory_xact_lock`` is released by the commit or rollback that ends the
    surrounding transaction, so a crash cannot leak it. ``lock_timeout`` keeps a
    stuck writer from blocking the whole API for the rest of the request.
    """
    timeout = lock_timeout_ms()
    # SET LOCAL does not accept bind parameters; ``timeout`` is an int from
    # env_int(), so formatting it cannot inject SQL.
    db.execute(text(f'SET LOCAL lock_timeout = {int(timeout)}'))
    try:
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': BUSINESS_LOCK_KEY})
    except OperationalError as error:
        # 55P03 lock_not_available, raised by lock_timeout.
        if 'lock_not_available' in str(error) or '55P03' in str(error) or 'lock timeout' in str(error).lower():
            raise BusinessLockTimeout('另一项修改正在进行，请稍后重试') from error
        raise


@contextmanager
def write_transaction(db, scope='business'):
    """Open the serialized business write transaction for one logical mutation.

    ``scope`` is only used for logging and for the SQLite trace: the lock itself
    is global, because business invariants (all invitations accepted => meeting
    confirmed) span several owners and therefore several idempotency keys.

    SQLite takes the process lock plus ``BEGIN IMMEDIATE``. PostgreSQL takes a
    transaction-scoped advisory lock before the first read, so a writer always
    observes every mutation that committed before it entered.
    """
    backend = backend_of(db.get_bind().url)
    db.rollback()  # end any implicit read transaction; it may hold a stale snapshot
    if backend == 'sqlite':
        with WRITE_LOCK:
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            try:
                yield db
            except BaseException:
                db.rollback()
                raise
        return
    if backend == 'postgresql':
        _acquire_postgres_business_lock(db)
    try:
        yield db
    except BaseException:
        db.rollback()
        raise


def schema_version(connection):
    """Highest applied migration, or 0 when the registry does not exist yet."""
    if not inspect(connection).has_table('schema_migrations'):
        return 0
    value = connection.execute(text('SELECT COALESCE(MAX(version),0) FROM schema_migrations')).scalar()
    return int(value or 0)


def describe(engine_):
    """Non-secret connection facts for /api/ready and support logs."""
    url = engine_.url
    backend = backend_of(url)
    info = {'backend': backend, 'driver': url.drivername, 'pool': type(engine_.pool).__name__}
    if backend == 'sqlite':
        info['database'] = Path(url.database).name if url.database else ':memory:'
    else:
        info['host'] = url.host
        info['database'] = url.database
    return info
