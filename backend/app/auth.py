"""Token resolution and FastAPI dependencies.

Three credential kinds exist and they are deliberately not interchangeable:

``user``     the four local demo identity tokens (only while LEGACY_TOKEN_AUTH is
             on, i.e. local development). Full business access.
``session``  a short-lived browser sandbox session. Full business access inside
             the shared synthetic sandbox, but no model configuration.
``device``   a read-only credential bound to one owner, scope ``agenda:read``.
             It may read the agenda and nothing else.

Only SHA-256 hashes of tokens are stored. Expiry and revocation are checked on
every request, before any ETag/304 decision.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import errors

from . import config
from .db import session
from .models import DeviceToken, SandboxSession, User
from .timeutil import dt, now

WEB_SCOPES = frozenset({'web:read', 'web:write', 'agenda:read'})
DEVICE_SCOPES = frozenset({'agenda:read'})
SESSION_SCOPES = frozenset({'sandbox', 'web:read', 'web:write', 'agenda:read'})


@dataclass(frozen=True)
class Principal:
    user: User
    kind: str
    scope: frozenset
    token_id: str | None = None
    expires_at: str | None = None

    @property
    def id(self):
        return self.user.id

    @property
    def is_device(self):
        return self.kind == 'device'

    @property
    def is_session(self):
        return self.kind == 'session'

    @property
    def actor(self):
        """Stable budget/rate-limit key: identity plus credential kind."""
        return f'{self.kind}:{self.user.id}:{self.token_id or "legacy"}'


def hash_token(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token():
    return secrets.token_urlsafe(32)


def expired(value):
    return not value or dt(value) <= dt(now())


def resolve(db, raw):
    """Return a Principal, or raise 401 for an expired/revoked credential.

    Returns ``None`` only when the token is simply unknown, so callers can tell
    "wrong token" from "this session ended 3 hours ago".
    """
    if not raw or len(raw) > 512:
        return None
    digest = hash_token(raw)

    if config.legacy_token_auth():
        user = db.scalar(select(User).where(User.token_hash == digest))
        if user:
            return Principal(user=user, kind='user', scope=WEB_SCOPES)

    sandbox = db.scalar(select(SandboxSession).where(SandboxSession.token_hash == digest))
    if sandbox:
        if sandbox.revoked_at:
            raise errors.unauthorized('沙箱会话已退出或被撤销，请重新进入演示沙箱', 'session_revoked')
        if expired(sandbox.expires_at):
            raise errors.unauthorized('沙箱会话已过期，请重新进入演示沙箱', 'session_expired')
        user = db.get(User, sandbox.user_id)
        if not user:
            raise errors.unauthorized('沙箱会话对应的身份不存在，请联系管理员', 'session_expired')
        return Principal(user=user, kind='session', scope=SESSION_SCOPES, token_id=sandbox.id, expires_at=sandbox.expires_at)

    device = db.scalar(select(DeviceToken).where(DeviceToken.token_hash == digest))
    if device:
        if device.revoked_at:
            raise errors.unauthorized('设备凭据已撤销，请联系管理员重新签发', 'device_revoked')
        if expired(device.expires_at):
            raise errors.unauthorized('设备凭据已过期，请联系管理员重新签发', 'device_expired')
        user = db.get(User, device.owner_id)
        if not user:
            raise errors.unauthorized('设备凭据绑定的身份不存在', 'device_revoked')
        return Principal(user=user, kind='device', scope=DEVICE_SCOPES, token_id=device.id, expires_at=device.expires_at)

    return None


def bearer(authorization: str = Header(default='')) -> str:
    if not authorization.startswith('Bearer '):
        raise errors.unauthorized('请先登录或提供访问令牌', 'auth_missing')
    raw = authorization[7:].strip()
    if not raw:
        raise errors.unauthorized('访问令牌为空', 'auth_missing')
    return raw


def principal(token: str = Depends(bearer), db: Session = Depends(session)) -> Principal:
    found = resolve(db, token)
    if not found:
        raise errors.unauthorized('访问令牌无效或已被删除，请重新登录', 'auth_invalid')
    return found


def current_user(found: Principal = Depends(principal)) -> User:
    """Full identity: rejects device credentials on every business endpoint."""
    if found.is_device:
        raise errors.forbidden('设备凭据只允许读取日程，不能调用该接口', 'device_forbidden')
    return found.user


def agenda_reader(found: Principal = Depends(principal)) -> Principal:
    if 'agenda:read' not in found.scope:
        raise errors.forbidden('该凭据没有日程读取权限', 'device_forbidden')
    return found


def session_only(found: Principal = Depends(principal)) -> Principal:
    if found.kind != 'session':
        raise errors.ApiError(403, '该接口只接受沙箱会话凭据（当前为本地演示身份令牌）', 'not_a_session')
    return found


def admin(x_admin_token: str = Header(default=''), authorization: str = Header(default='')) -> str:
    """Administrator gate for credential issuance. Disabled when unset."""
    expected = config.admin_token()
    if len(expected) < 16:
        raise errors.ApiError(503, '服务端未配置 ADMIN_TOKEN（至少 16 字符），管理接口不可用', 'admin_disabled')
    supplied = x_admin_token.strip()
    if not supplied and authorization.startswith('Bearer '):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise errors.forbidden('管理员凭据无效', 'admin_denied')
    return 'admin'


def remaining_minutes(value):
    if not value:
        return None
    return max(0, int((dt(value) - dt(now())).total_seconds() // 60))


def ttl_stamp(minutes=None, days=None):
    delta = timedelta(minutes=minutes) if minutes is not None else timedelta(days=days)
    return (dt(now()) + delta).isoformat(timespec='seconds')
