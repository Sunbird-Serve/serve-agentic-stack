"""
SERVE Agentic MCP Service - Database Models
SQLAlchemy ORM models for all core entities
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Boolean, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID, ARRAY, ENUM
from sqlalchemy.orm import relationship

from app.db.database import Base


# Create ENUM types for PostgreSQL
channel_type_enum = ENUM('web_ui', 'whatsapp', 'api', name='channel_type', create_type=False)
persona_type_enum = ENUM('new_volunteer', 'returning_volunteer', 'inactive_volunteer', 'need_coordinator', 'system', name='persona_type', create_type=False)
workflow_type_enum = ENUM('new_volunteer_onboarding', 'returning_volunteer', 'need_coordination', 'volunteer_engagement', 'system_triggered', name='workflow_type', create_type=False)
agent_type_enum = ENUM('onboarding', 'selection', 'engagement', 'need', 'fulfillment', 'delivery_assistant', name='agent_type', create_type=False)
session_status_enum = ENUM('active', 'paused', 'completed', 'abandoned', 'escalated', name='session_status', create_type=False)
handoff_type_enum = ENUM('agent_transition', 'resume', 'escalation', 'pause', name='handoff_type', create_type=False)
event_type_enum = ENUM('session_start', 'session_end', 'state_transition', 'mcp_call', 'agent_response', 'handoff', 'error', 'user_message', name='event_type', create_type=False)


class Session(Base):
    """
    Represents an interaction lifecycle across the system.
    Tracks current workflow, stage, active agent, persona, channel metadata, and linked entities.
    """
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(String(50), default='web_ui', nullable=False)
    persona = Column(String(50), default='new_volunteer', nullable=False)
    workflow = Column(String(100), default='new_volunteer_onboarding', nullable=False)
    active_agent = Column(String(50), default='onboarding', nullable=False)
    status = Column(String(50), default='active', nullable=False)
    stage = Column(String(100), default='init', nullable=False)
    sub_state = Column(String(100), nullable=True)
    context_summary = Column(Text, nullable=True)
    channel_metadata = Column(JSON, nullable=True)
    
    # Linked entities
    volunteer_id = Column(UUID(as_uuid=True), nullable=True)
    coordinator_id = Column(UUID(as_uuid=True), nullable=True)
    need_id = Column(UUID(as_uuid=True), nullable=True)
    assignment_id = Column(UUID(as_uuid=True), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    events = relationship("SessionEvent", back_populates="session", cascade="all, delete-orphan")
    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan")
    profile = relationship("VolunteerProfile", back_populates="session", uselist=False, cascade="all, delete-orphan")


class SessionEvent(Base):
    """
    Tracks state transitions, routing decisions, agent handoffs, and important lifecycle events.
    """
    __tablename__ = "session_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)
    from_state = Column(String(100), nullable=True)
    to_state = Column(String(100), nullable=True)
    agent = Column(String(50), nullable=True)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    session = relationship("Session", back_populates="events")


class VolunteerProfile(Base):
    """
    Stores structured volunteer information captured during onboarding and later stages.
    """
    __tablename__ = "volunteer_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, unique=True)
    
    # Basic info
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)
    
    # Profile details
    skills = Column(ARRAY(String), default=list)
    interests = Column(ARRAY(String), default=list)
    availability = Column(String(100), nullable=True)
    experience_level = Column(String(50), nullable=True)
    motivation = Column(Text, nullable=True)
    preferred_causes = Column(ARRAY(String), default=list)
    
    # Status
    onboarding_completed = Column(Boolean, default=False)
    eligibility_status = Column(String(50), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    session = relationship("Session", back_populates="profile")


class ConversationMessage(Base):
    """
    Stores conversation history for sessions.
    """
    __tablename__ = "conversation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    agent = Column(String(50), nullable=True)
    message_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    session = relationship("Session", back_populates="messages")


class MemorySummary(Base):
    """
    Stores summarized long-term memory used by agents to preserve important context across sessions.
    """
    __tablename__ = "memory_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    volunteer_id = Column(UUID(as_uuid=True), nullable=True)
    summary_text = Column(Text, nullable=False)
    key_facts = Column(ARRAY(String), default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class HandoffEvent(Base):
    """
    Records transitions between agents or workflow stages, including routing metadata.
    """
    __tablename__ = "handoff_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    from_agent = Column(String(50), nullable=False)
    to_agent = Column(String(50), nullable=False)
    handoff_type = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TelemetryEvent(Base):
    """
    Stores operational telemetry such as routing events, MCP calls, system signals, and error traces.
    """
    __tablename__ = "telemetry_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(50), nullable=False)
    agent = Column(String(50), nullable=True)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
