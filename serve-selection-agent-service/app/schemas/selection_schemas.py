"""
SERVE Selection Agent Service - Schemas

Selection is a lightweight post-onboarding evaluation agent.
It accepts the standard orchestrator turn contract, evaluates the
completed volunteer profile, and returns a concise next-step message.
"""
import json
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


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
    RECOMMENDED_VOLUNTEER = "recommended_volunteer"
    NEED_COORDINATION = "need_coordination"
    VOLUNTEER_ENGAGEMENT = "volunteer_engagement"
    SYSTEM_TRIGGERED = "system_triggered"


class SelectionOutcome(str, Enum):
    RECOMMEND = "recommend"
    NOT_RECOMMEND = "not_recommend"
    HOLD = "hold"


class EventType(str, Enum):
    MCP_CALL = "mcp_call"
    AGENT_RESPONSE = "agent_response"
    HANDOFF = "handoff"
    ERROR = "error"


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
    volunteer_name: Optional[str] = None
    volunteer_phone: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentTurnRequest(BaseModel):
    session_id: UUID
    session_state: SessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    intent_hint: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None


class TelemetryEvent(BaseModel):
    session_id: UUID
    event_type: EventType
    agent: Optional[AgentType] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class AgentTurnResponse(BaseModel):
    assistant_message: str
    active_agent: AgentType
    workflow: WorkflowType
    state: str
    sub_state: Optional[str] = None
    completion_status: Optional[str] = None
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    handoff_event: Optional[Dict[str, Any]] = None
    telemetry_events: List[TelemetryEvent] = Field(default_factory=list)


class VolunteerProfile(BaseModel):
    volunteer_id: Optional[str] = None
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    interests: List[str] = Field(default_factory=list)
    availability: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    motivation: Optional[str] = None
    qualification: Optional[str] = None
    years_of_experience: Optional[str] = None
    employment_status: Optional[str] = None


class SelectionEvaluateRequest(BaseModel):
    session_id: UUID
    volunteer_id: Optional[str] = None
    profile: VolunteerProfile
    onboarding_summary: Optional[str] = None
    key_facts: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SelectionEvaluateResponse(BaseModel):
    session_id: UUID
    volunteer_id: Optional[str] = None
    outcome: SelectionOutcome
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    reason: str = ""
    flags: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    evaluation_details: Dict[str, Any] = Field(default_factory=dict)


def extract_handoff_payload(raw_sub_state: Optional[str]) -> Dict[str, Any]:
    """Extract the orchestrator-persisted handoff payload from session sub_state."""
    if not raw_sub_state:
        return {}
    try:
        data = json.loads(raw_sub_state)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    handoff = data.get("handoff")
    return handoff if isinstance(handoff, dict) else {}
