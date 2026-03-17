"""
SERVE Agentic MCP Service - Onboarding Capabilities API
HTTP endpoints for onboarding domain capabilities
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel

from app.db import get_db
from app.service import onboarding_capability_service
from app.schemas import (
    MCPResponse, StartSessionRequest, ResumeContextRequest,
    AdvanceStateRequest, GetMissingFieldsRequest, SaveConfirmedFieldsRequest,
    PauseSessionRequest, PrepareHandoffRequest, EmitHandoffRequest,
    LogEventRequest, SaveMessageRequest, GetConversationRequest, HealthResponse
)
from datetime import datetime

router = APIRouter(prefix="/capabilities/onboarding", tags=["Onboarding Capabilities"])


@router.post("/start-session", response_model=MCPResponse)
async def start_session(request: StartSessionRequest, db: AsyncSession = Depends(get_db)):
    """Start a new onboarding session"""
    return await onboarding_capability_service.start_session(db, request)


@router.post("/resume-context", response_model=MCPResponse)
async def resume_context(request: ResumeContextRequest, db: AsyncSession = Depends(get_db)):
    """Resume context for an existing session"""
    return await onboarding_capability_service.resume_context(db, request.session_id)


@router.post("/advance-state", response_model=MCPResponse)
async def advance_state(request: AdvanceStateRequest, db: AsyncSession = Depends(get_db)):
    """Advance session to a new state"""
    return await onboarding_capability_service.advance_state(db, request)


@router.post("/get-missing-fields", response_model=MCPResponse)
async def get_missing_fields(request: GetMissingFieldsRequest, db: AsyncSession = Depends(get_db)):
    """Get list of missing required fields"""
    return await onboarding_capability_service.get_missing_fields(db, request.session_id)


@router.post("/save-confirmed-fields", response_model=MCPResponse)
async def save_confirmed_fields(request: SaveConfirmedFieldsRequest, db: AsyncSession = Depends(get_db)):
    """Save confirmed profile fields"""
    return await onboarding_capability_service.save_confirmed_fields(db, request)


@router.post("/pause-session", response_model=MCPResponse)
async def pause_session(request: PauseSessionRequest, db: AsyncSession = Depends(get_db)):
    """Pause an active session"""
    return await onboarding_capability_service.pause_session(db, request.session_id, request.reason)


@router.post("/evaluate-prerequisites", response_model=MCPResponse)
async def evaluate_prerequisites(request: GetMissingFieldsRequest, db: AsyncSession = Depends(get_db)):
    """Evaluate if prerequisites for onboarding are met"""
    return await onboarding_capability_service.evaluate_prerequisites(db, request.session_id)


@router.post("/evaluate-readiness", response_model=MCPResponse)
async def evaluate_readiness(request: GetMissingFieldsRequest, db: AsyncSession = Depends(get_db)):
    """Evaluate if volunteer is ready to proceed to selection"""
    return await onboarding_capability_service.evaluate_readiness(db, request.session_id)


@router.post("/prepare-selection-handoff", response_model=MCPResponse)
async def prepare_selection_handoff(request: PrepareHandoffRequest, db: AsyncSession = Depends(get_db)):
    """Prepare handoff payload for selection agent"""
    return await onboarding_capability_service.prepare_selection_handoff(
        db, request.session_id, request.target_agent.value
    )


@router.post("/emit-handoff-event", response_model=MCPResponse)
async def emit_handoff_event(request: EmitHandoffRequest, db: AsyncSession = Depends(get_db)):
    """Record a handoff event"""
    return await onboarding_capability_service.emit_handoff_event(db, request)


@router.post("/log-event", response_model=MCPResponse)
async def log_event(request: LogEventRequest, db: AsyncSession = Depends(get_db)):
    """Log a telemetry event"""
    return await onboarding_capability_service.log_event(db, request)


@router.post("/save-message", response_model=MCPResponse)
async def save_message(request: SaveMessageRequest, db: AsyncSession = Depends(get_db)):
    """Save a conversation message"""
    return await onboarding_capability_service.save_message(db, request)


@router.post("/get-conversation", response_model=MCPResponse)
async def get_conversation(request: GetConversationRequest, db: AsyncSession = Depends(get_db)):
    """Get conversation history for a session"""
    return await onboarding_capability_service.get_conversation(db, request.session_id, request.limit)


@router.get("/session/{session_id}", response_model=MCPResponse)
async def get_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get full session state"""
    return await onboarding_capability_service.get_session(db, session_id)


@router.get("/sessions", response_model=MCPResponse)
async def list_sessions(
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """List all sessions with optional status filter"""
    return await onboarding_capability_service.list_sessions(db, status, limit)


@router.get("/telemetry/{session_id}", response_model=MCPResponse)
async def get_telemetry(session_id: UUID, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Get telemetry events for a session"""
    return await onboarding_capability_service.get_telemetry(db, session_id, limit)


# ============ Memory Summary Routes ============

class SaveMemorySummaryRequest(BaseModel):
    session_id: UUID
    summary_text: str
    key_facts: List[str] = []
    volunteer_id: Optional[UUID] = None

class GetMemorySummaryRequest(BaseModel):
    session_id: UUID


@router.post("/save-memory-summary", response_model=MCPResponse)
async def save_memory_summary(request: SaveMemorySummaryRequest, db: AsyncSession = Depends(get_db)):
    """Save a conversation memory summary for long-term context"""
    return await onboarding_capability_service.save_memory_summary(
        session_id=request.session_id,
        summary_text=request.summary_text,
        key_facts=request.key_facts,
        volunteer_id=request.volunteer_id,
        db=db
    )


@router.post("/get-memory-summary", response_model=MCPResponse)
async def get_memory_summary(request: GetMemorySummaryRequest, db: AsyncSession = Depends(get_db)):
    """Retrieve memory summary for a session"""
    return await onboarding_capability_service.get_memory_summary(
        session_id=request.session_id,
        db=db
    )


@router.get("/memory/{session_id}", response_model=MCPResponse)
async def get_session_memory(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get memory summary for a session (GET endpoint)"""
    return await onboarding_capability_service.get_memory_summary(
        session_id=session_id,
        db=db
    )


@router.get("/volunteer-memory/{volunteer_id}", response_model=MCPResponse)
async def get_volunteer_memory(volunteer_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get all memory summaries for a volunteer across sessions"""
    return await onboarding_capability_service.get_volunteer_memory(
        volunteer_id=volunteer_id,
        db=db
    )

