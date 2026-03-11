"""
SERVE AI - Shared Contracts
Strongly typed request/response models
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4

from .enums import (
    AgentType, WorkflowType, OnboardingState, SessionStatus,
    ChannelType, PersonaType, HandoffType, EventType
)


# ============ Base Models ============

class TimestampMixin(BaseModel):
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============ Session Models ============

class SessionBase(BaseModel):
    channel: ChannelType = ChannelType.WEB_UI
    persona: PersonaType = PersonaType.NEW_VOLUNTEER
    workflow: WorkflowType = WorkflowType.NEW_VOLUNTEER_ONBOARDING
    active_agent: AgentType = AgentType.ONBOARDING
    status: SessionStatus = SessionStatus.ACTIVE


class SessionCreate(SessionBase):
    channel_metadata: Optional[Dict[str, Any]] = None
    volunteer_id: Optional[UUID] = None


class SessionState(SessionBase):
    id: UUID
    stage: str = OnboardingState.INIT.value
    sub_state: Optional[str] = None
    context_summary: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None
    volunteer_id: Optional[UUID] = None
    coordinator_id: Optional[UUID] = None
    need_id: Optional[UUID] = None
    assignment_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ Interaction Models ============

class InteractionRequest(BaseModel):
    """Request from channel to orchestrator"""
    session_id: Optional[UUID] = None
    message: str
    channel: ChannelType = ChannelType.WEB_UI
    channel_metadata: Optional[Dict[str, Any]] = None
    persona: Optional[PersonaType] = None


class InteractionResponse(BaseModel):
    """Response from orchestrator to channel"""
    session_id: UUID
    assistant_message: str
    active_agent: AgentType
    workflow: WorkflowType
    state: str
    sub_state: Optional[str] = None
    status: SessionStatus
    journey_progress: Optional[Dict[str, Any]] = None
    debug_info: Optional[Dict[str, Any]] = None


# ============ Agent Turn Models ============

class AgentTurnRequest(BaseModel):
    """Request from orchestrator to agent"""
    session_id: UUID
    session_state: SessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = []


class AgentTurnResponse(BaseModel):
    """Response from agent to orchestrator"""
    assistant_message: str
    active_agent: AgentType
    workflow: WorkflowType
    state: str
    sub_state: Optional[str] = None
    completion_status: Optional[str] = None
    confirmed_fields: Dict[str, Any] = {}
    missing_fields: List[str] = []
    handoff_event: Optional["HandoffEvent"] = None
    telemetry_events: List["TelemetryEvent"] = []


# ============ Volunteer Profile ============

class VolunteerProfileBase(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    skills: List[str] = []
    interests: List[str] = []
    availability: Optional[str] = None
    experience_level: Optional[str] = None
    motivation: Optional[str] = None
    preferred_causes: List[str] = []


class VolunteerProfileCreate(VolunteerProfileBase):
    session_id: UUID


class VolunteerProfile(VolunteerProfileBase):
    id: UUID
    session_id: UUID
    onboarding_completed: bool = False
    eligibility_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ Handoff Event ============

class HandoffEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    from_agent: AgentType
    to_agent: AgentType
    handoff_type: HandoffType
    payload: Dict[str, Any] = {}
    reason: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============ Telemetry Event ============

class TelemetryEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    event_type: EventType
    agent: Optional[AgentType] = None
    data: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============ MCP Request/Response ============

class MCPRequest(BaseModel):
    """Generic MCP capability request"""
    session_id: UUID
    capability: str
    payload: Dict[str, Any] = {}


class MCPResponse(BaseModel):
    """Generic MCP capability response"""
    status: str  # "success" | "error" | "pending"
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    diagnostics: Optional[Dict[str, Any]] = None


# ============ Memory Summary ============

class MemorySummary(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    volunteer_id: Optional[UUID] = None
    summary_text: str
    key_facts: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============ Health Check ============

class HealthResponse(BaseModel):
    service: str
    status: str
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Forward references
AgentTurnResponse.model_rebuild()
