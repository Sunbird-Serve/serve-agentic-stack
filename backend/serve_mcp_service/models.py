"""
SERVE AI - Database Models
SQLAlchemy ORM models for all core entities
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text, Boolean, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship

from .database import Base
from shared.enums import (
    AgentType, WorkflowType, SessionStatus, ChannelType,
    PersonaType, HandoffType, EventType, OnboardingState
)


class Session(Base):
    """
    Represents an interaction lifecycle across the system.
    Tracks current workflow, stage, active agent, persona, channel metadata, and linked entities.
    """
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(SQLEnum(ChannelType), default=ChannelType.WEB_UI, nullable=False)
    persona = Column(SQLEnum(PersonaType), default=PersonaType.NEW_VOLUNTEER, nullable=False)
    workflow = Column(SQLEnum(WorkflowType), default=WorkflowType.NEW_VOLUNTEER_ONBOARDING, nullable=False)
    active_agent = Column(SQLEnum(AgentType), default=AgentType.ONBOARDING, nullable=False)
    status = Column(SQLEnum(SessionStatus), default=SessionStatus.ACTIVE, nullable=False)
    stage = Column(String(100), default=OnboardingState.INIT.value, nullable=False)
    sub_state = Column(String(100), nullable=True)
    context_summary = Column(Text, nullable=True)
    channel_metadata = Column(JSON, nullable=True)
    
    # Linked entities
    volunteer_id = Column(UUID(as_uuid=True), ForeignKey("volunteer_profiles.id"), nullable=True)
    coordinator_id = Column(UUID(as_uuid=True), nullable=True)
    need_id = Column(UUID(as_uuid=True), nullable=True)
    assignment_id = Column(UUID(as_uuid=True), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    events = relationship("SessionEvent", back_populates="session", cascade="all, delete-orphan")
    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan")
    volunteer_profile = relationship("VolunteerProfile", back_populates="session", uselist=False)


class SessionEvent(Base):
    """
    Tracks state transitions, routing decisions, agent handoffs, and important lifecycle events.
    """
    __tablename__ = "session_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    event_type = Column(String(50), nullable=False)
    from_state = Column(String(100), nullable=True)
    to_state = Column(String(100), nullable=True)
    agent = Column(SQLEnum(AgentType), nullable=True)
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
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    
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
    session = relationship("Session", back_populates="volunteer_profile")


class ConversationMessage(Base):
    """
    Stores conversation history for sessions.
    """
    __tablename__ = "conversation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    agent = Column(SQLEnum(AgentType), nullable=True)
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
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    volunteer_id = Column(UUID(as_uuid=True), ForeignKey("volunteer_profiles.id"), nullable=True)
    summary_text = Column(Text, nullable=False)
    key_facts = Column(ARRAY(String), default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class HandoffEventRecord(Base):
    """
    Records transitions between agents or workflow stages, including routing metadata.
    """
    __tablename__ = "handoff_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    from_agent = Column(SQLEnum(AgentType), nullable=False)
    to_agent = Column(SQLEnum(AgentType), nullable=False)
    handoff_type = Column(SQLEnum(HandoffType), nullable=False)
    payload = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TelemetryEventRecord(Base):
    """
    Stores operational telemetry such as routing events, MCP calls, system signals, and error traces.
    """
    __tablename__ = "telemetry_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    event_type = Column(SQLEnum(EventType), nullable=False)
    agent = Column(SQLEnum(AgentType), nullable=True)
    data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
