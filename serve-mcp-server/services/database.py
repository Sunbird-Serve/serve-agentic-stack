"""
SERVE MCP Server - Database Configuration
Async PostgreSQL via SQLAlchemy.

Tables owned by the MCP server (AI conversation layer):
  sessions               - workflow state machine per conversation
  volunteer_profiles     - session-scoped working copy / Serve Registry cache
  conversation_messages  - full chat history
  memory_summaries       - AI-compressed long-term context
  telemetry_events       - audit trail for all agent activity
  actor_registry_cache   - identity cache (avoids repeated Serve Registry calls)
  identity_resolution_log- audit trail for S1-S5 identity resolution
  agent_handoff_log      - dedicated table for agent-to-agent handoffs
  need_drafts            - working copy of need draft during conversation
"""
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

import sqlalchemy
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from sqlalchemy.orm import declarative_base

from config import DATABASE_URL

import logging
logger = logging.getLogger(__name__)

# ─── Engine ──────────────────────────────────────────────────────────────────
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# ─── Models ───────────────────────────────────────────────────────────────────

class Session(Base):
    """
    Master record for every AI conversation session.
    Tracks workflow state machine + links to external Serve Registry entities.
    """
    __tablename__ = "sessions"

    id               = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Channel identity
    actor_id         = Column(String(255), nullable=True)   # channel-native identity
    identity_type    = Column(String(50),  nullable=True)   # email | phone | session_id | system
    channel          = Column(String(50),  nullable=False, default="web_ui")
    persona          = Column(String(50),  nullable=False, default="new_volunteer")
    # User classification (S1-S5)
    user_type        = Column(String(50),  nullable=True)   # new_user | registry_known | returning_ai_user | coordinator | anonymous
    # External Serve Registry references (not owned here, just referenced)
    volunteer_id     = Column(String(255), nullable=True)   # Serve Registry osid
    coordinator_id   = Column(String(255), nullable=True)   # Serve Registry coordinator osid
    registry_checked_at = Column(DateTime, nullable=True)   # last Serve Registry lookup
    # Workflow state
    workflow         = Column(String(100), nullable=False, default="new_volunteer_onboarding")
    active_agent     = Column(String(50),  nullable=False, default="onboarding")
    status           = Column(String(20),  nullable=False, default="active")
    stage            = Column(String(50),  nullable=False, default="init")
    sub_state        = Column(Text,        nullable=True)
    context_summary  = Column(Text,        nullable=True)
    channel_metadata = Column(JSONB,       nullable=True)
    idempotency_key  = Column(String(255), nullable=True)   # deduplication (WhatsApp wamid)
    last_message_at  = Column(DateTime,    nullable=True)
    created_at       = Column(DateTime,    default=datetime.utcnow, nullable=False)
    updated_at       = Column(DateTime,    default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_sessions_actor_channel", "actor_id", "channel"),
        sqlalchemy.Index("ix_sessions_volunteer_id",  "volunteer_id"),
        sqlalchemy.Index("ix_sessions_status_updated", "status", "updated_at"),
    )


