from sqlalchemy import String, Integer, ForeignKey, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    window_start: Mapped[str]
    window_end: Mapped[str]

class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str]
    deadline: Mapped[str] = mapped_column(String, index=True)
    duration_minutes: Mapped[int]
    priority: Mapped[int] = mapped_column(default=2)
    dependencies: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[str] = mapped_column(default='')
    evidence: Mapped[str] = mapped_column(default='')
    source: Mapped[str] = mapped_column(default='manual')

class BusyInterval(Base):
    __tablename__ = 'busy_intervals'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str]
    start: Mapped[str]
    end: Mapped[str]
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(default='course')

class Availability(Base):
    __tablename__ = 'availability'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    start: Mapped[str]
    end: Mapped[str]
    kind: Mapped[str] = mapped_column(default='available')
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)

class PlanVersion(Base):
    __tablename__ = 'plan_versions'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('plan_versions.id'), nullable=True)
    reason: Mapped[str]
    created_at: Mapped[str]
    status: Mapped[str]
    changes: Mapped[list] = mapped_column(JSON, default=list)
    diagnostics: Mapped[list] = mapped_column(JSON, default=list)

class ScheduledTask(Base):
    __tablename__ = 'scheduled_tasks'
    __table_args__ = (UniqueConstraint('plan_id','task_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('plan_versions.id'), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey('tasks.id'), index=True)
    start: Mapped[str]
    end: Mapped[str]

class Disruption(Base):
    __tablename__ = 'disruptions'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    busy_id: Mapped[int] = mapped_column(ForeignKey('busy_intervals.id'))
    plan_id: Mapped[int] = mapped_column(ForeignKey('plan_versions.id'))
    description: Mapped[str]

class Meeting(Base):
    __tablename__ = 'meetings'
    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str]
    start: Mapped[str]
    end: Mapped[str]
    status: Mapped[str] = mapped_column(default='pending')
    revision: Mapped[int] = mapped_column(default=1)
    replaces_id: Mapped[int | None] = mapped_column(ForeignKey('meetings.id'), nullable=True)
    linkage: Mapped[list] = mapped_column(JSON, default=list)

class MeetingInvitation(Base):
    __tablename__ = 'meeting_invitations'
    __table_args__ = (UniqueConstraint('meeting_id','member_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey('meetings.id'), index=True)
    member_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(default='pending')

class RequestRecord(Base):
    __tablename__ = 'request_records'
    __table_args__ = (UniqueConstraint('owner_id','key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    key: Mapped[str]
    fingerprint: Mapped[str]
    response: Mapped[dict] = mapped_column(JSON)

class TimetableImport(Base):
    __tablename__ = 'timetable_imports'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    week_start: Mapped[str]
    source: Mapped[str]
    created_at: Mapped[str]
    courses: Mapped[list] = mapped_column(JSON)


# ---------------------------------------------------------------------------
# Web sessions, device credentials and the AI budget ledger.
# Only token hashes are stored; a raw token is shown once, at issue time.
# ---------------------------------------------------------------------------

class SandboxSession(Base):
    """Short-lived browser session for the shared competition sandbox."""
    __tablename__ = 'sandbox_sessions'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(160), default='sandbox')
    created_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str] = mapped_column(String(40), index=True)
    revoked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_seen_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    client_ip: Mapped[str] = mapped_column(String(64), default='')


class DeviceToken(Base):
    """Read-only credential bound to one owner. Scope is fixed to agenda:read."""
    __tablename__ = 'device_tokens'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(80), default='')
    scope: Mapped[str] = mapped_column(String(40), default='agenda:read')
    created_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str] = mapped_column(String(40), index=True)
    revoked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Server receipt time only. It does not prove the screen drew anything.
    last_request_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str] = mapped_column(String(160), default='')
    notes: Mapped[str] = mapped_column(String(280), default='')


class AiUsage(Base):
    """One row per model call attempt; the ledger survives restarts."""
    __tablename__ = 'ai_usage'
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    kind: Mapped[str] = mapped_column(String(20), default='extract')
    actor: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(12), default='reserved')
    created_at: Mapped[str] = mapped_column(String(40))
    settled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str] = mapped_column(String(120), default='')


Index('ix_ai_usage_day_status', AiUsage.day, AiUsage.status)
