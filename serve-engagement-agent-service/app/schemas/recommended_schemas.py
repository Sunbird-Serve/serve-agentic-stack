"""
SERVE Engagement Agent Service - Recommended Volunteer Schemas

Workflow stages for recommended volunteer engagement:

  VERIFYING_IDENTITY    — Phone/email lookup to confirm registration
  GATHERING_PREFERENCES — Subject, school, time slot preferences
  HUMAN_REVIEW          — Terminal: declined, missing context, or loop exhausted
  PAUSED                — Volunteer deferred; session preserved for later
  NOT_REGISTERED        — Terminal: redirect to registration URL
"""
import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator
from enum import Enum

logger = logging.getLogger(__name__)


class RecommendedWorkflowState(str, Enum):
    VERIFYING_IDENTITY    = "verifying_identity"
    GATHERING_PREFERENCES = "gathering_preferences"
    HUMAN_REVIEW          = "human_review"
    PAUSED                = "paused"
    NOT_REGISTERED        = "not_registered"


_RECOMMENDED_DEFAULT_SUB_STATE: Dict[str, Any] = {
    "entry_type": "recommended",
    "engagement_context": {},
    "registration_url": None,
    "identity_verified": False,
    "preference_notes": None,
    "available_from": None,
    "handoff": {},
    "human_review_reason": None,
    "deferred": False,
    "deferred_reason": None,
}


class RecommendedSessionState(BaseModel):
    """Session state for recommended volunteer workflow."""
    id: UUID
    channel: str
    workflow: str = "recommended_volunteer"
    active_agent: str = "engagement"
    status: str = "active"
    stage: str = RecommendedWorkflowState.VERIFYING_IDENTITY.value
    sub_state: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None
    volunteer_id: Optional[str] = None
    volunteer_name: Optional[str] = None
    volunteer_phone: Optional[str] = None

    @field_validator("volunteer_id", mode="before")
    @classmethod
    def coerce_volunteer_id(cls, v):
        return str(v) if v is not None else None


class RecommendedAgentTurnRequest(BaseModel):
    """Request to process a turn in the recommended volunteer conversation."""
    session_id: UUID
    session_state: RecommendedSessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    channel_metadata: Optional[Dict[str, Any]] = None


class RecommendedAgentTurnResponse(BaseModel):
    """Response from the recommended volunteer handler."""
    assistant_message: str
    auto_continue: bool = False
    active_agent: str = "engagement"
    workflow: str = "recommended_volunteer"
    state: str
    sub_state: Optional[str] = None
    completion_status: Optional[str] = None
    confirmed_fields: Dict[str, Any] = Field(default_factory=dict)
    telemetry_events: List[Dict[str, Any]] = Field(default_factory=list)
    handoff_event: Optional[Dict[str, Any]] = None


def _load_recommended_sub_state(raw: Optional[str]) -> Dict[str, Any]:
    """Load recommended sub_state from JSON string, defaulting on missing/malformed input."""
    if not raw:
        return dict(_RECOMMENDED_DEFAULT_SUB_STATE)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return dict(_RECOMMENDED_DEFAULT_SUB_STATE)
        return {
            "entry_type": data.get("entry_type", "recommended"),
            "engagement_context": data.get("engagement_context", {}),
            "registration_url": data.get("registration_url"),
            "identity_verified": data.get("identity_verified", False),
            "preference_notes": data.get("preference_notes"),
            "available_from": data.get("available_from"),
            "handoff": data.get("handoff", {}),
            "human_review_reason": data.get("human_review_reason"),
            "deferred": data.get("deferred", False),
            "deferred_reason": data.get("deferred_reason"),
        }
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed recommended sub_state JSON — using defaults")
        return dict(_RECOMMENDED_DEFAULT_SUB_STATE)


def _dump_recommended_sub_state(sub_state: Dict[str, Any]) -> str:
    """Serialize recommended sub_state to JSON string."""
    return json.dumps({
        "entry_type": sub_state.get("entry_type", "recommended"),
        "engagement_context": sub_state.get("engagement_context", {}),
        "registration_url": sub_state.get("registration_url"),
        "identity_verified": sub_state.get("identity_verified", False),
        "preference_notes": sub_state.get("preference_notes"),
        "available_from": sub_state.get("available_from"),
        "handoff": sub_state.get("handoff", {}),
        "human_review_reason": sub_state.get("human_review_reason"),
        "deferred": sub_state.get("deferred", False),
        "deferred_reason": sub_state.get("deferred_reason"),
    })