class VolunteerProfile(Base):
    """
    Session-scoped working copy of a volunteer's profile.
    Populated from Serve Registry at session start (returning users),
    or built up during conversation (new users).
    Pushed back to Serve Registry at onboarding completion.
    """
    __tablename__ = "volunteer_profiles"

    id              = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id      = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True, unique=True)
    # External reference
    serve_volunteer_id = Column(String(255), nullable=True)  # Serve Registry osid
    # Source tracking
    source          = Column(String(20),  nullable=True, default="new")
    # "new"      = built during this conversation
    # "registry" = pre-populated from Serve Registry
    # "merged"   = registry data + new AI-collected data
    registry_fetched_at = Column(DateTime, nullable=True)    # when pulled FROM Serve Registry
    registry_synced_at  = Column(DateTime, nullable=True)    # when last pushed TO Serve Registry
    is_complete     = Column(Boolean,  nullable=True, default=False)
    # Identity fields (from identityDetails)
    full_name       = Column(String(255), nullable=True)
    first_name      = Column(String(100), nullable=True)
    gender          = Column(String(20),  nullable=True)
    dob             = Column(String(20),  nullable=True)
    # Contact fields (from contactDetails)
    email           = Column(String(255), nullable=True)
    phone           = Column(String(50),  nullable=True)
    location        = Column(String(255), nullable=True)     # city + state
    # Skills & preferences (from userPreference / skills[])
    skills          = Column(PGARRAY(String), nullable=True)
    skill_levels    = Column(JSONB,       nullable=True)     # {skillName: skillLevel}
    interests       = Column(PGARRAY(String), nullable=True) # interestArea
    languages       = Column(PGARRAY(String), nullable=True) # language preferences
    availability    = Column(String(100), nullable=True)     # day + time combined
    days_preferred  = Column(PGARRAY(String), nullable=True) # dayPreferred
    time_preferred  = Column(PGARRAY(String), nullable=True) # timePreferred
    # Generic details
    qualification         = Column(String(100), nullable=True)
    years_of_experience   = Column(String(20),  nullable=True)
    employment_status     = Column(String(50),  nullable=True)
    # Onboarding tracking
    profile_completion_pct = Column(Integer, nullable=True, default=0)
    onboarding_completed   = Column(Boolean, nullable=True, default=False)
    eligibility_status     = Column(String(50), nullable=True)
    motivation             = Column(Text, nullable=True)
    experience_level       = Column(String(50), nullable=True)
    preferred_causes       = Column(PGARRAY(String), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at      = Column(DateTime, default=datetime.utcnow, nullable=False)


class ConversationMessage(Base):
    """Every chat message in every session."""
    __tablename__ = "conversation_messages"

    id              = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id      = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    role            = Column(String(20),  nullable=False)   # user | assistant
    content         = Column(Text,        nullable=False)
    agent           = Column(String(50),  nullable=True)
    message_metadata = Column(JSONB,      nullable=True)    # token count, latency, model
    created_at      = Column(DateTime,    default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_conv_messages_session_time", "session_id", "created_at"),
    )


class MemorySummary(Base):
    """AI-compressed long-term memory per session. Versioned."""
    __tablename__ = "memory_summaries"

    id              = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id      = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    volunteer_id    = Column(String(255), nullable=True)    # Serve Registry osid (if resolved)
    summary_text    = Column(Text,        nullable=False)
    key_facts       = Column(JSONB,       default=list,  nullable=False)
    version         = Column(Integer,     default=1,     nullable=False)
    created_at      = Column(DateTime,    default=datetime.utcnow, nullable=False)
    updated_at      = Column(DateTime,    default=datetime.utcnow, nullable=False)


class TelemetryEvent(Base):
    """Audit trail for all agent activity."""
    __tablename__ = "telemetry_events"

    id              = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id      = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    event_type      = Column(String(100), nullable=False)
    agent           = Column(String(50),  nullable=True)
    domain          = Column(String(20),  nullable=True)    # volunteer | need | system
    source_service  = Column(String(50),  nullable=True)    # orchestrator | onboarding_agent | need_agent
    duration_ms     = Column(Integer,     nullable=True)
    data            = Column(JSONB,       default=dict, nullable=False)
    timestamp       = Column(DateTime,    default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_telemetry_session_type", "session_id", "event_type"),
        sqlalchemy.Index("ix_telemetry_timestamp",    "timestamp"),
    )


class ActorRegistryCache(Base):
    """
    Identity cache — avoids calling Serve Registry on every session start.
    Keyed on (actor_id, channel). TTL controlled by expires_at.
    """
    __tablename__ = "actor_registry_cache"

    id               = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id         = Column(String(255), nullable=False)  # phone / email / session stub
    identity_type    = Column(String(50),  nullable=False)  # email | phone | session_id
    channel          = Column(String(50),  nullable=False)  # whatsapp | web_ui | api | mobile
    actor_type       = Column(String(50),  nullable=False)  # volunteer | coordinator | unknown
    serve_entity_id  = Column(String(255), nullable=True)   # Serve Registry osid
    is_onboarding_complete = Column(Boolean, nullable=True, default=False)
    last_active_at   = Column(DateTime,    nullable=True)
    cached_at        = Column(DateTime,    default=datetime.utcnow, nullable=False)
    expires_at       = Column(DateTime,    nullable=False)

    __table_args__ = (
        UniqueConstraint("actor_id", "channel", name="uq_actor_registry_cache"),
        sqlalchemy.Index("ix_actor_cache_expires", "expires_at"),
    )


class IdentityResolutionLog(Base):
    """Audit trail for every identity resolution attempt (S1-S5 classification)."""
    __tablename__ = "identity_resolution_log"

    id                = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id        = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    actor_id          = Column(String(255), nullable=False)
    identity_type     = Column(String(50),  nullable=False)
    channel           = Column(String(50),  nullable=False)
    resolution_status = Column(String(50),  nullable=False)
    # resolved_new | resolved_registry | resolved_returning | resolved_coordinator | unresolved_anonymous
    user_type         = Column(String(50),  nullable=True)   # S1 | S2 | S3 | S4 | S5
    serve_entity_id   = Column(String(255), nullable=True)
    resolution_ms     = Column(Integer,     nullable=True)
    error_detail      = Column(Text,        nullable=True)
    created_at        = Column(DateTime,    default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_identity_log_actor",   "actor_id", "channel"),
        sqlalchemy.Index("ix_identity_log_session",  "session_id"),
    )


class AgentHandoffLog(Base):
    """Dedicated table for agent-to-agent handoffs (previously buried in telemetry)."""
    __tablename__ = "agent_handoff_log"

    id           = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id   = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    from_agent   = Column(String(50),  nullable=False)
    to_agent     = Column(String(50),  nullable=False)
    handoff_type = Column(String(50),  nullable=False)  # agent_transition | resume | escalation | pause
    payload      = Column(JSONB,       nullable=True)
    reason       = Column(Text,        nullable=True)
    created_at   = Column(DateTime,    default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_handoff_session_time", "session_id", "created_at"),
    )


class NeedDraft(Base):
    """
    Working copy of a need being assembled during an AI conversation.
    Lives in MCP DB until submitted. On submission, pushed to Serve Need Service.
    """
    __tablename__ = "need_drafts"

    id                  = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id          = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, unique=True)
    # External Serve references (populated as coordinator/school are resolved)
    serve_need_id       = Column(String(255), nullable=True)  # set after POST /need/raise
    coordinator_osid    = Column(String(255), nullable=True)  # Serve Registry coordinator osid
    entity_id           = Column(String(255), nullable=True)  # Serve Need entity (school) id
    # Need content fields
    subjects            = Column(PGARRAY(String), nullable=True)
    grade_levels        = Column(PGARRAY(String), nullable=True)
    student_count       = Column(Integer,     nullable=True)
    time_slots          = Column(JSONB,       nullable=True)  # [{day, startTime, endTime}]
    start_date          = Column(String(50),  nullable=True)
    end_date            = Column(String(50),  nullable=True)  # derived: start + duration_weeks*7
    duration_weeks      = Column(Integer,     nullable=True)
    schedule_preference = Column(String(255), nullable=True)
    grade_schedule      = Column(JSONB,       nullable=True)  # {"6": {"days":["Monday"],"time_slot":"13:00-14:00"}}
    skipped_grades      = Column(PGARRAY(String), nullable=True)  # grades coordinator opted out of
    special_requirements = Column(Text,       nullable=True)
    # Status tracking
    status              = Column(String(50),  nullable=False, default="draft")
    # draft | pending_approval | approved | rejected | refinement_required | submitted
    admin_comments      = Column(Text,        nullable=True)
    submitted_at        = Column(DateTime,    nullable=True)
    created_at          = Column(DateTime,    default=datetime.utcnow, nullable=False)
    updated_at          = Column(DateTime,    default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_need_drafts_session", "session_id"),
        sqlalchemy.Index("ix_need_drafts_status",  "status"),
    )


