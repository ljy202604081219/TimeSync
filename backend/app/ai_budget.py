"""AI call budget: a persistent daily ledger plus a concurrency guard.

Why a database ledger and not a process counter: the free Render instance
restarts and sleeps, and anonymous visitors can create new sessions, so an
in-memory counter would reset on every deploy and a per-session counter could be
bypassed. Every attempt is a row, counted towards one global daily budget.

The reservation is taken in a short transaction *before* the remote call and
settled afterwards, so the database write lock is never held while waiting for
the model.
"""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update

from . import config
from .models import AiUsage
from .timeutil import dt, now

KINDS = ('extract', 'timetable')


def _today():
    return now()[:10]


def _next_midnight_seconds():
    current = dt(now())
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - current).total_seconds()))


def _count(db, day, *, actor=None, status=None, since=None):
    query = select(func.count()).select_from(AiUsage).where(AiUsage.day == day)
    if actor is not None:
        query = query.where(AiUsage.actor == actor)
    if status is not None:
        query = query.where(AiUsage.status == status)
    if since is not None:
        query = query.where(AiUsage.created_at >= since)
    return db.scalar(query) or 0


def _inflight(db):
    cutoff = (dt(now()) - timedelta(seconds=config.ai_reservation_ttl_seconds())).isoformat(timespec='seconds')
    return _count(db, _today(), status='reserved', since=cutoff)


def status(db, actor):
    day = _today()
    used_global = _count(db, day)
    used_actor = _count(db, day, actor=actor)
    limit_global = config.ai_daily_budget()
    limit_actor = config.ai_actor_daily_budget()
    return {
        'day': day,
        'enabled': config.ai_budget_enabled(),
        'global': {'limit': limit_global, 'used': used_global, 'remaining': max(0, limit_global - used_global)},
        'actor': {'limit': limit_actor, 'used': used_actor, 'remaining': max(0, limit_actor - used_actor)},
        'max_concurrency': config.ai_max_concurrency(),
        'inflight': _inflight(db),
        'resets_in_seconds': _next_midnight_seconds(),
        'note': '失败与超时的尝试同样计数，避免重试绕过预算。',
    }


def reserve(db, actor, kind='extract'):
    """Reserve one model call. Returns a row id, or None when disabled."""
    if not config.ai_budget_enabled():
        return None
    if kind not in KINDS:
        raise ValueError(f'unknown budget kind: {kind}')
    day = _today()
    limit_global = config.ai_daily_budget()
    limit_actor = config.ai_actor_daily_budget()
    retry = {'Retry-After': str(_next_midnight_seconds())}

    if limit_global <= 0 or _count(db, day) >= limit_global:
        raise HTTPException(429, '今日 AI 识别额度已用完，请手动录入或明天再试。', headers=retry)
    if limit_actor <= 0 or _count(db, day, actor=actor) >= limit_actor:
        raise HTTPException(429, '你本次会话的 AI 识别次数已用完，请手动录入。', headers=retry)
    if _inflight(db) >= config.ai_max_concurrency():
        raise HTTPException(429, '另一个识别请求正在处理中，请稍后重试。', headers={'Retry-After': '10'})

    row = AiUsage(day=day, kind=kind, actor=actor[:120], status='reserved', created_at=now())
    db.add(row)
    db.commit()
    return row.id


def settle(db, reservation_id, status, note=''):
    if reservation_id is None:
        return
    if status not in ('ok', 'error', 'cancelled'):
        raise ValueError(f'unknown settlement status: {status}')
    db.execute(update(AiUsage).where(AiUsage.id == reservation_id, AiUsage.status == 'reserved').values(
        status=status, settled_at=now(), note=(note or '')[:120],
    ))
    db.commit()
