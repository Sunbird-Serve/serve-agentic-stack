"""
SERVE MCP Server - Database Configuration
Async PostgreSQL connection using SQLAlchemy
"""
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, DateTime, JSON, Text, ForeignKey, Integer, Boolean, text
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

# Database URL from environment
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://serve:servepassword@localhost:5432/serve_db"
)

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Declarative base
Base = declarative_base()


# ============ SQLAlchemy Models ============

class Session(Base):
    """Volunteer session model"""
    __tablename__ = "sessions"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(String(50), nullable=False, default="web_ui")
    persona = Column(String(50), nullable=False, default="new_volunteer")
    workflow = Column(String(100), nullable=False, default="new_volunteer_onboarding")
    active_agent = Column(String(50), nullable=False, default="onboarding")
    status = Column(String(20), nullable=False, default="active")
    stage = Column(String(50), nullable=False, default="init")
    sub_state = Column(String(50), nullable=True)
    context_summary = Column(Text, nullable=True)
    channel_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class VolunteerProfile(Base):
    """Volunteer profile model - must match the existing PostgreSQL schema."""
    __tablename__ = "volunteer_profiles"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True, unique=True)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)
    skills = Column(PGARRAY(String), nullable=True)
    interests = Column(PGARRAY(String), nullable=True)
    availability = Column(String(100), nullable=True)
    experience_level = Column(String(50), nullable=True)
    motivation = Column(Text, nullable=True)
    preferred_causes = Column(PGARRAY(String), nullable=True)
    onboarding_completed = Column(Boolean, nullable=True)
    eligibility_status = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ConversationMessage(Base):
    """Conversation message model"""
    __tablename__ = "conversation_messages"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    agent = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MemorySummary(Base):
    """Memory summary model"""
    __tablename__ = "memory_summaries"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    volunteer_id = Column(PGUUID(as_uuid=True), nullable=True)
    summary_text = Column(Text, nullable=False)
    key_facts = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class TelemetryEvent(Base):
    """Telemetry event model"""
    __tablename__ = "telemetry_events"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(PGUUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False)
    event_type = Column(String(50), nullable=False)
    agent = Column(String(50), nullable=True)
    data = Column(JSON, default=dict, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============ Database Operations ============

async def init_db():
    """Initialize database and create tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")


async def close_db():
    """Close database connections"""
    await engine.dispose()
    logger.info("Database connections closed")


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session context manager"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Flag to track if using in-memory fallback
_using_memory_fallback = False

def is_using_memory_fallback() -> bool:
    """Check if we're using in-memory fallback"""
    return _using_memory_fallback


async def test_connection() -> bool:
    """Test database connection"""
    global _using_memory_fallback
    try:
        async with get_db() as db:
            await db.execute(text("SELECT 1"))
        _using_memory_fallback = False
        return True
    except Exception as e:
        logger.warning(f"Database connection failed, using in-memory fallback: {e}")
        _using_memory_fallback = True
        return False