# ─── Delivery Assistant tables (post-handshake delivery journey) ──────────────
# Owned by the delivery_assistant agent. One Delivery per volunteer↔need
# assignment; scheduled sessions, policy-driven reminders, blockers, and
# reschedule requests hang off it. See serve-delivery-agent-service.

class Delivery(Base):
    """
    One volunteer↔need delivery journey, from post-handshake activation
    through programme completion / pause / escalation.
    """
    __tablename__ = "deliveries"

    id                = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id        = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    # Assignment context (external Serve references)
    volunteer_id      = Column(String(255), nullable=True)   # Serve Registry osid
    volunteer_name    = Column(String(255), nullable=True)
    need_id           = Column(String(255), nullable=True)   # Serve Need Service need id
    nomination_id     = Column(String(255), nullable=True)
    entity_id         = Column(String(255), nullable=True)   # school / institution
    coordinator_id    = Column(String(255), nullable=True)
    programme         = Column(String(255), nullable=True)
    start_date        = Column(String(50),  nullable=True)
    end_date          = Column(String(50),  nullable=True)
    expected_sessions = Column(Integer,     nullable=True, default=0)
    completed_sessions = Column(Integer,    nullable=False, default=0)
    # Activation gates
    volunteer_acknowledged   = Column(Boolean, nullable=False, default=False)
    coordinator_acknowledged = Column(Boolean, nullable=False, default=False)
    coordinator_phone        = Column(String(50), nullable=True)  # cached at activation, avoids a live lookup per notify
    first_session_ready      = Column(Boolean, nullable=False, default=False)
    activation_completed_at  = Column(DateTime, nullable=True)
    # Readiness across dimensions (volunteer/coordinator/session/classroom/material/
    # meeting_link/infrastructure), each a bool — see policy_engine.evaluate_readiness
    readiness_checklist = Column(JSONB, nullable=True)
    # Deterministic, template-generated delivery-level summary (see write_delivery_summary)
    last_summary      = Column(Text,       nullable=True)
    risk_level        = Column(String(50), nullable=True)  # none | low | medium | high
    # Delivery-level state machine
    delivery_status   = Column(String(50), nullable=False, default="activating")
    # activating | active | on_track | at_risk | interrupted | resumed |
    # nearing_completion | paused | completed | discontinued | escalated
    status_reason     = Column(Text,       nullable=True)
    created_at        = Column(DateTime,   default=datetime.utcnow, nullable=False)
    updated_at        = Column(DateTime,   default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_deliveries_session",   "session_id"),
        sqlalchemy.Index("ix_deliveries_volunteer", "volunteer_id"),
        sqlalchemy.Index("ix_deliveries_status",    "delivery_status"),
    )


