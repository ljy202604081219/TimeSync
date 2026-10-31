"""Machine-readable API errors.

The UI must be able to tell "your session ended, log in again" apart from
"you are not allowed to do that" without parsing Chinese prose. Every error
keeps the existing ``{"detail": "<human sentence>"}`` shape (so nothing that
already reads ``detail`` breaks) and adds a stable ``code``.

Codes used by the login loop (frozen contract, see docs/contracts/auth-flow.md):

    auth_missing      401  no Authorization: Bearer header
    auth_invalid      401  unknown token
    session_expired   401  sandbox session past expires_at  -> log in again
    session_revoked   401  sandbox session logged out/revoked -> log in again
    device_expired    401  device credential past expires_at
    device_revoked    401  device credential revoked
    device_forbidden  403  device credential used on a write endpoint
    sandbox_disabled  404  sandbox login is not enabled on this deployment
    sandbox_full      429  too many active sandbox sessions
    rate_limited      429  AI budget exhausted (Retry-After set)
    payload_too_large 413  request body above MAX_REQUEST_BYTES
    busy              503  business write lock timeout, safe to retry
"""
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    """HTTPException carrying a stable, client-facing ``code``."""

    def __init__(self, status_code, detail, code, headers=None):
        super().__init__(status_code=status_code, detail=detail, headers=dict(headers or {}))
        self.code = code


def unauthorized(detail, code='auth_invalid', headers=None):
    """401 must carry WWW-Authenticate (RFC 9110 §15.5.2)."""
    merged = {'WWW-Authenticate': 'Bearer'}
    merged.update(headers or {})
    return ApiError(401, detail, code, merged)


def forbidden(detail, code='forbidden'):
    return ApiError(403, detail, code)


async def http_error_handler(request: Request, exc: HTTPException):
    body = {'detail': exc.detail}
    code = getattr(exc, 'code', None)
    if code:
        body['code'] = code
    headers = dict(exc.headers or {})
    if exc.status_code == 401:
        headers.setdefault('WWW-Authenticate', 'Bearer')
    return JSONResponse(body, status_code=exc.status_code, headers=headers)


def install(app):
    app.add_exception_handler(HTTPException, http_error_handler)
