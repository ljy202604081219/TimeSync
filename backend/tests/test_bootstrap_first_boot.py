"""First-boot initialisation for an empty cloud database.

The free cloud tier has no shell, so a freshly migrated database must be able to
seed its own synthetic identities; and it must never re-seed over live data on a
restart or a redeploy.
"""
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app import bootstrap
from app.db import Base, backend_of, make_engine
from app.models import Task, User


@pytest.fixture
def factory(tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'first-boot.db')
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_empty_database_gets_identities_and_fixtures(factory, monkeypatch):
    monkeypatch.setattr(bootstrap, 'SessionLocal', factory)
    summary = bootstrap.initialise_if_empty(anchor='2026-11-02',with_fixtures=True)

    assert sorted(summary['created_identities']) == ['A:林同学', 'B:陈同学', 'C:王同学', 'D:许同学']
    assert sorted(summary['fixtures_members']) == ['A', 'B', 'C', 'D']
    assert summary['counts']['users'] == 4
    assert summary['counts']['tasks'] > 0

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 4
        # The demo week is anchored where the caller asked, not to a hard-coded date.
        starts = {task.deadline[:10] for task in db.scalars(select(Task))}
        assert any(day >= '2026-11-02' for day in starts), starts


def test_second_boot_changes_nothing(factory, monkeypatch):
    monkeypatch.setattr(bootstrap, 'SessionLocal', factory)
    bootstrap.initialise_if_empty(anchor='2026-11-02',with_fixtures=True)
    with factory() as db:
        before = (db.scalar(select(func.count()).select_from(User)),
                  db.scalar(select(func.count()).select_from(Task)))

    summary = bootstrap.initialise_if_empty(anchor='2026-12-07')
    assert summary['created_identities'] == []
    assert summary['fixtures_members'] == []
    with factory() as db:
        after = (db.scalar(select(func.count()).select_from(User)),
                 db.scalar(select(func.count()).select_from(Task)))
    assert after == before


def test_identities_without_fixtures(factory, monkeypatch):
    monkeypatch.setattr(bootstrap, 'SessionLocal', factory)
    summary = bootstrap.initialise_if_empty(anchor='2026-11-02', with_fixtures=False)
    assert len(summary['created_identities']) == 4
    assert summary['fixtures_members'] == []
    assert summary['counts']['tasks'] == 0


def test_bootstrap_is_off_by_default(monkeypatch):
    monkeypatch.delenv('BOOTSTRAP_FIXTURES', raising=False)
    from app import config
    assert config.bootstrap_fixtures() is False
    monkeypatch.setenv('BOOTSTRAP_FIXTURES', 'true')
    assert config.bootstrap_fixtures() is True
    assert config.bootstrap_anchor() == ''


def test_default_bootstrap_has_identities_only(factory,monkeypatch):
    monkeypatch.setattr(bootstrap,'SessionLocal',factory)
    result=bootstrap.initialise_if_empty()
    assert result['counts']['users']==4 and result['counts']['tasks']==0
    from app.models import BusyInterval,Availability,PlanVersion
    with factory() as db:
        for cls in (BusyInterval,Availability,PlanVersion):
            assert db.scalar(select(func.count()).select_from(cls))==0


def test_sandbox_lifespan_creates_login_members_without_schedule(factory,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(bootstrap,'SessionLocal',factory)
    monkeypatch.setenv('AUTO_MIGRATE','false');monkeypatch.setenv('DEMO_MODE','false')
    monkeypatch.setenv('SANDBOX_MODE','true');monkeypatch.setenv('BOOTSTRAP_FIXTURES','false')
    for _ in range(2):
        with TestClient(app) as client:assert client.get('/api/health').status_code==200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User))==4
        assert db.scalar(select(func.count()).select_from(Task))==0