class DeliveryScheduledSession(Base):
    """A single scheduled teaching session within a delivery."""
    __tablename__ = "delivery_scheduled_sessions"

    id                = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id       = Column(PGUUID(as_uuid=True), ForeignKey("deliveries.id"), nullable=False)
    session_number    = Column(Integer,     nullable=True)
    scheduled_date    = Column(String(50),  nullable=True)   # ISO date (school-local)
    start_time        = Column(String(20),  nullable=True)   # HH:MM
    end_time          = Column(String(20),  nullable=True)   # HH:MM
    subject           = Column(String(255), nullable=True)
    meeting_link      = Column(Text,        nullable=True)
    delivery_mode     = Column(String(50),  nullable=True)   # online | offline
    session_state     = Column(String(50),  nullable=False, default="upcoming")
    # upcoming | day_reminder_sent | pre_session_reminder_sent |
    # completion_check_sent | completed | partially_completed | missed |
    # unverified | cancelled | reschedule_requested
    outcome           = Column(String(50),  nullable=True)
    # completed | partially_completed | missed | disrupted | unverified |
    # reschedule_requested | support_needed | cancelled
    outcome_reason    = Column(Text,        nullable=True)
    outcome_reported_by = Column(String(50), nullable=True)  # volunteer | coordinator | system
    # Optional structured evidence (see delivery_record_session_outcome)
    attendance_count  = Column(Integer,     nullable=True)
    duration_minutes  = Column(Integer,     nullable=True)
    disruption_type   = Column(String(100), nullable=True)
    # Deterministic, template-generated session-level summary
    last_summary      = Column(Text,        nullable=True)
    created_at        = Column(DateTime,   default=datetime.utcnow, nullable=False)
    updated_at        = Column(DateTime,   default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_delivery_sessions_delivery", "delivery_id"),
        sqlalchemy.Index("ix_delivery_sessions_date",     "scheduled_date"),
    )


