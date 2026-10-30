import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv(Path(__file__).resolve().parents[2] / '.env')
class Base(DeclarativeBase):
    pass

def make_engine(url):
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {})
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def configure(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('PRAGMA journal_mode=WAL')
    return engine

engine = make_engine(os.getenv('DATABASE_URL', 'sqlite:///./timesync.db'))
SessionLocal = sessionmaker(engine, expire_on_commit=False)
def session():
    with SessionLocal() as db:
        yield db
