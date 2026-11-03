"""Persistent AI call ledger and in-flight concurrency guard.

Daily call caps are disabled by default. The optional legacy cap configuration
remains compatible for existing deployments, independently from in-flight
tracking, which is active even without a daily cap. No lock spans a model call.
"""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update, and_, or_

from . import config
from .models import AiUsage
from .timeutil import dt, now

KINDS = ('extract', 'timetable', 'assistant', 'qq')


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


def _fresh_reservation():
    current=dt(now())
    # QQ has a hard 45s model deadline; assistant has a hard <=60s budget.
    # Their crashed calls cannot legitimately hold a slot for the generic 10min TTL.
    bounded=('qq','assistant')
    short=(current-timedelta(seconds=90)).isoformat(timespec='seconds')
    general=(current-timedelta(seconds=config.ai_reservation_ttl_seconds())).isoformat(timespec='seconds')
    return or_(and_(AiUsage.kind.in_(bounded),AiUsage.created_at>=short),
               and_(AiUsage.kind.not_in(bounded),AiUsage.created_at>=general))


def _inflight(db):
    return db.scalar(select(func.count()).select_from(AiUsage).where(AiUsage.status=='reserved',_fresh_reservation())) or 0


def reclaim_expired(db):
    result=db.execute(update(AiUsage).where(AiUsage.status=='reserved',~_fresh_reservation()).values(
        status='cancelled',settled_at=now(),note='Expired in-flight reservation reclaimed'))
    db.commit()
    return result.rowcount


def status(db, actor):
    day = _today()
    used_global = _count(db, day)
    used_actor = _count(db, day, actor=actor)
    limit_global = config.ai_daily_budget()
    limit_actor = config.ai_actor_daily_budget()
    enabled=config.ai_budget_enabled()
    return {
        'day': day,
        'enabled': enabled,
        'global': {'limit': limit_global if enabled else None, 'used': used_global, 'remaining': max(0, limit_global - used_global) if enabled else None},
        'actor': {'limit': limit_actor if enabled else None, 'used': used_actor, 'remaining': max(0, limit_actor - used_actor) if enabled else None},
        'max_concurrency': config.ai_max_concurrency(),
        'inflight': _inflight(db),
        'resets_in_seconds': _next_midnight_seconds(),
        'note': '当前不设应用层每日次数限制。' if not enabled else '失败与超时的尝试同样计数。',
    }


def reserve(db, actor, kind='extract'):
    """Track in-flight calls; daily limits are opt-in legacy compatibility."""
    if kind not in KINDS:
        raise ValueError(f'unknown budget kind: {kind}')
    day = _today()
    reclaim_expired(db)
    limit_global = config.ai_daily_budget()
    limit_actor = config.ai_actor_daily_budget()
    retry = {'Retry-After': str(_next_midnight_seconds())}

    if config.ai_budget_enabled() and (limit_global <= 0 or _count(db, day) >= limit_global):
        raise HTTPException(429, '今日 AI 识别额度已用完，请手动录入或明天再试。', headers=retry)
    if config.ai_budget_enabled() and (limit_actor <= 0 or _count(db, day, actor=actor) >= limit_actor):
        raise HTTPException(429, '你本次会话的 AI 识别次数已用完，请手动录入。', headers=retry)
    if _inflight(db) >= config.ai_max_concurrency():
        raise HTTPException(429, '其他 AI 请求正在处理中，请稍后重试。', headers={'Retry-After': '2'})

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
