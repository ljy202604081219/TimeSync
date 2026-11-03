import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, backend_of, make_engine, session
from app.demo import seed
from app.main import app


@pytest.fixture(autouse=True)
def legacy_assistant_confirmation(monkeypatch):
    # Keep legacy confirmation contracts under test; auto-create tests explicitly
    # remove this override to exercise the production default.
    monkeypatch.setenv('ASSISTANT_AUTO_CREATE','false')


def database_url(tmp_path):
    """PostgreSQL when TIMESYNC_TEST_DATABASE_URL is set, SQLite otherwise.

    The PostgreSQL run is destructive on purpose: it drops and recreates the
    project tables in the database you point it at. Never point it at a database
    that holds real data.
    """
    return os.getenv('TIMESYNC_TEST_DATABASE_URL', '').strip() or 'sqlite:///' + str(tmp_path / 'test.db')


@pytest.fixture
def system(tmp_path):
    url = database_url(tmp_path)
    engine = make_engine(url)
    if backend_of(url) == 'postgresql':
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        tokens = seed(db, demo_data=True)

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[session] = override
    client = TestClient(app)

    def call(method, path, member='A', key=None, **kwargs):
        headers = {'Authorization': 'Bearer ' + tokens[member], 'Idempotency-Key': key or str(uuid.uuid4())}
        return client.request(method, path, headers=headers, **kwargs)

    call.tokens = tokens
    call.url = url
    yield call, factory, client
    app.dependency_overrides.clear()
    if backend_of(url) == 'postgresql':
        Base.metadata.drop_all(engine)
    engine.dispose()
