"""Issuance, revocation and metadata for sandbox sessions and device credentials.

Raw tokens leave this module exactly once, from the create/issue functions. The
database only ever holds SHA-256 hashes. Device metadata returned to the web UI
never contains a token, a hash, or another owner's rows.
"""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from . import config
from .auth import DEVICE_SCOPES, hash_token, new_token, remaining_minutes, ttl_stamp
from .models import DeviceToken, SandboxSession, User
from .timeutil import dt, now

TOUCH_INTERVAL_SECONDS = 60
SANDBOX_NOTICE = '共享演示沙箱：其他体验者可能修改同一份合成数据；请勿填写真实个人信息。'
DEVICE_SCOPE = 'agenda:read'


def _before(days=0, minutes=0):
    return (dt(now()) - timedelta(days=days, minutes=minutes)).isoformat(timespec='seconds')


def _active_device(token):
    if token.revoked_at:
        return 'revoked'
    if not token.expires_at or dt(token.expires_at) <= dt(now()):
        return 'expired'
    return 'active'


def device_metadata(token):
    return {
        'id': token.id,
        'owner_id': token.owner_id,
        'label': token.label,
        'scope': token.scope,
        'status': _active_device(token),
        'created_at': token.created_at,
        'expires_at': token.expires_at,
        'revoked_at': token.revoked_at,
        'last_request_at': token.last_request_at,
    }


# --------------------------------------------------------------------------
# Sandbox sessions
# --------------------------------------------------------------------------

def create_session(db, user_id, client_ip=''):
    if not config.sandbox_enabled():
        raise HTTPException(404, '沙箱登录未启用')
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, '演示身份不存在')
    # Cheap housekeeping: expired sessions are useless and would otherwise
    # accumulate across redeploys of a free instance.
    db.execute(delete(SandboxSession).where(SandboxSession.expires_at < _before(days=1)))
    active_count = db.scalar(select(func.count()).select_from(SandboxSession).where(
        SandboxSession.revoked_at.is_(None),
        SandboxSession.expires_at > now(),
    )) or 0
    if active_count >= config.max_active_sessions():
        raise HTTPException(429, '当前沙箱会话过多，请稍后再试或联系管理员清理')

    raw = new_token()
    minutes = config.session_ttl_minutes()
    session = SandboxSession(
        id=new_token()[:24],
        user_id=user_id,
        token_hash=hash_token(raw),
        scope='sandbox',
        created_at=now(),
        expires_at=ttl_stamp(minutes=minutes),
        client_ip=(client_ip or '')[:64],
    )
    db.add(session)
    db.commit()
    return {
        'token': raw,
        'kind': 'session',
        'scope': sorted(DEVICE_SCOPES | {'sandbox', 'web:read', 'web:write'}),
        'user': {'id': user.id, 'name': user.name},
        'issued_at': session.created_at,
        'expires_at': session.expires_at,
        'expires_in_seconds': minutes * 60,
        'notice': SANDBOX_NOTICE,
    }


def session_info(found):
    return {
        'kind': found.kind,
        'scope': sorted(found.scope),
        'user': {'id': found.user.id, 'name': found.user.name},
        'expires_at': found.expires_at,
        'remaining_minutes': remaining_minutes(found.expires_at),
        'notice': SANDBOX_NOTICE,
    }


def revoke_session(db, found):
    row = db.get(SandboxSession, found.token_id) if found.token_id else None
    if not row:
        raise HTTPException(404, '会话不存在')
    row.revoked_at = row.revoked_at or now()
    db.commit()
    return {'revoked': True, 'id': row.id, 'revoked_at': row.revoked_at}


# --------------------------------------------------------------------------
# Device credentials
# --------------------------------------------------------------------------

def issue_device(db, owner_id, label='', ttl_days=None, created_by='admin', notes=''):
    owner = db.get(User, owner_id)
    if not owner:
        raise HTTPException(404, '绑定的身份不存在')
    label = (label or '').strip()
    if len(label) > 80:
        raise HTTPException(422, '设备名称最长 80 个字符')
    days = config.device_ttl_days() if ttl_days is None else int(ttl_days)
    if not 1 <= days <= 90:
        raise HTTPException(422, '设备凭据有效期必须在 1–90 天之间')
    raw = new_token()
    token = DeviceToken(
        id=new_token()[:24],
        owner_id=owner_id,
        token_hash=hash_token(raw),
        label=label,
        scope=DEVICE_SCOPE,
        created_at=now(),
        expires_at=ttl_stamp(days=days),
        created_by=(created_by or 'admin')[:160],
        notes=(notes or '')[:280],
    )
    db.add(token)
    db.commit()
    return {
        'token': raw,
        'notice': '明文令牌只在此次响应中出现一次，请写入设备安全配置；服务端只保存哈希。',
        **device_metadata(token),
        'ttl_days': days,
    }


def revoke_device(db, token_id):
    token = db.get(DeviceToken, token_id)
    if not token:
        raise HTTPException(404, '设备凭据不存在')
    token.revoked_at = token.revoked_at or now()
    db.commit()
    return {'revoked': True, 'revoked_at': token.revoked_at, **device_metadata(token)}


def list_devices(db, owner_id):
    rows = db.scalars(select(DeviceToken).where(DeviceToken.owner_id == owner_id).order_by(DeviceToken.created_at.desc()))
    return [device_metadata(token) for token in rows]


def admin_list_devices(db, owner_id=None):
    query = select(DeviceToken).order_by(DeviceToken.created_at.desc()).limit(200)
    if owner_id:
        query = select(DeviceToken).where(DeviceToken.owner_id == owner_id).order_by(DeviceToken.created_at.desc()).limit(200)
    return [device_metadata(token) for token in db.scalars(query)]


def touch_device(db, found):
    """Record that the server received a request. Never proves the screen drew."""
    if not found.token_id:
        return False
    token = db.get(DeviceToken, found.token_id)
    if not token:
        return False
    last = token.last_request_at
    if last and (dt(now()) - dt(last)).total_seconds() < TOUCH_INTERVAL_SECONDS:
        return False
    token.last_request_at = now()
    db.commit()
    return True
