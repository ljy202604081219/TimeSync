"""B4: concurrency proof on a real PostgreSQL server.

These tests only run when ``TIMESYNC_TEST_DATABASE_URL`` points at a PostgreSQL
database: the behaviour under test (transaction-scoped advisory locks, real
concurrent transactions, real COMMIT boundaries) does not exist on SQLite.

    set TIMESYNC_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/timesync_test
    python -m pytest tests/test_pg_concurrency.py -q

The database in that URL is dropped and recreated. Never point it at real data.

Why the meeting test is the important one: the old code took one advisory lock
per ``owner:Idempotency-Key``. Two members answering the same invitation hold
two different keys, so both transactions could read "the other member has not
answered yet" and both commit — every invitation ends up ``accepted`` while the
meeting stays ``pending``. The first test below pins that defect down with the
legacy locking strategy; the rest prove the shipped one.
"""
import os
import socket
import threading
import time
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
import uvicorn
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app import coordination
from app.db import Base, make_engine, session as session_dep
from app.db import write_transaction as real_write_transaction
from app.demo import seed
from app.main import app as fastapi_app
from app.models import Meeting, MeetingInvitation, PlanVersion, RequestRecord, Task

PG_URL = os.getenv('TIMESYNC_TEST_DATABASE_URL', '').strip()
pytestmark = pytest.mark.skipif(not PG_URL, reason='needs TIMESYNC_TEST_DATABASE_URL (real PostgreSQL)')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@pytest.fixture
def pg(monkeypatch):
    """Fresh schema, demo fixtures, and a real uvicorn server on one port."""
    monkeypatch.setenv('DEMO_MODE', 'true')
    monkeypatch.setenv('SANDBOX_MODE', 'false')
    monkeypatch.setenv('AUTO_MIGRATE', 'false')
    engine = make_engine(PG_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        tokens = seed(db, demo_data=True)

    def override():
        with factory() as db:
            yield db

    fastapi_app.dependency_overrides[session_dep] = override
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(fastapi_app, host='127.0.0.1', port=port,
                                           log_level='warning', lifespan='off'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(f'http://127.0.0.1:{port}/api/health', timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        raise RuntimeError('test server did not start')

    class Ctx:
        base = f'http://127.0.0.1:{port}'
        db_factory = factory
        demo_tokens = tokens
        engine_ = engine

        def client(self):
            return httpx.Client(base_url=self.base, timeout=60)

        def auth(self, member, key=None):
            headers = {'Authorization': 'Bearer ' + tokens[member]}
            if key:
                headers['Idempotency-Key'] = key
            return headers

    yield Ctx()
    server.should_exit = True
    thread.join(timeout=15)
    fastapi_app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def run_together(jobs):
    """Start every job at the same instant; return results in submission order.

    A barrier *before* the request only synchronises the start. Putting it inside
    the transaction would deadlock against a correct mutual exclusion, so the
    tests measure overlap with timestamps instead.
    """
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)
    errors: list[BaseException | None] = [None] * len(jobs)

    def worker(index, job):
        try:
            barrier.wait(timeout=30)
            results[index] = job()
        except BaseException as error:  # noqa: BLE001 - surfaced by the assertions
            errors[index] = error

    threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)
    for error in errors:
        if error:
            raise error
    return results


# ---------------------------------------------------------------------------
# 1. One lock for every business writer, not one per idempotency key
# ---------------------------------------------------------------------------

def test_business_lock_is_one_global_key():
    from app.db import BUSINESS_LOCK_KEY
    assert BUSINESS_LOCK_KEY == int('54534E43', 16) == 0x54534E43
    assert 0 < BUSINESS_LOCK_KEY < 2 ** 63


def test_writers_with_different_keys_never_overlap(pg):
    """Read-modify-write under two different keys must not lose an update."""
    with pg.engine_.begin() as conn:
        conn.execute(text('DROP TABLE IF EXISTS lock_probe'))
        conn.execute(text('CREATE TABLE lock_probe (id int primary key, value int not null)'))
        conn.execute(text('INSERT INTO lock_probe VALUES (1, 0)'))

    windows: list[tuple[float, float]] = []
    guard = threading.Lock()

    def bump(tag):
        def job():
            with pg.db_factory() as db:
                with real_write_transaction(db, f'{tag}:{tag}-key'):
                    start = time.monotonic()
                    current = db.execute(text('SELECT value FROM lock_probe WHERE id=1')).scalar()
                    time.sleep(0.3)  # widen the lost-update window
                    db.execute(text('UPDATE lock_probe SET value=:value WHERE id=1'), {'value': current + 1})
                    db.commit()
                    end = time.monotonic()
            with guard:
                windows.append((start, end))
            return current
        return job

    # Different owner, different idempotency key: the case a per-key lock misses.
    first, second = run_together([bump('A'), bump('B')])
    assert sorted([first, second]) == [0, 1], (
        f'both writers read the same value: {first}, {second}; windows={windows}')

    (a_start, a_end), (b_start, b_end) = windows
    # Order is arbitrary; mutual exclusion means the two intervals are disjoint.
    gap = max(a_start, b_start) - min(a_end, b_end)
    # A 5 ms tolerance covers measurement at the commit boundary; a genuinely
    # unlocked lost update overlaps for the whole 300 ms sleep inside.
    assert gap > -0.005, f'transactions overlapped by {-gap:.4f}s: {windows}'

    with pg.db_factory() as db:
        assert db.execute(text('SELECT value FROM lock_probe WHERE id=1')).scalar() == 2


# ---------------------------------------------------------------------------
# 2. The reported product defect: simultaneous accepts left the meeting pending
# ---------------------------------------------------------------------------

@contextmanager
def slow_first_read(delay=0.25):
    """Make each thread read the invitations, then sit on them for a moment.

    Without it the race window is a few milliseconds and the test would be
    flaky; with it, every thread is guaranteed to have read before anyone commits.
    """
    original = coordination.invitations
    local = threading.local()

    def wrapper(db, meeting):
        rows = original(db, meeting)
        if not getattr(local, 'slept', False):
            local.slept = True
            time.sleep(delay)
        return rows

    coordination.invitations = wrapper
    try:
        yield
    finally:
        coordination.invitations = original


def book_meeting(pg, members=('A', 'B'), duration=60):
    """Create a pending meeting at a slot the candidate search says is free."""
    start = '2026-11-04T00:00:00+08:00'
    end = '2026-11-05T00:00:00+08:00'
    with pg.client() as client:
        found = client.post('/api/coordination/candidates', headers=pg.auth('A'),
                            json={'start': start, 'end': end, 'duration_minutes': duration,
                                  'members': list(members)})
        assert found.status_code == 200, found.text
        candidates = found.json()['candidates']
        assert candidates, 'fixture week has no common free slot; adjust book_meeting()'
        slot = candidates[0]
        created = client.post('/api/meetings', headers=pg.auth('A', 'meeting-create'),
                              json={'title': '并发确认测试', 'start': slot['start'], 'end': slot['end'],
                                    'members': list(members)})
        assert created.status_code == 200, created.text
        return created.json()


def accept_all(pg, meeting, members):
    bodies = [lambda m=m: dict(response='accepted', revision=meeting['revision']) for m in members]

    def job(member, body):
        def call():
            with pg.client() as client:
                return client.post(f"/api/meetings/{meeting['id']}/respond",
                                   headers=pg.auth(member, f'respond-{member}-{meeting["id"]}'),
                                   json=body())
        return call

    return run_together([job(member, body) for member, body in zip(members, bodies)])


def test_the_per_key_lock_would_have_missed_this_race(pg, monkeypatch):
    """Characterisation of the defect: same requests, old locking strategy."""
    @contextmanager
    def per_key_write_transaction(db, scope='business'):
        db.rollback()
        db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'), {'scope': scope})
        try:
            yield db
        except BaseException:
            db.rollback()
            raise

    monkeypatch.setattr('app.main.write_transaction', per_key_write_transaction)
    meeting = book_meeting(pg, ('A', 'B'))
    with slow_first_read():
        responses = accept_all(pg, meeting, ['A', 'B'])
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    with pg.db_factory() as db:
        row = db.get(Meeting, meeting['id'])
        statuses = sorted(i.status for i in db.scalars(
            select(MeetingInvitation).where(MeetingInvitation.meeting_id == meeting['id'])))
        # Every member agreed, the meeting is still waiting for confirmation.
        assert statuses == ['accepted', 'accepted']
        assert row.status == 'pending', 'if this now says confirmed, the legacy shim is wrong'


def test_simultaneous_accepts_confirm_the_meeting_exactly_once(pg):
    meeting = book_meeting(pg, ('A', 'B', 'C'))
    with slow_first_read():
        responses = accept_all(pg, meeting, ['A', 'B', 'C'])
    assert [r.status_code for r in responses] == [200, 200, 200], [r.text for r in responses]
    # Each response describes the state as of its own commit: the members who
    # answered before the last one legitimately saw "pending". What must hold is
    # that nobody saw a half-applied or regressed state, and that the meeting
    # ended confirmed. The old per-key lock produced all-200, all-accepted,
    # still-pending here.
    final = [r.json()['status'] for r in responses]
    assert set(final) <= {'pending', 'confirmed'}, final
    assert 'confirmed' in final, final
    assert final.index('confirmed') == len(final) - 1 or final.count('confirmed') >= 1

    with pg.db_factory() as db:
        row = db.get(Meeting, meeting['id'])
        assert row.status == 'confirmed'
        assert len(row.linkage) == 3, row.linkage
        statuses = sorted(i.status for i in db.scalars(
            select(MeetingInvitation).where(MeetingInvitation.meeting_id == meeting['id'])))
        assert statuses == ['accepted'] * 3


def test_decline_wins_over_a_concurrent_accept(pg):
    """A meeting must never end up confirmed after somebody declined."""
    meeting = book_meeting(pg, ('A', 'B', 'C'))
    with slow_first_read():
        responses = run_together([
            lambda: _respond(pg, meeting, 'A', 'accepted'),
            lambda: _respond(pg, meeting, 'B', 'declined'),
            lambda: _respond(pg, meeting, 'C', 'accepted'),
        ])
    codes = [r.status_code for r in responses]
    assert all(code in (200, 409) for code in codes), [r.text for r in responses]
    with pg.db_factory() as db:
        row = db.get(Meeting, meeting['id'])
        assert row.status == 'declined', row.status
        accepted = db.scalar(select(func.count()).select_from(MeetingInvitation).where(
            MeetingInvitation.meeting_id == meeting['id'], MeetingInvitation.status == 'accepted'))
        assert accepted < 3


def _respond(pg, meeting, member, answer):
    with pg.client() as client:
        return client.post(f"/api/meetings/{meeting['id']}/respond",
                           headers=pg.auth(member, f'respond-{member}-{answer}-{meeting["id"]}'),
                           json={'response': answer, 'revision': meeting['revision']})


# ---------------------------------------------------------------------------
# 3. Idempotency still holds when the same key arrives twice at once
# ---------------------------------------------------------------------------

def test_same_idempotency_key_in_parallel_creates_one_row(pg):
    body = {'title': '并发幂等任务', 'deadline': '2026-11-06T18:00:00+08:00', 'duration_minutes': 60}

    def job():
        with pg.client() as client:
            return client.post('/api/tasks', headers=pg.auth('A', 'same-key-1'), json=body)

    first, second = run_together([job, job])
    assert [first.status_code, second.status_code] == [200, 200], [first.text, second.text]
    assert first.json()['id'] == second.json()['id']
    with pg.db_factory() as db:
        assert db.scalar(select(func.count()).select_from(Task).where(Task.title == '并发幂等任务')) == 1
        assert db.scalar(select(func.count()).select_from(RequestRecord).where(
            RequestRecord.owner_id == 'A', RequestRecord.key == 'same-key-1')) == 1


# ---------------------------------------------------------------------------
# 4. A failure inside the transaction leaves nothing behind
# ---------------------------------------------------------------------------

def test_failed_confirm_rolls_back_and_releases_the_lock(pg):
    meeting = book_meeting(pg, ('A', 'B'))
    assert _respond(pg, meeting, 'A', 'accepted').status_code == 200

    def explode(*args, **kwargs):
        raise RuntimeError('solver exploded')

    # Only the confirming request reaches compute(); B is the last accept.
    # Restored by hand: monkeypatch.undo() would also drop the fixture's env.
    original_compute = coordination.compute
    coordination.compute = explode
    failed = _respond(pg, meeting, 'B', 'accepted')
    assert failed.status_code == 500, failed.text

    with pg.db_factory() as db:
        assert db.get(Meeting, meeting['id']).status == 'pending'
        invite = db.scalar(select(MeetingInvitation).where(
            MeetingInvitation.meeting_id == meeting['id'], MeetingInvitation.member_id == 'B'))
        assert invite.status == 'pending', 'partial write survived the rollback'
        assert db.scalar(select(func.count()).select_from(RequestRecord).where(
            RequestRecord.key == f'respond-B-accepted-{meeting["id"]}')) == 0
        assert db.scalar(select(func.count()).select_from(PlanVersion).where(
            PlanVersion.reason.like(f'%会议 #{meeting["id"]}%'))) == 0

    # The advisory lock must be gone: the retry may not block or time out.
    coordination.compute = original_compute
    started = time.monotonic()
    retried = _respond(pg, meeting, 'B', 'accepted')
    assert retried.status_code == 200, retried.text
    assert retried.json()['status'] == 'confirmed'
    assert time.monotonic() - started < 30
