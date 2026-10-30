"""Synthetic, repeatable demo fixtures. No real student data.

The anchor date is a Monday. ``seed()`` keeps the original 2026-11-02 week by
default, so existing tests and screenshots stay valid, while the cloud bootstrap
can generate fixtures for the actual demo week:

    from app.demo import seed
    seed(db, demo_data=True, anchor='2026-12-07')
"""
import hashlib
import secrets
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select

from .models import User, Task, BusyInterval, Availability, PlanVersion, ScheduledTask
from .timeutil import TZ

DEFAULT_ANCHOR = '2026-11-02'
MEMBERS = {'A': '林同学', 'B': '陈同学', 'C': '王同学', 'D': '许同学'}
COURSES = [(2, '08:00', '10:00', '高等数学'), (3, '10:00', '12:00', '程序设计'), (4, '08:00', '10:00', '大学英语'), (5, '14:00', '16:00', '专业选修'), (6, '10:00', '12:00', '通识课程')]


def anchor_date(anchor=None):
    value = date.fromisoformat(anchor or DEFAULT_ANCHOR)
    if value.weekday() != 0:
        raise ValueError('演示锚点必须是周一（例如 2026-11-02）')
    return value


def window(anchor=None):
    base = anchor_date(anchor)
    start = datetime.combine(base, time(8, 0), TZ)
    return start.isoformat(timespec='seconds'), (start + timedelta(days=7)).isoformat(timespec='seconds')


def stamp(day, clock, anchor=None):
    """Day 2..8 of the demo week as an ISO8601 Shanghai timestamp."""
    base = anchor_date(anchor) + timedelta(days=day - 2)
    return f'{base.isoformat()}T{clock}:00+08:00'


DEMO_START, DEMO_END = window()


def _member_fixtures(db, member, index, anchor):
    for day in range(2, 9):
        db.add(Availability(owner_id=member, start=stamp(day, '08:00', anchor), end=stamp(day, '22:00', anchor), kind='available'))
        db.add(Availability(owner_id=member, start=stamp(day, '12:00', anchor), end=stamp(day, '13:30', anchor), kind='uncomfortable'))
    for day, a, b, title in COURSES:
        hour_shift = index if day in (2, 4) else 0
        a = f'{int(a[:2]) + hour_shift:02}:00'
        b = f'{int(b[:2]) + hour_shift:02}:00'
        db.add(BusyInterval(owner_id=member, title=title, start=stamp(day, a, anchor), end=stamp(day, b, anchor), kind='course', weekday=day - 2))
    first = Task(owner_id=member, title='机器学习 · 实验报告', deadline=stamp(5, '18:00', anchor), duration_minutes=120, priority=3, requirements='提交 PDF 与源代码', source='demo', dependencies=[])
    db.add(first)
    db.flush()
    second = Task(owner_id=member, title='阅读与整理文献', deadline=stamp(6, '20:00', anchor), duration_minutes=90, priority=2, dependencies=[], source='demo')
    third = Task(owner_id=member, title='小组项目 · 演示准备', deadline=stamp(8, '20:00', anchor), duration_minutes=60, priority=2, dependencies=[first.id], source='demo')
    db.add_all([second, third])
    db.flush()
    plan = PlanVersion(owner_id=member, parent_id=None, reason='四人演示初始计划（合成数据）', created_at=stamp(2, '08:00', anchor), status='feasible', changes=[], diagnostics=[])
    db.add(plan)
    db.flush()
    for task, a, b in [(first, stamp(4, '14:00', anchor), stamp(4, '16:00', anchor)), (second, stamp(5, '09:00', anchor), stamp(5, '10:30', anchor)), (third, stamp(6, '16:00', anchor), stamp(6, '17:00', anchor))]:
        db.add(ScheduledTask(plan_id=plan.id, task_id=task.id, start=a, end=b))


def fixtures(db, *, anchor=None, reset_window=False):
    """Add the synthetic course/task/plan set to identities that have no tasks.

    Returns the member ids that gained fixtures. Calling it twice is a no-op, so
    the cloud bootstrap can run it before every demo without duplicating data.
    """
    start, end = window(anchor)
    added = []
    for index, member in enumerate('ABCD'):
        user = db.get(User, member)
        if not user:
            continue
        existing = db.scalar(select(func.count()).select_from(Task).where(Task.owner_id == member))
        if existing:
            continue
        if reset_window:
            user.window_start, user.window_end = start, end
        _member_fixtures(db, member, index, anchor)
        added.append(member)
    db.commit()
    return added


def seed(db, *, demo_data=False, anchor=None, tokens=True):
    """Create the four synthetic identities (and optional fixtures).

    Returns a ``{member: token}`` mapping for the local SQLite demo path, or an
    empty dict when identities already exist. Cloud bootstrap calls this with
    ``tokens=False`` so no permanent credential is ever written to disk.
    """
    if db.get(User, 'A'):
        return {}
    start, end = window(anchor)
    issued = {}
    for member in 'ABCD':
        token = secrets.token_urlsafe(32 if tokens else 48)
        issued[member] = token
        db.add(User(
            id=member,
            name=MEMBERS[member],
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            window_start=start,
            window_end=end,
        ))
        db.flush()
    if demo_data:
        fixtures(db, anchor=anchor)
    else:
        db.commit()
    return issued if tokens else {}