class DeliveryReminder(Base):
    """
    Record of a policy-driven reminder for a scheduled session.
    The unique constraint (scheduled_session_id, reminder_type) makes
    duplicate reminders structurally impossible — the audit trail the
    delivery spec mandates.
    """
    __tablename__ = "delivery_reminders"

    id                  = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id         = Column(PGUUID(as_uuid=True), ForeignKey("deliveries.id"), nullable=False)
    scheduled_session_id = Column(PGUUID(as_uuid=True), ForeignKey("delivery_scheduled_sessions.id"), nullable=False)
    reminder_type       = Column(String(50), nullable=False)
    # session_day | pre_session | completion_check | followup_nudge
    status              = Column(String(50), nullable=False, default="sent")
    # sent | suppressed | responded
    suppressed_reason   = Column(Text,       nullable=True)
    sent_at             = Column(DateTime,   default=datetime.utcnow, nullable=False)
    responded_at        = Column(DateTime,   nullable=True)

    __table_args__ = (
        UniqueConstraint("scheduled_session_id", "reminder_type", name="uq_delivery_reminder_type"),
        sqlalchemy.Index("ix_delivery_reminders_delivery", "delivery_id"),
    )


class DeliveryBlocker(Base):
    """A structured operational blocker on a delivery or a specific session."""
    __tablename__ = "delivery_blockers"

    id                   = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id          = Column(PGUUID(as_uuid=True), ForeignKey("deliveries.id"), nullable=False)
    scheduled_session_id = Column(PGUUID(as_uuid=True), ForeignKey("delivery_scheduled_sessions.id"), nullable=True)
    blocker_type         = Column(String(50), nullable=False)
    description          = Column(Text,       nullable=True)
    status               = Column(String(50), nullable=False, default="open")
    # open | resolved | escalated
    owner                = Column(String(100), nullable=True)
    resolution_notes     = Column(Text,       nullable=True)
    resolved_at          = Column(DateTime,   nullable=True)
    raised_by            = Column(String(50), nullable=True)  # volunteer | coordinator | system
    created_at           = Column(DateTime,   default=datetime.utcnow, nullable=False)
    updated_at           = Column(DateTime,   default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_delivery_blockers_delivery", "delivery_id"),
        sqlalchemy.Index("ix_delivery_blockers_status",   "status"),
    )


class DeliveryRescheduleRequest(Base):
    """A reschedule request — always captured as pending; never auto-approved."""
    __tablename__ = "delivery_reschedule_requests"

    id                   = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id          = Column(PGUUID(as_uuid=True), ForeignKey("deliveries.id"), nullable=False)
    scheduled_session_id = Column(PGUUID(as_uuid=True), ForeignKey("delivery_scheduled_sessions.id"), nullable=True)
    reason               = Column(Text,       nullable=True)
    preferred_date       = Column(String(50), nullable=True)
    preferred_time       = Column(String(20), nullable=True)
    requested_by         = Column(String(50), nullable=True)  # volunteer | coordinator
    status               = Column(String(50), nullable=False, default="pending")
    # pending | submitted | approved | rejected
    resolution_notes     = Column(Text,       nullable=True)
    resolved_at          = Column(DateTime,   nullable=True)
    created_at           = Column(DateTime,   default=datetime.utcnow, nullable=False)
    updated_at           = Column(DateTime,   default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_delivery_reschedule_delivery", "delivery_id"),
    )


