"""Controlled initialisation for a cloud (or fresh) database.

Run from ``backend/`` with DATABASE_URL pointing at the target database:

    python -m app.bootstrap --status
    python -m app.bootstrap --fixtures                # this week's Monday as anchor
    python -m app.bootstrap --fixtures --anchor 2026-12-07
    python -m app.bootstrap --clear-sessions

What it does:
  * applies pending schema migrations (never drops tables);
  * creates the four synthetic identities A/B/C/D when they are missing, with a
    random token hash that is never printed - the cloud login path is a sandbox
    session or a device credential issued by an administrator;
  * optionally adds the synthetic course/task/plan fixtures for the demo week,
    skipping any identity that already has tasks.

It never imports the local ``.demo-tokens.json`` file and never writes secrets to
disk, so it is safe to run on a read-only container filesystem.
"""
import argparse
import json
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from .db import SessionLocal, describe, engine
from .demo import MEMBERS, fixtures, seed
from .migrations import ensure_schema
from .models import DeviceToken, SandboxSession, Task, User
from .timeutil import now


def current_monday():
    today = datetime.fromisoformat(now()).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def counts(db):
    return {
        'users': db.scalar(select(func.count()).select_from(User)) or 0,
        'tasks': db.scalar(select(func.count()).select_from(Task)) or 0,
        'sessions': db.scalar(select(func.count()).select_from(SandboxSession)) or 0,
        'device_tokens': db.scalar(select(func.count()).select_from(DeviceToken)) or 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fixtures', action='store_true', help='Add synthetic course/task/plan fixtures for the demo week')
    parser.add_argument('--anchor', help='Monday of the demo week (YYYY-MM-DD); defaults to the current week')
    parser.add_argument('--status', action='store_true', help='Report state only, write nothing')
    parser.add_argument('--clear-sessions', action='store_true', help='Revoke every sandbox session before a demo')
    args = parser.parse_args(argv)

    report = ensure_schema(engine, apply=not args.status)
    created_identities = []
    added_fixtures = []
    cleared = 0
    with SessionLocal() as db:
        if not args.status:
            if db.scalar(select(func.count()).select_from(User)) == 0:
                seed(db, demo_data=False, tokens=False)
                created_identities = [f'{member}:{MEMBERS[member]}' for member in 'ABCD']
            if args.clear_sessions:
                cleared = db.execute(delete(SandboxSession)).rowcount or 0
                db.commit()
            if args.fixtures:
                added_fixtures = fixtures(db, anchor=args.anchor or current_monday(), reset_window=True)
        snapshot = counts(db)

    summary = {
        'schema': report,
        'connection': describe(engine),
        'created_identities': created_identities,
        'fixtures_members': added_fixtures,
        'cleared_sessions': cleared,
        'counts': snapshot,
        'anchor': (args.anchor or current_monday()) if args.fixtures else None,
        'note': 'Synthetic data only. No token or key is printed or written by this command.',
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
