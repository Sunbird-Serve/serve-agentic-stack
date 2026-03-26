"""
SERVE Engagement Agent Service - Schemas

Workflow stages for returning volunteer re-engagement:

  RE_ENGAGING        — Warm welcome back, confirm identity, surface last activity
  PROFILE_REFRESH    — Check if skills/availability have changed since last session
  MATCHING_READY     — Profile is current, hand off to matching agent
  PAUSED             — Volunteer wants to continue later

TODO (contributor): Add more stages as the engagement flow is designed.
  e.g. PREFERENCE_UPDATE, COMMITMENT_CONFIRMATION, SCHEDULING, etc.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum


class EngagementWorkflowState(str, Enum):
    """Stages in the returning-volunteer engagement workflow."""
    RE_ENGAGING     = "re_engaging"      # Initial re-contact, identity confirmation
    PROFILE_REFRESH = "profile_refresh"  # Checking for profile updates
    MATCHING_READY  = "matching_ready"   # Ready to hand off to matching agent
    PAUSED          = "paused"           # Volunteer paused the session

    # TODO: add more stages here as the flow is designed
    # PREFERENCE_UPDATE     = "preference_update"
    # COMMITMENT_CONFIRM    = "commitment_confirm"
    # SCHEDULING            = "scheduling"


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
