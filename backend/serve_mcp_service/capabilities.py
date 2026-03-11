"""
SERVE AI - MCP Onboarding Capabilities
Domain capabilities for the onboarding workflow (with in-memory fallback)
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel

from .database import get_db, is_db_available, in_memory_store
from .models import (
    Session, SessionEvent, VolunteerProfile, ConversationMessage,
    MemorySummary, HandoffEventRecord, TelemetryEventRecord
)
from shared.enums import (
    AgentType, WorkflowType, OnboardingState, SessionStatus,
    ChannelType, PersonaType, HandoffType, EventType
)
from shared.contracts import MCPResponse

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


# ============ In-Memory Helpers ============

def get_in_memory_session(session_id: str) -> Optional[Dict]:
    """Get session from in-memory store"""
    return in_memory_store.sessions.get(session_id)


def create_in_memory_session(channel: str, persona: str, channel_metadata: Optional[Dict]) -> Dict:
    """Create a new session in memory"""
    session_id = str(uuid4())
    now = datetime.utcnow().isoformat()
    
    session = {
        "id": session_id,
        "channel": channel,
        "persona": persona,
        "workflow": WorkflowType.NEW_VOLUNTEER_ONBOARDING.value,
        "active_agent": AgentType.ONBOARDING.value,
        "status": SessionStatus.ACTIVE.value,
        "stage": OnboardingState.INIT.value,
        "sub_state": None,
        "context_summary": None,
        "channel_metadata": channel_metadata,
        "created_at": now,
        "updated_at": now,
    }
    
    in_memory_store.sessions[session_id] = session
    
    # Create profile
    profile = {
        "id": str(uuid4()),
        "session_id": session_id,
        "full_name": None,
        "email": None,
        "phone": None,
        "location": None,
        "skills": [],
        "interests": [],
        "availability": None,
        "experience_level": None,
        "motivation": None,
        "preferred_causes": [],
        "onboarding_completed": False,
        "created_at": now,
    }
    in_memory_store.volunteer_profiles[session_id] = profile
    
    # Initialize messages list
    in_memory_store.messages[session_id] = []
    in_memory_store.telemetry[session_id] = []
    
    return session


# ============ Capability Endpoints ============

@router.post("/resume-context", response_model=MCPResponse)
async def resume_context(request: ResumeContextRequest, db: AsyncSession = Depends(get_db)):
    """Resume context for an existing session"""
    session_id = str(request.session_id)
    
    # Try in-memory first
    session = get_in_memory_session(session_id)
    profile = in_memory_store.volunteer_profiles.get(session_id)
    messages = in_memory_store.messages.get(session_id, [])
    
    if session:
        return MCPResponse(
            status="success",
            data={
                "session": session,
                "volunteer_profile": profile,
                "conversation_history": messages[-10:] if messages else [],
                "memory_summary": None,
            }
        )
    
    # Try database if available
    if db and is_db_available():
        try:
            result = await db.execute(
                select(Session)
                .options(selectinload(Session.volunteer_profile))
                .where(Session.id == request.session_id)
            )
            db_session = result.scalar_one_or_none()
            
            if db_session:
                messages_result = await db.execute(
                    select(ConversationMessage)
                    .where(ConversationMessage.session_id == request.session_id)
                    .order_by(ConversationMessage.created_at.desc())
                    .limit(10)
                )
                db_messages = messages_result.scalars().all()
                
                return MCPResponse(
                    status="success",
                    data={
                        "session": {
                            "id": str(db_session.id),
                            "stage": db_session.stage,
                            "sub_state": db_session.sub_state,
                            "status": db_session.status.value,
                            "active_agent": db_session.active_agent.value,
                            "workflow": db_session.workflow.value,
                            "context_summary": db_session.context_summary,
                        },
                        "volunteer_profile": {
                            "full_name": db_session.volunteer_profile.full_name if db_session.volunteer_profile else None,
                            "email": db_session.volunteer_profile.email if db_session.volunteer_profile else None,
                            "skills": db_session.volunteer_profile.skills if db_session.volunteer_profile else [],
                        } if db_session.volunteer_profile else None,
                        "conversation_history": [
                            {"role": m.role, "content": m.content} for m in reversed(db_messages)
                        ],
                        "memory_summary": None,
                    }
                )
        except Exception as e:
            pass
    
    return MCPResponse(status="error", error="Session not found")


@router.post("/start-session", response_model=MCPResponse)
async def start_session(request: StartSessionRequest, db: AsyncSession = Depends(get_db)):
    """Start a new onboarding session"""
    
    # Always use in-memory for reliability
    session = create_in_memory_session(
        channel=request.channel.value,
        persona=request.persona.value,
        channel_metadata=request.channel_metadata
    )
    
    # Also try to persist to DB if available
    if db and is_db_available():
        try:
            db_session = Session(
                id=UUID(session["id"]),
                channel=request.channel,
                persona=request.persona,
                workflow=WorkflowType.NEW_VOLUNTEER_ONBOARDING,
                active_agent=AgentType.ONBOARDING,
                status=SessionStatus.ACTIVE,
                stage=OnboardingState.INIT.value,
                channel_metadata=request.channel_metadata
            )
            db.add(db_session)
            
            profile = VolunteerProfile(session_id=db_session.id)
            db.add(profile)
            
            await db.commit()
        except Exception:
            pass
    
    return MCPResponse(
        status="success",
        data={
            "session_id": session["id"],
            "stage": session["stage"],
            "status": session["status"],
        }
    )


@router.post("/advance-state", response_model=MCPResponse)
async def advance_state(request: AdvanceStateRequest, db: AsyncSession = Depends(get_db)):
    """Advance session to a new state"""
    session_id = str(request.session_id)
    session = get_in_memory_session(session_id)
    
    if session:
        old_state = session["stage"]
        session["stage"] = request.new_state
        session["sub_state"] = request.sub_state
        session["updated_at"] = datetime.utcnow().isoformat()
        
        if request.new_state == OnboardingState.ONBOARDING_COMPLETE.value:
            session["status"] = SessionStatus.COMPLETED.value
        
        return MCPResponse(
            status="success",
            data={
                "session_id": session_id,
                "previous_state": old_state,
                "current_state": request.new_state,
                "sub_state": request.sub_state,
            }
        )
    
    return MCPResponse(status="error", error="Session not found")


@router.post("/extract-candidate-profile", response_model=MCPResponse)
async def extract_candidate_profile(request: ExtractProfileRequest, db: AsyncSession = Depends(get_db)):
    """Extract profile information from user message (placeholder for NLP extraction)"""
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
    session_id = str(request.session_id)
    profile = in_memory_store.volunteer_profiles.get(session_id)
    
    required_fields = ["full_name", "email", "location", "skills", "availability"]
    missing = []
    confirmed = {}
    
    if profile:
        for field in required_fields:
            value = profile.get(field)
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
    session_id = str(request.session_id)
    session = get_in_memory_session(session_id)
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    prerequisites_met = session["status"] == SessionStatus.ACTIVE.value
    
    return MCPResponse(
        status="success",
        data={
            "prerequisites_met": prerequisites_met,
            "issues": [] if prerequisites_met else ["Session is not active"],
        }
    )


@router.post("/evaluate-readiness", response_model=MCPResponse)
async def evaluate_readiness(request: EvaluateReadinessRequest, db: AsyncSession = Depends(get_db)):
    """Evaluate if volunteer is ready to proceed to selection"""
    session_id = str(request.session_id)
    profile = in_memory_store.volunteer_profiles.get(session_id)
    
    if not profile:
        return MCPResponse(status="error", error="Profile not found")
    
    required_fields = ["full_name", "email", "skills", "availability"]
    missing = []
    
    for field in required_fields:
        value = profile.get(field)
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
    session_id = str(request.session_id)
    profile = in_memory_store.volunteer_profiles.get(session_id)
    
    if not profile:
        # Create profile if it doesn't exist
        profile = {
            "id": str(uuid4()),
            "session_id": session_id,
            "full_name": None,
            "email": None,
            "phone": None,
            "location": None,
            "skills": [],
            "interests": [],
            "availability": None,
            "experience_level": None,
            "motivation": None,
            "preferred_causes": [],
            "onboarding_completed": False,
            "created_at": datetime.utcnow().isoformat(),
        }
        in_memory_store.volunteer_profiles[session_id] = profile
    
    # Update profile fields
    for field, value in request.fields.items():
        if field in profile:
            profile[field] = value
    
    return MCPResponse(
        status="success",
        data={
            "saved_fields": list(request.fields.keys()),
        }
    )


@router.post("/pause-session", response_model=MCPResponse)
async def pause_session(request: PauseSessionRequest, db: AsyncSession = Depends(get_db)):
    """Pause an active session"""
    session_id = str(request.session_id)
    session = get_in_memory_session(session_id)
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    session["status"] = SessionStatus.PAUSED.value
    session["stage"] = OnboardingState.PAUSED.value
    session["updated_at"] = datetime.utcnow().isoformat()
    
    return MCPResponse(
        status="success",
        data={
            "session_id": session_id,
            "status": "paused",
            "reason": request.reason
        }
    )


@router.post("/prepare-selection-handoff", response_model=MCPResponse)
async def prepare_selection_handoff(request: PrepareHandoffRequest, db: AsyncSession = Depends(get_db)):
    """Prepare handoff payload for selection agent"""
    session_id = str(request.session_id)
    session = get_in_memory_session(session_id)
    profile = in_memory_store.volunteer_profiles.get(session_id)
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    handoff_payload = {
        "session_id": session_id,
        "volunteer_profile": {
            "full_name": profile.get("full_name") if profile else None,
            "email": profile.get("email") if profile else None,
            "skills": profile.get("skills", []) if profile else [],
            "interests": profile.get("interests", []) if profile else [],
            "availability": profile.get("availability") if profile else None,
            "experience_level": profile.get("experience_level") if profile else None,
        },
        "onboarding_summary": session.get("context_summary"),
        "workflow": session["workflow"],
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
    session_id = str(request.session_id)
    session = get_in_memory_session(session_id)
    
    if session:
        session["active_agent"] = request.to_agent.value
        session["updated_at"] = datetime.utcnow().isoformat()
    
    handoff_id = str(uuid4())
    
    return MCPResponse(
        status="success",
        data={
            "handoff_id": handoff_id,
            "from_agent": request.from_agent.value,
            "to_agent": request.to_agent.value,
        }
    )


@router.post("/log-event", response_model=MCPResponse)
async def log_event(request: LogEventRequest, db: AsyncSession = Depends(get_db)):
    """Log a telemetry event"""
    session_id = str(request.session_id)
    event_id = str(uuid4())
    
    event = {
        "id": event_id,
        "session_id": session_id,
        "event_type": request.event_type.value,
        "agent": request.agent.value if request.agent else None,
        "data": request.data,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    if session_id not in in_memory_store.telemetry:
        in_memory_store.telemetry[session_id] = []
    in_memory_store.telemetry[session_id].append(event)
    
    return MCPResponse(
        status="success",
        data={
            "event_id": event_id,
            "event_type": request.event_type.value,
        }
    )


@router.post("/save-message", response_model=MCPResponse)
async def save_message(request: SaveMessageRequest, db: AsyncSession = Depends(get_db)):
    """Save a conversation message"""
    session_id = str(request.session_id)
    message_id = str(uuid4())
    
    message = {
        "id": message_id,
        "role": request.role,
        "content": request.content,
        "agent": request.agent.value if request.agent else None,
        "timestamp": datetime.utcnow().isoformat(),
    }
    
    if session_id not in in_memory_store.messages:
        in_memory_store.messages[session_id] = []
    in_memory_store.messages[session_id].append(message)
    
    return MCPResponse(
        status="success",
        data={
            "message_id": message_id,
        }
    )


@router.post("/get-conversation", response_model=MCPResponse)
async def get_conversation(request: GetConversationRequest, db: AsyncSession = Depends(get_db)):
    """Get conversation history for a session"""
    session_id = str(request.session_id)
    messages = in_memory_store.messages.get(session_id, [])
    
    return MCPResponse(
        status="success",
        data={
            "messages": messages[:request.limit]
        }
    )


@router.get("/session/{session_id}", response_model=MCPResponse)
async def get_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get full session state"""
    sid = str(session_id)
    session = get_in_memory_session(sid)
    profile = in_memory_store.volunteer_profiles.get(sid)
    
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    return MCPResponse(
        status="success",
        data={
            "session": session,
            "volunteer_profile": profile
        }
    )


