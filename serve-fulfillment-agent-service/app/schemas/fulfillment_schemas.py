"""
SERVE Fulfillment Agent Service - Schemas

Workflow states for L4 volunteer-to-need matching:

  ACTIVE       — L4 loop running, LLM has full autonomy
  COMPLETE     — Nomination submitted. Terminal.
  HUMAN_REVIEW — No match or volunteer declined. Terminal.
  PAUSED       — Volunteer wants to continue later. Resumable.
"""
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_SUB_STATE = {"handoff": {}, "nominated_need_id": None, "human_review_reason": None, "match_result": None}


class FulfillmentWorkflowState(str, Enum):
    ACTIVE       = "active"
    COMPLETE     = "complete"
    HUMAN_REVIEW = "human_review"
    PAUSED       = "paused"


class HandoffPayload(BaseModel):
    volunteer_id: str
    volunteer_name: str
    continuity: Literal["same", "different"]
    preferred_need_id: Optional[str] = None
    preferred_school_id: Optional[str] = None
    preference_notes: Optional[str] = None
    fulfillment_history: List[Dict[str, Any]] = Field(default_factory=list)


class FulfillmentSessionState(BaseModel):
    id: UUID
    channel: str
    workflow: str = "returning_volunteer"
    active_agent: str = "fulfillment"
    status: str = "active"
    stage: str = FulfillmentWorkflowState.ACTIVE.value
    sub_state: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None
    volunteer_id: Optional[str] = None
    volunteer_name: Optional[str] = None


class FulfillmentAgentTurnRequest(BaseModel):
    session_id: UUID
    session_state: FulfillmentSessionState
    user_message: str
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    channel_metadata: Optional[Dict[str, Any]] = None


class FulfillmentAgentTurnResponse(BaseModel):
    assistant_message: str
    active_agent: str = "fulfillment"
    workflow: str = "returning_volunteer"
    state: str
    sub_state: Optional[str] = None
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
            "handoff": data.get("handoff", {}),
            "nominated_need_id": data.get("nominated_need_id"),
            "human_review_reason": data.get("human_review_reason"),
            "match_result": data.get("match_result"),
        }
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed sub_state JSON — using defaults")
        return dict(_DEFAULT_SUB_STATE)


def _dump_sub_state(sub_state: Dict[str, Any]) -> str:
    """Serialize sub_state to JSON string."""
    return json.dumps({
        "handoff": sub_state.get("handoff", {}),
        "nominated_need_id": sub_state.get("nominated_need_id"),
        "human_review_reason": sub_state.get("human_review_reason"),
        "match_result": sub_state.get("match_result"),
    })
