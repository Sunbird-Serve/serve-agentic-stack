"""
SERVE AI - MCP Onboarding Capabilities
Domain capabilities for the onboarding workflow
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel

from .database import get_db
from .models import (
    Session, SessionEvent, VolunteerProfile, ConversationMessage,
    MemorySummary, HandoffEventRecord, TelemetryEventRecord
)
from shared.enums import (
    AgentType, WorkflowType, OnboardingState, SessionStatus,
    ChannelType, PersonaType, HandoffType, EventType
)
from shared.contracts import MCPResponse, SessionState, HandoffEvent, TelemetryEvent

router = APIRouter(prefix="/capabilities/onboarding", tags=["MCP Onboarding"])


# ============ Request Models ============

class ResumeContextRequest(BaseModel):
    session_id: UUID


class StartSessionRequest(BaseModel):
    channel: ChannelType = ChannelType.WEB_UI
    persona: PersonaType = PersonaType.NEW_VOLUNTEER
    channel_metadata: Optional[Dict[str, Any]] = None


class AdvanceStateRequest(BaseModel):
    session_id: UUID
    new_state: str
    sub_state: Optional[str] = None


class ExtractProfileRequest(BaseModel):
    session_id: UUID
    message: str


class GetMissingFieldsRequest(BaseModel):
    session_id: UUID


class EvaluatePrerequisitesRequest(BaseModel):
    session_id: UUID


class EvaluateReadinessRequest(BaseModel):
    session_id: UUID


class SaveConfirmedFieldsRequest(BaseModel):
    session_id: UUID
    fields: Dict[str, Any]


class PauseSessionRequest(BaseModel):
    session_id: UUID
    reason: Optional[str] = None


class PrepareHandoffRequest(BaseModel):
    session_id: UUID
    target_agent: AgentType


class EmitHandoffRequest(BaseModel):
    session_id: UUID
    from_agent: AgentType
    to_agent: AgentType
    handoff_type: HandoffType
    payload: Dict[str, Any] = {}
    reason: Optional[str] = None


class LogEventRequest(BaseModel):
    session_id: UUID
    event_type: EventType
    agent: Optional[AgentType] = None
    data: Dict[str, Any] = {}


class SaveMessageRequest(BaseModel):
    session_id: UUID
    role: str
    content: str
    agent: Optional[AgentType] = None
    message_metadata: Optional[Dict[str, Any]] = None


class GetConversationRequest(BaseModel):
    session_id: UUID
    limit: int = 50


# ============ Capability Endpoints ============

@router.post("/resume-context", response_model=MCPResponse)
async def resume_context(request: ResumeContextRequest, db: AsyncSession = Depends(get_db)):
    """Resume context for an existing session"""
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.volunteer_profile))
        .where(Session.id == request.session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    # Get conversation history
    messages_result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.session_id == request.session_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(10)
    )
    messages = messages_result.scalars().all()
    
    # Get memory summary
    memory_result = await db.execute(
        select(MemorySummary)
        .where(MemorySummary.session_id == request.session_id)
        .order_by(MemorySummary.created_at.desc())
        .limit(1)
    )
    memory = memory_result.scalar_one_or_none()
    
    return MCPResponse(
        status="success",
        data={
            "session": {
                "id": str(session.id),
                "stage": session.stage,
                "sub_state": session.sub_state,
                "status": session.status.value,
                "active_agent": session.active_agent.value,
                "workflow": session.workflow.value,
                "context_summary": session.context_summary,
            },
            "volunteer_profile": {
                "full_name": session.volunteer_profile.full_name if session.volunteer_profile else None,
                "email": session.volunteer_profile.email if session.volunteer_profile else None,
                "skills": session.volunteer_profile.skills if session.volunteer_profile else [],
            } if session.volunteer_profile else None,
            "conversation_history": [
                {"role": m.role, "content": m.content} for m in reversed(messages)
            ],
            "memory_summary": memory.summary_text if memory else None,
        }
    )


@router.post("/start-session", response_model=MCPResponse)
async def start_session(request: StartSessionRequest, db: AsyncSession = Depends(get_db)):
    """Start a new onboarding session"""
    # Create session
    session = Session(
        channel=request.channel,
        persona=request.persona,
        workflow=WorkflowType.NEW_VOLUNTEER_ONBOARDING,
        active_agent=AgentType.ONBOARDING,
        status=SessionStatus.ACTIVE,
        stage=OnboardingState.INIT.value,
        channel_metadata=request.channel_metadata
    )
    db.add(session)
    
    # Create volunteer profile
    profile = VolunteerProfile(session_id=session.id)
    db.add(profile)
    
    # Log session start event
    event = TelemetryEventRecord(
        session_id=session.id,
        event_type=EventType.SESSION_START,
        agent=AgentType.ONBOARDING,
        data={"channel": request.channel.value, "persona": request.persona.value}
    )
    db.add(event)
    
    await db.commit()
    await db.refresh(session)
    
    return MCPResponse(
        status="success",
        data={
            "session_id": str(session.id),
            "stage": session.stage,
            "status": session.status.value,
        }
    )


@router.post("/advance-state", response_model=MCPResponse)
async def advance_state(request: AdvanceStateRequest, db: AsyncSession = Depends(get_db)):
    """Advance session to a new state"""
    result = await db.execute(
        select(Session).where(Session.id == request.session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    old_state = session.stage
    
    # Create state transition event
    event = SessionEvent(
        session_id=session.id,
        event_type="state_transition",
        from_state=old_state,
        to_state=request.new_state,
        agent=session.active_agent
    )
    db.add(event)
    
    # Update session
    session.stage = request.new_state
    session.sub_state = request.sub_state
    session.updated_at = datetime.utcnow()
    
    # Check for completion
    if request.new_state == OnboardingState.ONBOARDING_COMPLETE.value:
        session.status = SessionStatus.COMPLETED
    
    await db.commit()
    
    return MCPResponse(
        status="success",
        data={
            "session_id": str(session.id),
            "previous_state": old_state,
            "current_state": request.new_state,
            "sub_state": request.sub_state,
        }
    )


@router.post("/extract-candidate-profile", response_model=MCPResponse)
async def extract_candidate_profile(request: ExtractProfileRequest, db: AsyncSession = Depends(get_db)):
    """Extract profile information from user message (placeholder for NLP extraction)"""
    # This would use NLP to extract structured data from messages
    # For now, return a placeholder indicating extraction capability
    return MCPResponse(
        status="success",
        data={
            "extracted_fields": {},
            "confidence": 0.0,
            "message": "Profile extraction placeholder - implement NLP logic"
        },
        diagnostics={"message_length": len(request.message)}
    )


@router.post("/get-missing-fields", response_model=MCPResponse)
async def get_missing_fields(request: GetMissingFieldsRequest, db: AsyncSession = Depends(get_db)):
    """Get list of missing required fields for the volunteer profile"""
    result = await db.execute(
        select(VolunteerProfile).where(VolunteerProfile.session_id == request.session_id)
    )
    profile = result.scalar_one_or_none()
    
    required_fields = ["full_name", "email", "location", "skills", "availability"]
    missing = []
    confirmed = {}
    
    if profile:
        for field in required_fields:
            value = getattr(profile, field, None)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
            else:
                confirmed[field] = value
    else:
        missing = required_fields
    
    return MCPResponse(
        status="success",
        data={
            "missing_fields": missing,
            "confirmed_fields": confirmed,
            "completion_percentage": round((len(confirmed) / len(required_fields)) * 100)
        }
    )


@router.post("/evaluate-prerequisites", response_model=MCPResponse)
async def evaluate_prerequisites(request: EvaluatePrerequisitesRequest, db: AsyncSession = Depends(get_db)):
    """Evaluate if prerequisites for onboarding are met"""
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.volunteer_profile))
        .where(Session.id == request.session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    prerequisites_met = True
    issues = []
    
    # Basic checks
    if session.status != SessionStatus.ACTIVE:
        prerequisites_met = False
        issues.append("Session is not active")
    
    return MCPResponse(
        status="success",
        data={
            "prerequisites_met": prerequisites_met,
            "issues": issues,
        }
    )


@router.post("/evaluate-readiness", response_model=MCPResponse)
async def evaluate_readiness(request: EvaluateReadinessRequest, db: AsyncSession = Depends(get_db)):
    """Evaluate if volunteer is ready to proceed to selection"""
    result = await db.execute(
        select(VolunteerProfile).where(VolunteerProfile.session_id == request.session_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        return MCPResponse(status="error", error="Profile not found")
    
    required_fields = ["full_name", "email", "skills", "availability"]
    missing = []
    
    for field in required_fields:
        value = getattr(profile, field, None)
        if not value or (isinstance(value, list) and len(value) == 0):
            missing.append(field)
    
    ready = len(missing) == 0
    
    return MCPResponse(
        status="success",
        data={
            "ready_for_selection": ready,
            "missing_fields": missing,
            "recommendation": "proceed" if ready else "gather_more_info"
        }
    )


@router.post("/save-confirmed-fields", response_model=MCPResponse)
async def save_confirmed_fields(request: SaveConfirmedFieldsRequest, db: AsyncSession = Depends(get_db)):
    """Save confirmed profile fields"""
    result = await db.execute(
        select(VolunteerProfile).where(VolunteerProfile.session_id == request.session_id)
    )
    profile = result.scalar_one_or_none()
    
    if not profile:
        return MCPResponse(status="error", error="Profile not found")
    
    # Update profile fields
    for field, value in request.fields.items():
        if hasattr(profile, field):
            setattr(profile, field, value)
    
    profile.updated_at = datetime.utcnow()
    await db.commit()
    
    return MCPResponse(
        status="success",
        data={
            "saved_fields": list(request.fields.keys()),
        }
    )


@router.post("/pause-session", response_model=MCPResponse)
async def pause_session(request: PauseSessionRequest, db: AsyncSession = Depends(get_db)):
    """Pause an active session"""
    result = await db.execute(
        select(Session).where(Session.id == request.session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    session.status = SessionStatus.PAUSED
    session.stage = OnboardingState.PAUSED.value
    session.updated_at = datetime.utcnow()
    
    # Log pause event
    event = SessionEvent(
        session_id=session.id,
        event_type="session_paused",
        from_state=session.stage,
        to_state=OnboardingState.PAUSED.value,
        data={"reason": request.reason}
    )
    db.add(event)
    
    await db.commit()
    
    return MCPResponse(
        status="success",
        data={
            "session_id": str(session.id),
            "status": "paused",
            "reason": request.reason
        }
    )


@router.post("/prepare-selection-handoff", response_model=MCPResponse)
async def prepare_selection_handoff(request: PrepareHandoffRequest, db: AsyncSession = Depends(get_db)):
    """Prepare handoff payload for selection agent"""
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.volunteer_profile))
        .where(Session.id == request.session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    profile = session.volunteer_profile
    
    handoff_payload = {
        "session_id": str(session.id),
        "volunteer_profile": {
            "full_name": profile.full_name if profile else None,
            "email": profile.email if profile else None,
            "skills": profile.skills if profile else [],
            "interests": profile.interests if profile else [],
            "availability": profile.availability if profile else None,
            "experience_level": profile.experience_level if profile else None,
        },
        "onboarding_summary": session.context_summary,
        "workflow": session.workflow.value,
    }
    
    return MCPResponse(
        status="success",
        data={
            "handoff_payload": handoff_payload,
            "target_agent": request.target_agent.value,
        }
    )


@router.post("/emit-handoff-event", response_model=MCPResponse)
async def emit_handoff_event(request: EmitHandoffRequest, db: AsyncSession = Depends(get_db)):
    """Record a handoff event"""
    handoff = HandoffEventRecord(
        session_id=request.session_id,
        from_agent=request.from_agent,
        to_agent=request.to_agent,
        handoff_type=request.handoff_type,
        payload=request.payload,
        reason=request.reason
    )
    db.add(handoff)
    
    # Update session's active agent
    await db.execute(
        update(Session)
        .where(Session.id == request.session_id)
        .values(active_agent=request.to_agent, updated_at=datetime.utcnow())
    )
    
    await db.commit()
    
    return MCPResponse(
        status="success",
        data={
            "handoff_id": str(handoff.id),
            "from_agent": request.from_agent.value,
            "to_agent": request.to_agent.value,
        }
    )


@router.post("/log-event", response_model=MCPResponse)
async def log_event(request: LogEventRequest, db: AsyncSession = Depends(get_db)):
    """Log a telemetry event"""
    event = TelemetryEventRecord(
        session_id=request.session_id,
        event_type=request.event_type,
        agent=request.agent,
        data=request.data
    )
    db.add(event)
    await db.commit()
    
    return MCPResponse(
        status="success",
        data={
            "event_id": str(event.id),
            "event_type": request.event_type.value,
        }
    )


@router.post("/save-message", response_model=MCPResponse)
async def save_message(request: SaveMessageRequest, db: AsyncSession = Depends(get_db)):
    """Save a conversation message"""
    message = ConversationMessage(
        session_id=request.session_id,
        role=request.role,
        content=request.content,
        agent=request.agent,
        message_metadata=request.message_metadata
    )
    db.add(message)
    await db.commit()
    
    return MCPResponse(
        status="success",
        data={
            "message_id": str(message.id),
        }
    )


@router.post("/get-conversation", response_model=MCPResponse)
async def get_conversation(request: GetConversationRequest, db: AsyncSession = Depends(get_db)):
    """Get conversation history for a session"""
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.session_id == request.session_id)
        .order_by(ConversationMessage.created_at)
        .limit(request.limit)
    )
    messages = result.scalars().all()
    
    return MCPResponse(
        status="success",
        data={
            "messages": [
                {
                    "id": str(m.id),
                    "role": m.role,
                    "content": m.content,
                    "agent": m.agent.value if m.agent else None,
                    "timestamp": m.created_at.isoformat(),
                }
                for m in messages
            ]
        }
    )


@router.get("/session/{session_id}", response_model=MCPResponse)
async def get_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get full session state"""
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.volunteer_profile))
        .where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    return MCPResponse(
        status="success",
        data={
            "session": {
                "id": str(session.id),
                "channel": session.channel.value,
                "persona": session.persona.value,
                "workflow": session.workflow.value,
                "active_agent": session.active_agent.value,
                "status": session.status.value,
                "stage": session.stage,
                "sub_state": session.sub_state,
                "context_summary": session.context_summary,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
            },
            "volunteer_profile": {
                "id": str(session.volunteer_profile.id) if session.volunteer_profile else None,
                "full_name": session.volunteer_profile.full_name if session.volunteer_profile else None,
                "email": session.volunteer_profile.email if session.volunteer_profile else None,
                "phone": session.volunteer_profile.phone if session.volunteer_profile else None,
                "location": session.volunteer_profile.location if session.volunteer_profile else None,
                "skills": session.volunteer_profile.skills if session.volunteer_profile else [],
                "interests": session.volunteer_profile.interests if session.volunteer_profile else [],
                "availability": session.volunteer_profile.availability if session.volunteer_profile else None,
                "onboarding_completed": session.volunteer_profile.onboarding_completed if session.volunteer_profile else False,
            } if session.volunteer_profile else None
        }
    )