@router.get("/sessions", response_model=MCPResponse)
async def list_sessions(
    status: Optional[SessionStatus] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """List all sessions with optional status filter"""
    sessions_list = []
    
    for sid, session in in_memory_store.sessions.items():
        if status and session["status"] != status.value:
            continue
        
        profile = in_memory_store.volunteer_profiles.get(sid, {})
        sessions_list.append({
            "id": sid,
            "status": session["status"],
            "stage": session["stage"],
            "active_agent": session["active_agent"],
            "volunteer_name": profile.get("full_name"),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        })
    
    # Sort by created_at descending
    sessions_list.sort(key=lambda x: x["created_at"], reverse=True)
    
    return MCPResponse(
        status="success",
        data={
            "sessions": sessions_list[:limit]
        }
    )


@router.get("/telemetry/{session_id}", response_model=MCPResponse)
async def get_telemetry(session_id: UUID, limit: int = 100, db: AsyncSession = Depends(get_db)):
    """Get telemetry events for a session"""
    sid = str(session_id)
    events = in_memory_store.telemetry.get(sid, [])
    
    # Sort by timestamp descending
    events_sorted = sorted(events, key=lambda x: x["timestamp"], reverse=True)
    
    return MCPResponse(
        status="success",
        data={
            "events": events_sorted[:limit]
        }
    )
