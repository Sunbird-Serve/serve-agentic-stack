"""
SERVE Orchestrator Service - Schemas
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
    SCHEDULER = "scheduler"
    MOBILE = "mobile"


class TriggerType(str, Enum):
    """What caused this event to enter the orchestrator."""
    USER_MESSAGE = "user_message"       # Human typed a message
    SYSTEM_TRIGGER = "system_trigger"   # Internal orchestration event
    SCHEDULED = "scheduled"             # Scheduler-triggered (cron/timer)
    WEBHOOK = "webhook"                 # Inbound webhook notification
    RESUME = "resume"                   # Explicit re-open of a paused session


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


class NeedWorkflowState(str, Enum):
    """States in the need lifecycle workflow."""
    INITIATED = "initiated"
    RESOLVING_COORDINATOR = "resolving_coordinator"
    RESOLVING_SCHOOL = "resolving_school"
    DRAFTING_NEED = "drafting_need"
    PENDING_APPROVAL = "pending_approval"
    REFINEMENT_REQUIRED = "refinement_required"
    APPROVED = "approved"
    PAUSED = "paused"
    REJECTED = "rejected"
    HUMAN_REVIEW = "human_review"
    FULFILLMENT_HANDOFF_READY = "fulfillment_handoff_ready"


class IntentType(str, Enum):
    """
    What the user intends to do with this message.
    Resolved before agent routing so the orchestrator can short-circuit
    workflow-control signals (pause, escalate, restart) without touching agents.
    """
    START_WORKFLOW = "start_workflow"        # First contact — no session exists
    CONTINUE_WORKFLOW = "continue_workflow"  # Normal progression through a workflow
    RESUME_SESSION = "resume_session"        # Re-engaging a paused session
    SEEK_HELP = "seek_help"                  # User is confused or stuck
    PAUSE_SESSION = "pause_session"          # User wants to stop for now
    RESTART = "restart"                      # User wants to begin from scratch
    ESCALATE = "escalate"                    # User requests a human agent


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


# ============ Channel Adapter Model ============

class NormalizedEvent(BaseModel):
    """
    Canonical internal representation of any inbound event, regardless of channel.

    Every channel adapter transforms its raw input into this model. All downstream
    orchestration logic operates exclusively on NormalizedEvent so it stays
    decoupled from channel-specific concerns.

    Fields:
        actor_id:        Stable identifier for who triggered the event.
                         WhatsApp → phone number, Web UI → user_id / session stub,
                         Scheduler → job_id, API → client_id.
        channel:         Which channel the event arrived on.
        trigger_type:    Nature of the trigger (message, scheduled, webhook, etc.).
        payload:         The actual message text or content.
        session_id:      Present when this is a continuation of an existing session.
        persona:         Explicit persona override from the channel; resolved by the
                         orchestrator if absent.
        raw_metadata:    Original channel-specific data preserved verbatim.
        idempotency_key: Deduplication key (e.g. WhatsApp message_id / wamid).
        timestamp:       When the event was received.
    """
    actor_id: str
    channel: ChannelType
    trigger_type: TriggerType
    payload: str
    session_id: Optional[UUID] = None
    persona: Optional["PersonaType"] = None
    raw_metadata: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class IntentResult(BaseModel):
    """
    Output of the IntentResolver.

    intent:            Classified intent type.
    confidence:        Resolver confidence [0–1]; lower values indicate ambiguity.
    suggested_response: Optional canned text for terminal intents (pause, escalate,
                       restart) that the orchestrator returns directly without
                       invoking an agent.
    metadata:          Diagnostic info (which signal fired, matched keyword, etc.).
    """
    intent: "IntentType"
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    suggested_response: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PersonaResolutionResult(BaseModel):
    """
    Output of the PersonaResolver.

    persona:    The resolved persona type for this actor.
    confidence: Resolver confidence [0–1].
    source:     How the persona was determined:
                  "explicit"        — channel sent an explicit persona override
                  "trigger_type"    — inferred from trigger (e.g. SCHEDULED → SYSTEM)
                  "actor_lookup"    — looked up in the volunteer/coordinator registry
                  "default"         — no record found; defaulting to NEW_VOLUNTEER
    metadata:   Diagnostic info (actor_type, last_active_days, etc.).
    """
    persona: "PersonaType"
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


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
    session_id: Optional[UUID] = None
    assistant_message: str
    active_agent: AgentType
    workflow: WorkflowType
    state: str
    sub_state: Optional[str] = None
    status: SessionStatus = SessionStatus.ACTIVE
    is_complete: bool = False
    is_duplicate: bool = False          # True when idempotency check rejects a repeat event
    journey_progress: Optional[Dict[str, Any]] = None
    debug_info: Optional[Dict[str, Any]] = None


# ============ Agent Turn Models ============

class AgentTurnRequest(BaseModel):
    """Request from orchestrator to agent"""
    session_id: UUID
    session_state: SessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = []
    intent_hint: Optional[str] = None  # resolved intent value, e.g. "seek_help"


class HandoffEvent(BaseModel):
    """Handoff event"""
    session_id: UUID
    from_agent: AgentType
    to_agent: AgentType
    handoff_type: HandoffType
    payload: Dict[str, Any] = {}
    reason: Optional[str] = None


class TelemetryEvent(BaseModel):
    """Telemetry event"""
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