@router.get("/sessions", response_model=MCPResponse)
async def list_sessions(
    status: Optional[SessionStatus] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """List all sessions with optional status filter"""
    query = select(Session).options(selectinload(Session.volunteer_profile))
    
    if status:
        query = query.where(Session.status == status)
    
    query = query.order_by(Session.created_at.desc()).limit(limit)
    
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    return MCPResponse(
        status="success",
        data={
            "sessions": [
                {
                    "id": str(s.id),
                    "status": s.status.value,
                    "stage": s.stage,
                    "active_agent": s.active_agent.value,
                    "volunteer_name": s.volunteer_profile.full_name if s.volunteer_profile else None,
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in sessions
            ]
        }
    )


@router.get("/telemetry/{session_id}", response_model=MCPResponse)
async def get_telemetry(session_id: UUID, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Get telemetry events for a session"""
    result = await db.execute(
        select(TelemetryEventRecord)
        .where(TelemetryEventRecord.session_id == session_id)
        .order_by(TelemetryEventRecord.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    
    return MCPResponse(
        status="success",
        data={
            "events": [
                {
                    "id": str(e.id),
                    "event_type": e.event_type.value,
                    "agent": e.agent.value if e.agent else None,
                    "data": e.data,
                    "timestamp": e.created_at.isoformat(),
                }
                for e in events
            ]
        }
    )
