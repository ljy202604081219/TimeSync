"""Run from backend: python -m app.seed_demo [--reset]. Stop the server first."""
import argparse
import json
import shutil
import sqlite3
from pathlib import Path
from datetime import datetime
from .db import Base,engine,SessionLocal
from .main import TOKEN_FILE
from .demo import seed

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset',action='store_true',help='Back up the SQLite demo DB and replace its synthetic data')
    args=parser.parse_args()
    if args.reset:
        database=engine.url.database
        if not database or not str(engine.url).startswith('sqlite'): raise SystemExit('Reset supports the local SQLite demo only.')
        if Path(database).exists():
            backup=Path(database).with_name('timesync.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db')
            with sqlite3.connect(database) as source,sqlite3.connect(backup) as target: source.backup(target)
            if TOKEN_FILE.exists(): shutil.copy(TOKEN_FILE,backup.with_suffix('.tokens.json'))
            print('Backup:',backup.resolve())
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        tokens=seed(db)
        if tokens: TOKEN_FILE.write_text(json.dumps(tokens),encoding='utf8')
    print('Demo data initialized.' if tokens else 'Existing data preserved. Use --reset only for the synthetic demo.')

if __name__=='__main__': main()
