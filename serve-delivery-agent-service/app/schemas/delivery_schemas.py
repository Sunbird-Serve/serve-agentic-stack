"""
SERVE Delivery Agent Service - Schemas

State machines for the post-handshake delivery journey:

  Activation stages (session.stage during Mode 1 — activation):
    activation_started → volunteer_acknowledged → first_session_ready
    → activation_completed
    escapes: activation_blocked, paused, human_review

  Operations stage (session.stage during Mode 2 — daily ops):
    delivery_operations  (single orchestrator stage; per-session detail is in DB)
    terminal: delivery_complete

  Per-session states (tracked in the MCP DB, not here):
    upcoming → day_reminder_sent → pre_session_reminder_sent
    → completion_check_sent → {completed | partially_completed | missed
    | unverified | cancelled | reschedule_requested}
"""
import json
import logging
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

logger = logging.getLogger("delivery.schemas")

_DEFAULT_SUB_STATE = {"delivery_id": None, "mode": "activation", "escalation_reason": None}


class ActivationStage(str, Enum):
    ACTIVATION_STARTED    = "activation_started"
    VOLUNTEER_ACKNOWLEDGED = "volunteer_acknowledged"
    FIRST_SESSION_READY   = "first_session_ready"
    ACTIVATION_COMPLETED  = "activation_completed"
    ACTIVATION_BLOCKED    = "activation_blocked"


class OpsStage(str, Enum):
    DELIVERY_OPERATIONS = "delivery_operations"
    DELIVERY_COMPLETE   = "delivery_complete"


class ControlStage(str, Enum):
    # Operations-phase control stages (the originals — still used whenever a
    # pause/escalation happens during daily operations).
    PAUSED       = "paused"
    HUMAN_REVIEW = "human_review"
    # Activation-phase equivalents, so the spec's per-phase state granularity
    # is preserved. Functionally identical resume behavior to PAUSED/HUMAN_REVIEW
    # (see policy_engine._VALID_TRANSITIONS and delivery_logic's resume_status
    # logic) — delivery_logic picks whichever variant matches the current mode
    # when a pause/escalate signal fires.
    ACTIVATION_PAUSED    = "activation_paused"
    ACTIVATION_ESCALATED = "activation_escalated"


class DeliveryStatus(str, Enum):
    ACTIVATING         = "activating"
    ACTIVE             = "active"
    ON_TRACK           = "on_track"
    AT_RISK            = "at_risk"
    INTERRUPTED        = "interrupted"
    RESUMED            = "resumed"
    NEARING_COMPLETION = "nearing_completion"
    PAUSED             = "paused"
    COMPLETED          = "completed"
    DISCONTINUED       = "discontinued"
    ESCALATED          = "escalated"


class SessionState(str, Enum):
    """The fuller set of per-session states (stored in the DB's free-text
    session_state column — this enum documents the allowed values and gives
    code a typed reference; the column itself stays a plain string so adding
    a new value here never requires a migration)."""
    UPCOMING                    = "upcoming"
    READINESS_PENDING           = "readiness_pending"
    READINESS_CONFIRMED         = "readiness_confirmed"
    READINESS_AT_RISK           = "readiness_at_risk"
    DAY_REMINDER_SENT           = "day_reminder_sent"
    PRE_SESSION_REMINDER_SENT   = "pre_session_reminder_sent"
    SESSION_WINDOW_ACTIVE       = "session_window_active"
    COMPLETION_CHECK_SENT       = "completion_check_sent"
    COMPLETION_PENDING          = "completion_pending"
    COMPLETED                   = "completed"
    PARTIALLY_COMPLETED         = "partially_completed"
    MISSED                      = "missed"
    DISRUPTED                   = "disrupted"
    UNVERIFIED                  = "unverified"
    RESCHEDULE_REQUESTED        = "reschedule_requested"
    RESCHEDULED                 = "rescheduled"
    ESCALATED                   = "escalated"
    CANCELLED                   = "cancelled"
    CHECKIN_CLOSED              = "checkin_closed"


# Session outcome values accepted by delivery_record_session_outcome
SESSION_OUTCOMES = [
    "completed", "partially_completed", "missed", "disrupted",
    "unverified", "reschedule_requested", "support_needed", "cancelled",
]


# Stages the delivery agent owns (used by orchestrator routing + guards)
DELIVERY_STAGES = [
    ActivationStage.ACTIVATION_STARTED.value,
    ActivationStage.VOLUNTEER_ACKNOWLEDGED.value,
    ActivationStage.FIRST_SESSION_READY.value,
    ActivationStage.ACTIVATION_COMPLETED.value,
    ActivationStage.ACTIVATION_BLOCKED.value,
    OpsStage.DELIVERY_OPERATIONS.value,
    OpsStage.DELIVERY_COMPLETE.value,
    ControlStage.PAUSED.value,
    ControlStage.HUMAN_REVIEW.value,
    ControlStage.ACTIVATION_PAUSED.value,
    ControlStage.ACTIVATION_ESCALATED.value,
]

# Terminal conversation stages — no further LLM turn processing. PAUSED is
# deliberately NOT here: it must stay resumable (see policy_engine's
# _VALID_TRANSITIONS, which allows paused -> every earlier stage). Only a
# genuinely finished delivery has nothing left to process.
TERMINAL_STAGES = {OpsStage.DELIVERY_COMPLETE.value}


class DeliverySessionState(BaseModel):
    """Subset of the orchestrator SessionState the delivery agent needs."""
    id: UUID
    channel: str = "web_ui"
    persona: str = "new_volunteer"
    workflow: str = "delivery_support"
    active_agent: str = "delivery_assistant"
    status: str = "active"
    stage: str = ActivationStage.ACTIVATION_STARTED.value
    sub_state: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None
    volunteer_id: Optional[str] = None
    volunteer_name: Optional[str] = None
    volunteer_phone: Optional[str] = None


class DeliveryAgentTurnRequest(BaseModel):
    session_id: UUID
    session_state: DeliverySessionState
    user_message: str = ""
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    intent_hint: Optional[str] = None
    channel_metadata: Optional[Dict[str, Any]] = None


class DeliveryAgentTurnResponse(BaseModel):
    assistant_message: str
    preliminary_message: Optional[str] = None
    auto_continue: bool = False
    active_agent: str = "delivery_assistant"
    workflow: str = "delivery_support"
    state: str
    sub_state: Optional[str] = None
    completion_status: Optional[str] = None
    telemetry_events: List[Dict[str, Any]] = Field(default_factory=list)
    handoff_event: Optional[Dict[str, Any]] = None


def load_sub_state(raw: Optional[str]) -> Dict[str, Any]:
    """Load sub_state JSON, defaulting on missing/malformed input. Preserves the
    handoff payload persisted by the orchestrator under the 'handoff' key."""
    if not raw:
        return dict(_DEFAULT_SUB_STATE)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return dict(_DEFAULT_SUB_STATE)
        merged = dict(_DEFAULT_SUB_STATE)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, ValueError):
        logger.warning("Malformed delivery sub_state JSON — using defaults")
        return dict(_DEFAULT_SUB_STATE)


def dump_sub_state(sub_state: Dict[str, Any]) -> str:
    return json.dumps(sub_state)
