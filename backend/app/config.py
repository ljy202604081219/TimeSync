"""Runtime flags read from the environment on every access.

Defaults keep the local single-user experience working with no .env at all.
Cloud deployments must set the values documented in .env.example explicitly; a
flag is never inferred from another one except where noted (LEGACY_TOKEN_AUTH
follows DEMO_MODE so that turning the demo entry off does not silently leave the
old permanent tokens active).
"""
import os

TRUE = {'1', 'true', 'yes', 'on'}


def flag(name, default):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in TRUE


def number(name, default, minimum=0, maximum=None):
    try:
        value = int(str(os.getenv(name, '')).strip())
    except ValueError:
        return default
    value = max(minimum, value)
    return min(maximum, value) if maximum is not None else value


def text(name, default=''):
    return (os.getenv(name) or default).strip()


def demo_mode():
    """Local synthetic demo endpoints. Never enables cloud sandbox sessions."""
    return flag('DEMO_MODE', True)


def sandbox_enabled():
    """Short-lived shared browser sessions for the competition sandbox."""
    return flag('SANDBOX_MODE', False)


def legacy_token_auth():
    """Whether the four permanent user tokens still authenticate requests."""
    return flag('LEGACY_TOKEN_AUTH', demo_mode())


def auto_migrate():
    return flag('AUTO_MIGRATE', True)


def bootstrap_fixtures():
    """Seed the synthetic identities (and demo week) when the database is empty.

    Cloud containers have no shell on the free tier, so an empty database left
    after the first migration would have zero members and nobody could log in.
    Off by default: a local run seeds through DEMO_MODE instead.
    """
    return flag('BOOTSTRAP_FIXTURES', False)


def bootstrap_anchor():
    """Monday of the demo week for BOOTSTRAP_FIXTURES; empty means this week."""
    return text('BOOTSTRAP_ANCHOR')


def admin_token():
    return text('ADMIN_TOKEN')


def session_ttl_minutes():
    return number('SANDBOX_SESSION_TTL_MINUTES', 180, 5, 24 * 60)


def max_active_sessions():
    return number('SANDBOX_MAX_ACTIVE_SESSIONS', 40, 1, 500)


def device_ttl_days():
    return number('DEVICE_TOKEN_TTL_DAYS', 7, 1, 90)


def max_request_bytes():
    return number('MAX_REQUEST_BYTES', 8 * 1024 * 1024, 64 * 1024)


def ai_budget_enabled():
    return flag('AI_BUDGET_ENABLED', True)


def ai_daily_budget():
    return number('AI_DAILY_BUDGET', 20, 0)


def ai_actor_daily_budget():
    return number('AI_ACTOR_DAILY_BUDGET', 5, 0)


def ai_max_concurrency():
    return number('AI_MAX_CONCURRENCY', 1, 1, 16)


def ai_reservation_ttl_seconds():
    return number('AI_RESERVATION_TTL_SECONDS', 600, 30, 7200)
