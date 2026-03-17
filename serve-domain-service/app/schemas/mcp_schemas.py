"""
SERVE Agentic MCP Service - Schemas
Pydantic models for API contracts
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


# ============ Enums ============

class ChannelType(str, Enum):
    WEB_UI = "web_ui"
    WHATSAPP = "whatsapp"
    API = "api"


class PersonaType(str, Enum):
    NEW_VOLUNTEER = "new_volunteer"
    RETURNING_VOLUNTEER = "returning_volunteer"
    INACTIVE_VOLUNTEER = "inactive_volunteer"
    NEED_COORDINATOR = "need_coordinator"
    SYSTEM = "system"


class WorkflowType(str, Enum):
    NEW_VOLUNTEER_ONBOARDING = "new_volunteer_onboarding"
    RETURNING_VOLUNTEER = "returning_volunteer"
    NEED_COORDINATION = "need_coordination"
    VOLUNTEER_ENGAGEMENT = "volunteer_engagement"
    SYSTEM_TRIGGERED = "system_triggered"


class AgentType(str, Enum):
    ONBOARDING = "onboarding"
    SELECTION = "selection"
    ENGAGEMENT = "engagement"
    NEED = "need"
    FULFILLMENT = "fulfillment"
    DELIVERY_ASSISTANT = "delivery_assistant"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    ESCALATED = "escalated"


class OnboardingState(str, Enum):
    INIT = "init"
    INTENT_DISCOVERY = "intent_discovery"
    PURPOSE_ORIENTATION = "purpose_orientation"
    ELIGIBILITY_CONFIRMATION = "eligibility_confirmation"
    CAPABILITY_DISCOVERY = "capability_discovery"
    PROFILE_CONFIRMATION = "profile_confirmation"
    ONBOARDING_COMPLETE = "onboarding_complete"
    PAUSED = "paused"


class HandoffType(str, Enum):
    AGENT_TRANSITION = "agent_transition"
    RESUME = "resume"
    ESCALATION = "escalation"
    PAUSE = "pause"


class EventType(str, Enum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    STATE_TRANSITION = "state_transition"
    MCP_CALL = "mcp_call"
    AGENT_RESPONSE = "agent_response"
    HANDOFF = "handoff"
    ERROR = "error"
    USER_MESSAGE = "user_message"


# ============ Request Models ============

class StartSessionRequest(BaseModel):
    channel: ChannelType = ChannelType.WEB_UI
    persona: PersonaType = PersonaType.NEW_VOLUNTEER
    channel_metadata: Optional[Dict[str, Any]] = None


class ResumeContextRequest(BaseModel):
    session_id: UUID


class AdvanceStateRequest(BaseModel):
    session_id: UUID
    new_state: str
    sub_state: Optional[str] = None


class GetMissingFieldsRequest(BaseModel):
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


class GetConversationRequest(BaseModel):
    session_id: UUID
    limit: int = 50


# ============ Response Models ============

class MCPResponse(BaseModel):
    status: str  # "success" | "error"
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    diagnostics: Optional[Dict[str, Any]] = None


class SessionData(BaseModel):
    id: UUID
    channel: str
    persona: str
    workflow: str
    active_agent: str
    status: str
    stage: str
    sub_state: Optional[str] = None
    context_summary: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None
    volunteer_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VolunteerProfileData(BaseModel):
    id: UUID
    session_id: Optional[UUID] = None
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
    onboarding_completed: bool = False
    eligibility_status: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HealthResponse(BaseModel):
    service: str
    status: str
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
