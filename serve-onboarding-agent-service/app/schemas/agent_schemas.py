"""
SERVE Onboarding Agent Service - Schemas
Pydantic models for API contracts
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum


# ============ Enums ============

class AgentType(str, Enum):
    ONBOARDING = "onboarding"
    SELECTION = "selection"
    ENGAGEMENT = "engagement"
    NEED = "need"
    FULFILLMENT = "fulfillment"
    DELIVERY_ASSISTANT = "delivery_assistant"


class WorkflowType(str, Enum):
    NEW_VOLUNTEER_ONBOARDING = "new_volunteer_onboarding"
    RETURNING_VOLUNTEER = "returning_volunteer"
    NEED_COORDINATION = "need_coordination"
    VOLUNTEER_ENGAGEMENT = "volunteer_engagement"
    SYSTEM_TRIGGERED = "system_triggered"


class OnboardingState(str, Enum):
    WELCOME = "welcome"
    ORIENTATION_VIDEO = "orientation_video"
    ELIGIBILITY_SCREENING = "eligibility_screening"
    CONTACT_CAPTURE = "contact_capture"
    TEACHING_PROFILE = "teaching_profile"
    REGISTRATION_REVIEW = "registration_review"
    ONBOARDING_COMPLETE = "onboarding_complete"
    HUMAN_REVIEW = "human_review"
    PAUSED = "paused"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    ESCALATED = "escalated"


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


# ============ Session State Model ============

class SessionState(BaseModel):
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
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ============ Agent Turn Models ============

class AgentTurnRequest(BaseModel):
    """Request from orchestrator to agent"""
    session_id: UUID
    session_state: SessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = []


class HandoffEvent(BaseModel):
    """Handoff event from agent"""
    session_id: UUID
    from_agent: AgentType
    to_agent: AgentType
    handoff_type: HandoffType
    payload: Dict[str, Any] = {}
    reason: Optional[str] = None


class TelemetryEvent(BaseModel):
    """Telemetry event from agent"""
    session_id: UUID
    event_type: EventType
    agent: Optional[AgentType] = None
    data: Dict[str, Any] = {}


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
    handoff_event: Optional[HandoffEvent] = None
    telemetry_events: List[TelemetryEvent] = []


# ============ Health Response ============

class HealthResponse(BaseModel):
    service: str
    status: str
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
