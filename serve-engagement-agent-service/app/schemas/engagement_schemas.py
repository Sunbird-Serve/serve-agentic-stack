"""
SERVE Engagement Agent Service - Schemas

Workflow stages for returning volunteer re-engagement:

  RE_ENGAGING   — Active conversation: welcome back, capture preferences
  HUMAN_REVIEW  — Terminal: declined, already active, or missing context
  PAUSED        — Volunteer deferred; session preserved for later
"""
import json
import logging
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
from enum import Enum

logger = logging.getLogger(__name__)

_DEFAULT_SUB_STATE: Dict[str, Any] = {
    "engagement_context": {},   # cached from get_engagement_context MCP tool
    "preference_notes": None,   # LLM-captured natural language preference summary
    "continuity": None,         # "same" | "different"
    "preferred_need_id": None,  # need_id from history if continuity=same
    "available_from": None,     # "immediately" | ISO date | natural language
    "handoff": {},              # FulfillmentHandoffPayload once ready
    "human_review_reason": None,
    "deferred": False,
}


class EngagementWorkflowState(str, Enum):
    RE_ENGAGING  = "re_engaging"   # Active LLM loop
    HUMAN_REVIEW = "human_review"  # Terminal
    PAUSED       = "paused"        # Deferred


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

    volunteer_id: Optional[str] = None
    volunteer_name: Optional[str] = None
    volunteer_phone: Optional[str] = None
    last_active_at: Optional[str] = None

    @field_validator("volunteer_id", mode="before")
    @classmethod
    def coerce_volunteer_id(cls, v):
        return str(v) if v is not None else None


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
    auto_continue: bool = False         # UI should auto-fire a follow-up request
    active_agent: str = "engagement"
    workflow: str = "returning_volunteer"
    state: str
    sub_state: Optional[str] = None
    completion_status: Optional[str] = None
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)
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
            "preference_notes":   data.get("preference_notes"),
            "continuity":         data.get("continuity"),
            "preferred_need_id":  data.get("preferred_need_id"),
            "available_from":     data.get("available_from"),
            "handoff":            data.get("handoff", {}),
            "human_review_reason": data.get("human_review_reason"),
            "deferred":           data.get("deferred", False),
        }
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed engagement sub_state JSON — using defaults")
        return dict(_DEFAULT_SUB_STATE)


def _dump_sub_state(sub_state: Dict[str, Any]) -> str:
    """Serialize engagement sub_state to JSON string."""
    return json.dumps({
        "engagement_context":  sub_state.get("engagement_context", {}),
        "preference_notes":    sub_state.get("preference_notes"),
        "continuity":          sub_state.get("continuity"),
        "preferred_need_id":   sub_state.get("preferred_need_id"),
        "available_from":      sub_state.get("available_from"),
        "handoff":             sub_state.get("handoff", {}),
        "human_review_reason": sub_state.get("human_review_reason"),
        "deferred":            sub_state.get("deferred", False),
    })
