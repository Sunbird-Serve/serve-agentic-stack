"""
SERVE Selection Agent Service - Schemas

Selection is the conversational evaluation step that follows onboarding.
It gathers readiness signals, decides the volunteer's immediate outcome,
and hands appropriate cases to engagement for the next step.
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


class SelectionWorkflowState(str, Enum):
    SELECTION_CONVERSATION = "selection_conversation"
    GATHERING_PREFERENCES = "gathering_preferences"
    HUMAN_REVIEW = "human_review"
    PAUSED = "paused"


class SelectionOutcome(str, Enum):
    RECOMMENDED = "recommended"
    ENGAGEMENT_LATER = "engagement_later"
    NOT_MATCHED = "not_matched"
    HUMAN_REVIEW = "human_review"
    PAUSED = "paused"


class EventType(str, Enum):
    MCP_CALL = "mcp_call"
    AGENT_RESPONSE = "agent_response"
    HANDOFF = "handoff"
    ERROR = "error"


DEFAULT_SELECTION_SUB_STATE: Dict[str, Any] = {
    "handoff": {},
    "signals": {
        "motivation_alignment": None,
        "continuity_intent": None,
        "communication_clarity": None,
        "language_comfort": None,
        "availability_realism": None,
        "readiness": None,
        "blockers": [],
        "risk_signals": [],
    },
    "notes": {
        "motivation": None,
        "availability": None,
        "blockers": None,
        "language_notes": None,
    },
    "asked_questions": [],
    "outcome": None,
    "outcome_reason": None,
}


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
    selection_signals: Dict[str, Any] = Field(default_factory=dict)


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


def load_selection_sub_state(raw_sub_state: Optional[str]) -> Dict[str, Any]:
    if not raw_sub_state:
        return json.loads(json.dumps(DEFAULT_SELECTION_SUB_STATE))
    try:
        data = json.loads(raw_sub_state)
    except (json.JSONDecodeError, ValueError):
        return json.loads(json.dumps(DEFAULT_SELECTION_SUB_STATE))
    if not isinstance(data, dict):
        return json.loads(json.dumps(DEFAULT_SELECTION_SUB_STATE))

    merged = json.loads(json.dumps(DEFAULT_SELECTION_SUB_STATE))
    merged.update(data)
    merged_signals = dict(DEFAULT_SELECTION_SUB_STATE["signals"])
    merged_signals.update(data.get("signals") or {})
    merged["signals"] = merged_signals
    merged_notes = dict(DEFAULT_SELECTION_SUB_STATE["notes"])
    merged_notes.update(data.get("notes") or {})
    merged["notes"] = merged_notes
    merged["asked_questions"] = list(data.get("asked_questions") or [])
    return merged


def dump_selection_sub_state(sub_state: Dict[str, Any]) -> str:
    return json.dumps(
        {
            "handoff": sub_state.get("handoff", {}),
            "signals": sub_state.get("signals", {}),
            "notes": sub_state.get("notes", {}),
            "asked_questions": list(sub_state.get("asked_questions") or []),
            "outcome": sub_state.get("outcome"),
            "outcome_reason": sub_state.get("outcome_reason"),
        }
    )