class DeliveryNotification(Base):
    """A request to notify a linked stakeholder (currently: coordinator). Records
    both the intent and the real send outcome — never assume delivery succeeded."""
    __tablename__ = "delivery_notifications"

    id                = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id       = Column(PGUUID(as_uuid=True), ForeignKey("deliveries.id"), nullable=False)
    stakeholder_type  = Column(String(50), nullable=False)  # coordinator
    reason            = Column(Text,       nullable=True)
    channel           = Column(String(50), nullable=True)   # whatsapp
    status            = Column(String(50), nullable=False, default="requested")
    # requested | sent | failed | no_contact_on_file
    sent_at           = Column(DateTime,   nullable=True)
    created_at        = Column(DateTime,   default=datetime.utcnow, nullable=False)

    __table_args__ = (
        sqlalchemy.Index("ix_delivery_notifications_delivery", "delivery_id"),
    )


# ─── DB Lifecycle ─────────────────────────────────────────────────────────────

async def init_db():
    """Create all tables (safe to call on every startup — uses CREATE IF NOT EXISTS).
    Also runs lightweight column migrations for schema drift (e.g. VARCHAR → TEXT)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run DDL migrations in a separate transaction — asyncpg requires DDL
    # to be committed independently from create_all.
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE sessions ALTER COLUMN sub_state TYPE TEXT"
            ))
        logger.info("Migration applied: sub_state VARCHAR(50) → TEXT")
    except Exception as e:
        # Already TEXT or other benign error — log and continue
        logger.info(f"Migration sub_state skipped (likely already applied): {e}")

    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE need_drafts ADD COLUMN IF NOT EXISTS grade_schedule JSONB"
            ))
        logger.info("Migration applied: need_drafts.grade_schedule JSONB column added")
    except Exception as e:
        logger.info(f"Migration grade_schedule skipped: {e}")

    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE need_drafts ADD COLUMN IF NOT EXISTS skipped_grades TEXT[]"
            ))
        logger.info("Migration applied: need_drafts.skipped_grades TEXT[] column added")
    except Exception as e:
        logger.info(f"Migration skipped_grades skipped: {e}")

    # Delivery Assistant full-spec expansion — additive columns on tables that
    # already existed before this round. New tables (e.g. delivery_notifications)
    # don't need a migration entry; create_all above already handles those.
    _delivery_column_migrations = [
        ("deliveries", "coordinator_phone", "VARCHAR(50)"),
        ("deliveries", "readiness_checklist", "JSONB"),
        ("deliveries", "last_summary", "TEXT"),
        ("deliveries", "risk_level", "VARCHAR(50)"),
        ("delivery_scheduled_sessions", "attendance_count", "INTEGER"),
        ("delivery_scheduled_sessions", "duration_minutes", "INTEGER"),
        ("delivery_scheduled_sessions", "disruption_type", "VARCHAR(100)"),
        ("delivery_scheduled_sessions", "last_summary", "TEXT"),
        ("delivery_blockers", "owner", "VARCHAR(100)"),
        ("delivery_blockers", "resolution_notes", "TEXT"),
        ("delivery_blockers", "resolved_at", "TIMESTAMP"),
        ("delivery_reschedule_requests", "resolution_notes", "TEXT"),
        ("delivery_reschedule_requests", "resolved_at", "TIMESTAMP"),
    ]
    for _table, _column, _coltype in _delivery_column_migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    f"ALTER TABLE {_table} ADD COLUMN IF NOT EXISTS {_column} {_coltype}"
                ))
            logger.info(f"Migration applied: {_table}.{_column} {_coltype} column added")
        except Exception as e:
            logger.info(f"Migration {_table}.{_column} skipped: {e}")

    logger.info("Database tables initialised")


async def close_db():
    await engine.dispose()
    logger.info("Database connections closed")


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─── Connection health (cached — not checked per-call) ────────────────────────

_db_healthy: bool = False


async def check_db_health() -> bool:
    """Test the DB connection. Called once at startup and on failure recovery."""
    global _db_healthy
    try:
        async with get_db() as db:
            await db.execute(text("SELECT 1"))
        _db_healthy = True
        return True
    except Exception as e:
        logger.warning(f"DB health check failed: {e}")
        _db_healthy = False
        return False


def is_db_healthy() -> bool:
    """Return cached DB health status (no network call)."""
    return _db_healthy


async def test_connection() -> bool:
    """Alias kept for backward compatibility."""
    return await check_db_health()
