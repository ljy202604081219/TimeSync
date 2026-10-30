"""Apply or inspect versioned schema migrations.

Usage (run from ``backend/``):

    python -m app.migrate --status   # show applied/pending versions
    python -m app.migrate            # apply pending migrations
    python -m app.migrate --check    # exit 1 when something is pending

The command uses DATABASE_URL exactly like the API, prints no credentials, and
never deletes or rewrites existing rows.
"""
import argparse
import json
import sys

from .db import describe, engine
from .migrations import ensure_schema

TARGET_LABEL = 'schema_migrations'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--status', action='store_true', help='Only report versions, change nothing')
    parser.add_argument('--check', action='store_true', help='Exit 1 if the database is behind the code')
    args = parser.parse_args(argv)

    report = ensure_schema(engine, apply=not args.status)
    summary = {**report, 'connection': describe(engine)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.status:
        return 0
    if args.check and report['pending']:
        print('Database schema is behind the code; run "python -m app.migrate".', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
