"""Versioned, additive schema migrations for SQLite and PostgreSQL.

Rules this module deliberately follows:
  * Never call ``drop_all()`` and never rewrite data on start-up.
  * Every version is recorded in ``schema_migrations`` before the next one runs.
  * Creating tables is idempotent (``checkfirst``) so an existing local SQLite
    database simply gains the tables it is missing.
  * A version may only add tables, columns or indexes. Destructive changes need
    a new explicit migration plus a backup/rollback note in the handoff docs.
"""
from sqlalchemy import inspect, text

from .db import Base, schema_version
from .models import (
    AiUsage, Availability, BusyInterval, DeviceToken, Disruption, Meeting,
    MeetingInvitation, PlanVersion, RequestRecord, SandboxSession, ScheduledTask,
    Task, TimetableImport, User,
)

# The eleven tables delivered by ① before ③ touched the schema.
BASELINE_TABLES = [
    User.__table__, Task.__table__, BusyInterval.__table__, Availability.__table__,
    PlanVersion.__table__, ScheduledTask.__table__, Disruption.__table__,
    Meeting.__table__, MeetingInvitation.__table__, RequestRecord.__table__,
    TimetableImport.__table__,
]

# Added by ③ in B1/B2: browser sessions, device credentials, AI budget ledger.
IDENTITY_TABLES = [SandboxSession.__table__, DeviceToken.__table__, AiUsage.__table__]

MIGRATIONS = []


def migration(version, name):
    def register(apply):
        MIGRATIONS.append((version, name, apply))
        return apply
    return register


@migration(1, 'baseline business schema')
def baseline(connection):
    Base.metadata.create_all(bind=connection, tables=BASELINE_TABLES)


@migration(2, 'sandbox sessions, device tokens, ai budget ledger')
def identity(connection):
    Base.metadata.create_all(bind=connection, tables=IDENTITY_TABLES)


def expected_version():
    return max(version for version, _, _ in MIGRATIONS)


def applied_versions(connection):
    if not inspect(connection).has_table('schema_migrations'):
        return set()
    rows = connection.execute(text('SELECT version FROM schema_migrations')).scalars().all()
    return {int(row) for row in rows}


def pending_versions(connection):
    done = applied_versions(connection)
    return [version for version, _, _ in sorted(MIGRATIONS) if version not in done]


def ensure_schema(engine, apply=True):
    """Apply pending migrations (default) and return a small status dictionary."""
    with engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE IF NOT EXISTS schema_migrations ('
            'version INTEGER PRIMARY KEY, '
            'name VARCHAR(160) NOT NULL, '
            'applied_at VARCHAR(40) NOT NULL)'
        ))
        applied = []
        for version, name, apply_step in sorted(MIGRATIONS):
            if version in applied_versions(connection):
                continue
            if not apply:
                continue
            apply_step(connection)
            connection.execute(
                text('INSERT INTO schema_migrations(version,name,applied_at) VALUES (:v,:n,:t)'),
                {'v': version, 'n': name, 't': _stamp()},
            )
            applied.append(version)
        current = schema_version(connection)
        pending = pending_versions(connection)
    return {
        'schema_version': current,
        'expected_version': expected_version(),
        'applied_now': applied,
        'pending': pending,
    }


def _stamp():
    from .timeutil import now
    return now()
