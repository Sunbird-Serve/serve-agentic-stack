"""
SERVE AI - Shared Enums
Strongly typed enumerations for the entire system
"""
from enum import Enum


class AgentType(str, Enum):
    """Available agents in the SERVE ecosystem"""
    ONBOARDING = "onboarding"
    SELECTION = "selection"
    ENGAGEMENT = "engagement"
    NEED = "need"
    FULFILLMENT = "fulfillment"
    DELIVERY_ASSISTANT = "delivery_assistant"


class WorkflowType(str, Enum):
    """Supported workflow types"""
    NEW_VOLUNTEER_ONBOARDING = "new_volunteer_onboarding"
    RETURNING_VOLUNTEER = "returning_volunteer"
    NEED_COORDINATION = "need_coordination"
    VOLUNTEER_ENGAGEMENT = "volunteer_engagement"
    SYSTEM_TRIGGERED = "system_triggered"


class OnboardingState(str, Enum):
    """Onboarding agent states"""
    INIT = "init"
    INTENT_DISCOVERY = "intent_discovery"
    PURPOSE_ORIENTATION = "purpose_orientation"
    ELIGIBILITY_CONFIRMATION = "eligibility_confirmation"
    CAPABILITY_DISCOVERY = "capability_discovery"
    PROFILE_CONFIRMATION = "profile_confirmation"
    ONBOARDING_COMPLETE = "onboarding_complete"
    PAUSED = "paused"


class SessionStatus(str, Enum):
    """Session lifecycle status"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    ESCALATED = "escalated"


class ChannelType(str, Enum):
    """Supported interaction channels"""
    WEB_UI = "web_ui"
    WHATSAPP = "whatsapp"
    API = "api"


class PersonaType(str, Enum):
    """User persona types"""
    NEW_VOLUNTEER = "new_volunteer"
    RETURNING_VOLUNTEER = "returning_volunteer"
    INACTIVE_VOLUNTEER = "inactive_volunteer"
    NEED_COORDINATOR = "need_coordinator"
    SYSTEM = "system"


class HandoffType(str, Enum):
    """Types of agent handoffs"""
    AGENT_TRANSITION = "agent_transition"
    RESUME = "resume"
    ESCALATION = "escalation"
    PAUSE = "pause"


class EventType(str, Enum):
    """Telemetry event types"""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    STATE_TRANSITION = "state_transition"
    MCP_CALL = "mcp_call"
    AGENT_RESPONSE = "agent_response"
    HANDOFF = "handoff"
    ERROR = "error"
    USER_MESSAGE = "user_message"
