"""
SERVE Engagement Agent Service - Schemas

Workflow stages for returning volunteer re-engagement:

  RE_ENGAGING        — Warm welcome back and confirm whether they want to continue
  PROFILE_REFRESH    — Capture continuity preferences before downstream routing
  MATCHING_READY     — Legacy compatibility stage for handoff preparation
  HUMAN_REVIEW       — Sensitive / declined / ambiguous case
  PAUSED             — Volunteer wants to continue later
"""
import json
import logging
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum

logger = logging.getLogger(__name__)

_DEFAULT_SUB_STATE = {
    "engagement_context": {},
    "continue_decision": None,
    "same_school": None,
    "same_slot": None,
    "open_to_alternatives": None,
    "continuity": None,
    "preference_notes": None,
    "handoff": {},
    "human_review_reason": None,
}


class EngagementWorkflowState(str, Enum):
    """Stages in the returning-volunteer engagement workflow."""
    RE_ENGAGING     = "re_engaging"      # Initial re-contact, identity confirmation
    PROFILE_REFRESH = "profile_refresh"  # Capturing continuity preferences
    MATCHING_READY  = "matching_ready"   # Legacy handoff-prep stage
    HUMAN_REVIEW    = "human_review"     # Needs human follow-up or manual handling
    PAUSED          = "paused"           # Volunteer paused the session


class FulfillmentHandoffPayload(BaseModel):
    """Payload shape expected by the fulfillment agent."""
    volunteer_id: str
    volunteer_name: str
    continuity: Literal["same", "different"]
    preferred_need_id: Optional[str] = None
    preferred_school_id: Optional[str] = None
    preference_notes: Optional[str] = None
    fulfillment_history: List[Dict[str, Any]] = Field(default_factory=list)


class EngagementSessionState(BaseModel):
    """Current state of an engagement session."""
    id: UUID
    channel: str
    workflow: str = "returning_volunteer"
    active_agent: str = "engagement"
    status: str = "active"
    stage: str = EngagementWorkflowState.RE_ENGAGING.value
    sub_state: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None

    # Volunteer context (populated from MCP / Serve Registry)
    volunteer_id: Optional[str] = None       # Serve Registry osid
    volunteer_name: Optional[str] = None
    last_active_at: Optional[str] = None     # ISO datetime of last session


class EngagementAgentTurnRequest(BaseModel):
    """Request to process a turn in the engagement conversation."""
    session_id: UUID
    session_state: EngagementSessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    channel_metadata: Optional[Dict[str, Any]] = None


class EngagementAgentTurnResponse(BaseModel):
    """Response from the engagement agent."""
    assistant_message: str
    active_agent: str = "engagement"
    workflow: str = "returning_volunteer"
    state: str
    sub_state: Optional[str] = None
    completion_status: Optional[str] = None

    # Fields confirmed or updated during this turn
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)

    # Telemetry
    telemetry_events: List[Dict[str, Any]] = Field(default_factory=list)
    handoff_event: Optional[Dict[str, Any]] = None


def _load_sub_state(raw: Optional[str]) -> Dict[str, Any]:
    """Load sub_state from JSON string, defaulting on missing/malformed input."""
    if not raw:
        return dict(_DEFAULT_SUB_STATE)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return dict(_DEFAULT_SUB_STATE)
        return {
            "engagement_context": data.get("engagement_context", {}),
            "continue_decision": data.get("continue_decision"),
            "same_school": data.get("same_school"),
            "same_slot": data.get("same_slot"),
            "open_to_alternatives": data.get("open_to_alternatives"),
            "continuity": data.get("continuity"),
            "preference_notes": data.get("preference_notes"),
            "handoff": data.get("handoff", {}),
            "human_review_reason": data.get("human_review_reason"),
        }
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed engagement sub_state JSON — using defaults")
        return dict(_DEFAULT_SUB_STATE)


def _dump_sub_state(sub_state: Dict[str, Any]) -> str:
    """Serialize engagement sub_state to JSON string."""
    return json.dumps({
        "engagement_context": sub_state.get("engagement_context", {}),
        "continue_decision": sub_state.get("continue_decision"),
        "same_school": sub_state.get("same_school"),
        "same_slot": sub_state.get("same_slot"),
        "open_to_alternatives": sub_state.get("open_to_alternatives"),
        "continuity": sub_state.get("continuity"),
        "preference_notes": sub_state.get("preference_notes"),
        "handoff": sub_state.get("handoff", {}),
        "human_review_reason": sub_state.get("human_review_reason"),
    })
