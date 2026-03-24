"""
SERVE AI Platform - Backend Server (Refactored)
For development environment - runs all services in combined mode.
In production, use docker-compose to run services separately.

This version includes:
- AgentRouter abstraction for routing decisions
- WorkflowValidator for state transition validation
- Structured contracts for clean inter-service communication
- Enhanced structured logging
- WhatsApp channel adapter integration
"""
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from contextlib import asynccontextmanager
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator
from enum import Enum
import re

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============ Enums ============

class ChannelType(str, Enum):
    WEB_UI = "web_ui"
    WHATSAPP = "whatsapp"
    API = "api"

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

class OrchestrationEventType(str, Enum):
    SESSION_CREATED = 'session_created'
    SESSION_RESUMED = 'session_resumed'
    MESSAGE_RECEIVED = 'message_received'
    AGENT_INVOKED = 'agent_invoked'
    AGENT_RESPONDED = 'agent_responded'
    STATE_TRANSITION = 'state_transition'
    ROUTING_DECISION = 'routing_decision'
    HANDOFF_INITIATED = 'handoff_initiated'
    VALIDATION_FAILED = 'validation_failed'
    ERROR_OCCURRED = 'error_occurred'


# ============ Pydantic Models ============

class InteractionRequest(BaseModel):
    session_id: Optional[UUID] = None
    message: str
    channel: ChannelType = ChannelType.WEB_UI
    channel_metadata: Optional[Dict[str, Any]] = None
    persona: Optional[PersonaType] = None

class InteractionResponse(BaseModel):
    session_id: UUID
    assistant_message: str
    active_agent: AgentType
    workflow: WorkflowType
    state: str
    sub_state: Optional[str] = None
    status: SessionStatus
    journey_progress: Optional[Dict[str, Any]] = None
    debug_info: Optional[Dict[str, Any]] = None

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

class AgentTurnRequest(BaseModel):
    session_id: UUID
    session_state: SessionState
    user_message: str
    conversation_history: List[Dict[str, str]] = []

class HandoffEvent(BaseModel):
    session_id: UUID
    from_agent: AgentType
    to_agent: AgentType
    handoff_type: HandoffType
    payload: Dict[str, Any] = {}
    reason: Optional[str] = None

class TelemetryEvent(BaseModel):
    session_id: UUID
    event_type: EventType
    agent: Optional[AgentType] = None
    data: Dict[str, Any] = {}

class AgentTurnResponse(BaseModel):
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

class MCPResponse(BaseModel):
    status: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class StartSessionRequest(BaseModel):
    channel: ChannelType = ChannelType.WEB_UI
    persona: PersonaType = PersonaType.NEW_VOLUNTEER
    channel_metadata: Optional[Dict[str, Any]] = None

class ResumeContextRequest(BaseModel):
    session_id: UUID

class AdvanceStateRequest(BaseModel):
    session_id: UUID
    new_state: str
    sub_state: Optional[str] = None

class GetMissingFieldsRequest(BaseModel):
    session_id: UUID

class SaveConfirmedFieldsRequest(BaseModel):
    session_id: UUID
    fields: Dict[str, Any]

class SaveMessageRequest(BaseModel):
    session_id: UUID
    role: str
    content: str
    agent: Optional[AgentType] = None

class GetConversationRequest(BaseModel):
    session_id: UUID
    limit: int = 50

class LogEventRequest(BaseModel):
    session_id: UUID
    event_type: EventType
    agent: Optional[AgentType] = None
    data: Dict[str, Any] = {}

class EmitHandoffRequest(BaseModel):
    session_id: UUID
    from_agent: AgentType
    to_agent: AgentType
    handoff_type: HandoffType
    payload: Dict[str, Any] = {}
    reason: Optional[str] = None

class PrepareHandoffRequest(BaseModel):
    session_id: UUID
    target_agent: AgentType

class PauseSessionRequest(BaseModel):
    session_id: UUID
    reason: Optional[str] = None


# ============ Routing Contract ============

class RoutingDecision(BaseModel):
    """Represents a routing decision made by the orchestrator."""
    target_agent: str
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    reason: str
    fallback_agent: Optional[str] = None
    routing_context: Dict[str, Any] = Field(default_factory=dict)


# ============ Transition Validation Contract ============

class TransitionValidation(BaseModel):
    """Represents the result of validating a state transition."""
    is_valid: bool
    from_state: str
    to_state: str
    reason: str
    warnings: List[str] = Field(default_factory=list)
    required_fields_met: bool = True
    recommended_action: Optional[str] = None


# ============ In-Memory Store ============

class InMemoryStore:
    def __init__(self):
        self.sessions = {}
        self.profiles = {}
        self.messages = {}
        self.telemetry = {}
        self.memory_summaries = {}  # session_id -> {summary_text, key_facts, created_at}
        # Need coordination stores
        self.need_drafts = {}  # session_id -> need_draft
        self.coordinators = {}  # coordinator_id -> coordinator_data
        self.schools = {}  # school_id -> school_data
        self.coordinator_by_phone = {}  # phone -> coordinator_id

store = InMemoryStore()


# ============ Workflow Validator ============

class WorkflowValidator:
    """Validates state transitions within workflows."""
    
    # Define valid transitions for onboarding workflow
    VALID_TRANSITIONS = {
        'init': ['intent_discovery'],
        'intent_discovery': ['purpose_orientation', 'paused'],
        'purpose_orientation': ['eligibility_confirmation', 'paused'],
        'eligibility_confirmation': ['capability_discovery', 'paused'],
        'capability_discovery': ['profile_confirmation', 'paused'],
        'profile_confirmation': ['onboarding_complete', 'capability_discovery', 'paused'],
        'onboarding_complete': [],
        'paused': ['init', 'intent_discovery', 'purpose_orientation', 
                   'eligibility_confirmation', 'capability_discovery', 'profile_confirmation',
                   # Need workflow resume states
                   'initiated', 'resolving_coordinator', 'resolving_school', 'drafting_need', 
                   'pending_approval', 'refinement_required'],
        # Need workflow transitions
        'initiated': ['resolving_coordinator', 'paused'],
        'resolving_coordinator': ['resolving_school', 'human_review', 'paused'],
        'resolving_school': ['drafting_need', 'human_review', 'paused'],
        'drafting_need': ['pending_approval', 'paused'],
        'pending_approval': ['approved', 'refinement_required', 'drafting_need', 'rejected', 'paused'],
        'refinement_required': ['drafting_need', 'pending_approval', 'paused'],
        'approved': ['fulfillment_handoff_ready'],
        'fulfillment_handoff_ready': [],
        'human_review': ['resolving_coordinator', 'resolving_school', 'drafting_need', 'rejected'],
        'rejected': [],
    }
    
    # Required fields for each stage
    STAGE_REQUIRED_FIELDS = {
        'eligibility_confirmation': ['full_name', 'email'],
        'capability_discovery': ['skills', 'availability'],
        'profile_confirmation': ['full_name', 'email', 'skills', 'availability'],
        'onboarding_complete': ['full_name', 'email', 'skills', 'availability'],
        # Need workflow fields
        'pending_approval': ['subjects', 'grade_levels', 'student_count', 'time_slots', 'start_date', 'duration_weeks'],
        'approved': ['subjects', 'grade_levels', 'student_count', 'time_slots', 'start_date', 'duration_weeks'],
    }
    
    def validate_transition(
        self,
        from_state: str,
        to_state: str,
        confirmed_fields: Dict = None
    ) -> TransitionValidation:
        """Validate a state transition."""
        confirmed_fields = confirmed_fields or {}
        
        # Allow staying in same state
        if from_state == to_state:
            return TransitionValidation(
                is_valid=True,
                from_state=from_state,
                to_state=to_state,
                reason="Remaining in current stage"
            )
        
        # Check if transition is allowed
        valid_next = self.VALID_TRANSITIONS.get(from_state, [])
        if to_state not in valid_next:
            return TransitionValidation(
                is_valid=False,
                from_state=from_state,
                to_state=to_state,
                reason=f"Transition from '{from_state}' to '{to_state}' is not allowed",
                recommended_action=f"Valid next stages: {valid_next}"
            )
        
        # Check required fields
        required = self.STAGE_REQUIRED_FIELDS.get(to_state, [])
        missing = [f for f in required if not confirmed_fields.get(f)]
        
        if missing and to_state != 'paused':
            return TransitionValidation(
                is_valid=True,
                from_state=from_state,
                to_state=to_state,
                reason="Transition allowed with warnings",
                warnings=[f"Missing fields: {missing}"],
                required_fields_met=False,
                recommended_action="Collect missing required fields"
            )
        
        return TransitionValidation(
            is_valid=True,
            from_state=from_state,
            to_state=to_state,
            reason=f"Valid transition from '{from_state}' to '{to_state}'",
            required_fields_met=True
        )
    
    def get_completion_percentage(self, stage: str, workflow: str = 'new_volunteer_onboarding') -> int:
        """Calculate workflow completion percentage."""
        stage_orders = {
            'new_volunteer_onboarding': ['init', 'intent_discovery', 'purpose_orientation',
                      'eligibility_confirmation', 'capability_discovery',
                      'profile_confirmation', 'onboarding_complete'],
            'need_coordination': ['initiated', 'resolving_coordinator', 'resolving_school',
                      'drafting_need', 'pending_approval', 'approved',
                      'fulfillment_handoff_ready']
        }
        stages = stage_orders.get(workflow, stage_orders['new_volunteer_onboarding'])
        if stage not in stages:
            if stage in ['paused', 'human_review', 'refinement_required']:
                return 50
            return 0
        idx = stages.index(stage)
        return round((idx / (len(stages) - 1)) * 100)
    
    def is_terminal_stage(self, stage: str, workflow: str = 'new_volunteer_onboarding') -> bool:
        """Check if stage is terminal."""
        terminal_stages = {
            'new_volunteer_onboarding': ['onboarding_complete'],
            'need_coordination': ['approved', 'rejected', 'fulfillment_handoff_ready']
        }
        return stage in terminal_stages.get(workflow, [])


workflow_validator = WorkflowValidator()


# ============ Agent Router ============

class AgentRouter:
    """Routes requests to appropriate agents."""
    
    AGENT_STAGES = {
        'onboarding': ['init', 'intent_discovery', 'purpose_orientation',
                       'eligibility_confirmation', 'capability_discovery',
                       'profile_confirmation', 'onboarding_complete', 'paused'],
        'need': ['initiated', 'resolving_coordinator', 'resolving_school',
                 'drafting_need', 'pending_approval', 'refinement_required',
                 'approved', 'paused', 'rejected', 'human_review',
                 'fulfillment_handoff_ready']
    }
    
    def make_routing_decision(
        self,
        session_state: SessionState,
        user_message: str
    ) -> RoutingDecision:
        """Determine which agent should handle the request."""
        current_agent = session_state.active_agent
        current_stage = session_state.stage
        
        # Check if current agent handles this stage
        agent_stages = self.AGENT_STAGES.get(current_agent, [])
        if current_stage in agent_stages:
            return RoutingDecision(
                target_agent=current_agent,
                confidence=1.0,
                reason=f"Continuing with {current_agent} for stage {current_stage}",
                routing_context={'decision_type': 'continue'}
            )
        
        # Find appropriate agent
        for agent, stages in self.AGENT_STAGES.items():
            if current_stage in stages:
                return RoutingDecision(
                    target_agent=agent,
                    confidence=0.9,
                    reason=f"Routing to {agent} for stage {current_stage}",
                    fallback_agent=current_agent,
                    routing_context={'decision_type': 'stage_based'}
                )
        
        # Fallback
        return RoutingDecision(
            target_agent=current_agent,
            confidence=0.5,
            reason=f"Fallback to {current_agent}",
            routing_context={'decision_type': 'fallback'}
        )
    
    def log_routing_decision(self, session_id: str, decision: RoutingDecision):
        """Log routing decision for debugging."""
        logger.info(f"Routing Decision: session={session_id}, "
                   f"target={decision.target_agent}, "
                   f"confidence={decision.confidence}, "
                   f"reason={decision.reason}")


agent_router = AgentRouter()


# ============ Structured Event Logger ============

def log_orchestration_event(
    event_type: OrchestrationEventType,
    session_id: str,
    agent: str = None,
    workflow: str = None,
    stage: str = None,
    duration_ms: float = None,
    details: Dict = None,
    success: bool = True
):
    """Log structured orchestration events."""
    event = {
        'event': event_type.value,
        'session_id': session_id,
        'timestamp': datetime.utcnow().isoformat(),
        'agent': agent,
        'workflow': workflow,
        'stage': stage,
        'success': success,
        'duration_ms': duration_ms,
        **(details or {})
    }
    logger.info(f"Orchestration: {event}")


# ============ MCP Capabilities ============

async def mcp_start_session(request: StartSessionRequest) -> MCPResponse:
    session_id = str(uuid4())
    now = datetime.utcnow().isoformat()
    
    store.sessions[session_id] = {
        "id": session_id,
        "channel": request.channel.value,
        "persona": request.persona.value,
        "workflow": "new_volunteer_onboarding",
        "active_agent": "onboarding",
        "status": "active",
        "stage": "init",
        "sub_state": None,
        "context_summary": None,
        "created_at": now,
        "updated_at": now,
    }
    
    store.profiles[session_id] = {
        "id": str(uuid4()),
        "session_id": session_id,
        "full_name": None,
        "email": None,
        "phone": None,
        "location": None,
        "skills": [],
        "interests": [],
        "availability": None,
    }
    
    store.messages[session_id] = []
    store.telemetry[session_id] = []
    
    log_orchestration_event(
        OrchestrationEventType.SESSION_CREATED,
        session_id,
        workflow="new_volunteer_onboarding",
        stage="init",
        details={'channel': request.channel.value, 'persona': request.persona.value}
    )
    
    return MCPResponse(status="success", data={
        "session_id": session_id,
        "stage": "init",
        "status": "active"
    })

async def mcp_resume_context(session_id: str) -> MCPResponse:
    session = store.sessions.get(session_id)
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    profile = store.profiles.get(session_id, {})
    messages = store.messages.get(session_id, [])[-10:]
    
    log_orchestration_event(
        OrchestrationEventType.SESSION_RESUMED,
        session_id,
        workflow=session.get("workflow"),
        stage=session.get("stage")
    )
    
    return MCPResponse(status="success", data={
        "session": session,
        "volunteer_profile": profile,
        "conversation_history": messages,
        "memory_summary": None
    })

async def mcp_advance_state(session_id: str, new_state: str, sub_state: str = None) -> MCPResponse:
    session = store.sessions.get(session_id)
    if not session:
        return MCPResponse(status="error", error="Session not found")
    
    old_state = session["stage"]
    profile = store.profiles.get(session_id, {})
    
    # Validate transition
    validation = workflow_validator.validate_transition(
        old_state, new_state, profile
    )
    
    if not validation.is_valid:
        logger.warning(f"Invalid transition blocked: {validation.reason}")
        return MCPResponse(
            status="error",
            error=validation.reason,
            data={"recommended_action": validation.recommended_action}
        )
    
    if validation.warnings:
        logger.info(f"Transition warnings: {validation.warnings}")
    
    session["stage"] = new_state
    session["sub_state"] = sub_state
    session["updated_at"] = datetime.utcnow().isoformat()
    
    if new_state == "onboarding_complete":
        session["status"] = "completed"
    
    log_orchestration_event(
        OrchestrationEventType.STATE_TRANSITION,
        session_id,
        workflow=session["workflow"],
        stage=new_state,
        details={
            'from_state': old_state,
            'to_state': new_state,
            'required_fields_met': validation.required_fields_met
        }
    )
    
    return MCPResponse(status="success", data={
        "session_id": session_id,
        "previous_state": old_state,
        "current_state": new_state,
        "validation": {
            "is_valid": validation.is_valid,
            "warnings": validation.warnings
        }
    })

async def mcp_get_missing_fields(session_id: str) -> MCPResponse:
    profile = store.profiles.get(session_id, {})
    required = ["full_name", "email", "location", "skills", "availability"]
    missing = []
    confirmed = {}
    
    for field in required:
        value = profile.get(field)
        if not value or (isinstance(value, list) and len(value) == 0):
            missing.append(field)
        else:
            confirmed[field] = value
    
    return MCPResponse(status="success", data={
        "missing_fields": missing,
        "confirmed_fields": confirmed,
        "completion_percentage": round((len(confirmed) / len(required)) * 100)
    })

async def mcp_save_confirmed_fields(session_id: str, fields: Dict[str, Any]) -> MCPResponse:
    if session_id not in store.profiles:
        store.profiles[session_id] = {"session_id": session_id}
    
    for field, value in fields.items():
        store.profiles[session_id][field] = value
    
    logger.info(f"Saved fields for session {session_id}: {list(fields.keys())}")
    return MCPResponse(status="success", data={"saved_fields": list(fields.keys())})

async def mcp_save_message(session_id: str, role: str, content: str, agent: str = None) -> MCPResponse:
    if session_id not in store.messages:
        store.messages[session_id] = []
    
    store.messages[session_id].append({
        "id": str(uuid4()),
        "role": role,
        "content": content,
        "agent": agent,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return MCPResponse(status="success", data={"message_id": str(uuid4())})

async def mcp_log_event(session_id: str, event_type: str, agent: str = None, data: Dict = None) -> MCPResponse:
    if session_id not in store.telemetry:
        store.telemetry[session_id] = []
    
    event_id = str(uuid4())
    store.telemetry[session_id].append({
        "id": event_id,
        "event_type": event_type,
        "agent": agent,
        "data": data or {},
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return MCPResponse(status="success", data={"event_id": event_id})


# ============ eVidyaloka Context ============

EVIDYALOKA_CONTEXT = """
eVidyaloka's Mission:
eVidyaloka enables equitable access to quality education for children in rural India.
We connect passionate volunteers with students who need support.

Communication Style:
- Warm and welcoming - like greeting a friend joining a cause
- Respectful and encouraging
- Simple, clear language - avoid jargon
- Never use technical terms like: workflow, orchestrator, MCP, agent, system
"""

# ============ Onboarding Agent Logic ============

def build_state_prompt(stage: str, missing_fields: List[str], confirmed_fields: Dict) -> str:
    """Build contextual prompt for eVidyaloka-aligned responses."""
    
    base = f"""You are an onboarding assistant for eVidyaloka, helping new volunteers join 
our mission to bring quality education to children in rural India.

{EVIDYALOKA_CONTEXT}

Guidelines:
- Keep responses concise (2-3 sentences max)
- Be warm but not overly effusive
- Ask one question at a time
- Never mention technical terms or internal processes
"""
    
    stage_instructions = {
        "init": """STAGE: Welcome
Give a warm, brief welcome and ask what brings them to volunteer with eVidyaloka.
Example: "Welcome! It's wonderful to meet someone interested in supporting education. What brings you to eVidyaloka?" """,
        
        "intent_discovery": """STAGE: Understanding Interest
Learn why they want to volunteer. Acknowledge their motivation warmly.
Example: "That's really thoughtful. What draws you specifically to education or working with children?" """,
        
        "purpose_orientation": """STAGE: Sharing Mission
Share briefly what eVidyaloka does - connecting volunteers with rural students.
Ask what kind of support they'd enjoy providing.
Example: "At eVidyaloka, volunteers teach and mentor children who might not otherwise have access to quality education. What kind of support would you enjoy providing?" """,
        
        "eligibility_confirmation": """STAGE: Getting to Know You
Gather basic info: name, email. Ask for one piece at a time naturally.
Example: "I'd love to know who I'm chatting with! What's your name?" """,
        
        "capability_discovery": """STAGE: Your Strengths
Explore skills and availability. Be encouraging about whatever they share.
Example: "What subjects or skills do you feel comfortable sharing with students?" """,
        
        "profile_confirmation": """STAGE: Confirm Profile
Present what you've learned and ask if anything needs updating.
Keep it conversational, not robotic.""",
        
        "onboarding_complete": """STAGE: Welcome Aboard!
Congratulate them warmly. Let them know we'll match them with students soon.
Example: "You're all set to begin your journey with eVidyaloka. We'll connect you with students soon. Thank you for choosing to make a difference!" """,
        
        "paused": """STAGE: Paused
Be understanding, let them know they can return anytime.
Example: "Of course! Take all the time you need. When you're ready, I'll be here." """
    }
    
    prompt = base + "\n\n" + stage_instructions.get(stage, stage_instructions["init"])
    
    if missing_fields:
        prompt += f"\n\nINFO STILL NEEDED: {', '.join(missing_fields)}. Ask about one naturally."
    if confirmed_fields:
        prompt += f"\n\nCONFIRMED: {confirmed_fields}"
    
    return prompt

STATE_PROMPTS = {
    "init": "Welcome stage - see build_state_prompt()",
    "intent_discovery": "Understanding motivation",
    "purpose_orientation": "Sharing mission",
    "eligibility_confirmation": "Gathering basic info",
    "capability_discovery": "Exploring skills",
    "profile_confirmation": "Confirming profile",
    "onboarding_complete": "Completion",
}

def determine_next_state(current_state: str, message: str, missing_fields: List[str], confirmed_fields: Dict = None) -> str:
    """
    Autonomously determine next state based on:
    1. User signals (pause, exit)
    2. Data completeness
    3. Natural conversation flow
    """
    confirmed_fields = confirmed_fields or {}
    message_lower = message.lower()
    
    # Check for pause/exit signals
    pause_signals = ["pause", "stop", "later", "bye", "quit", "exit", "not now"]
    if any(s in message_lower for s in pause_signals):
        return "paused"
    
    # Check for resume signals if paused
    if current_state == "paused":
        resume_signals = ["continue", "resume", "back", "ready", "let's go"]
        if any(s in message_lower for s in resume_signals):
            return "eligibility_confirmation"
    
    if current_state == "init":
        return "intent_discovery"
    
    elif current_state == "intent_discovery":
        if len(message.split()) > 3:
            return "purpose_orientation"
        return current_state
    
    elif current_state == "purpose_orientation":
        return "eligibility_confirmation"
    
    elif current_state == "eligibility_confirmation":
        # Progress when we have basic info
        has_name = confirmed_fields.get("full_name")
        has_email = confirmed_fields.get("email")
        if has_name and has_email:
            return "capability_discovery"
        return current_state
    
    elif current_state == "capability_discovery":
        # Progress when we have skills
        has_skills = confirmed_fields.get("skills") and len(confirmed_fields.get("skills", [])) > 0
        if has_skills:
            return "profile_confirmation"
        return current_state
    
    elif current_state == "profile_confirmation":
        confirms = ["yes", "correct", "confirm", "looks good", "that's right", "perfect", "ok", "okay"]
        if any(c in message_lower for c in confirms):
            return "onboarding_complete"
        corrections = ["no", "wrong", "change", "update", "fix"]
        if any(c in message_lower for c in corrections):
            return "capability_discovery"
        return current_state
    
    return current_state

def extract_fields(message: str, existing_fields: Dict = None) -> Dict[str, Any]:
    """
    Enhanced profile extraction from free-form text.
    Uses multiple strategies for robust extraction.
    """
    existing_fields = existing_fields or {}
    fields = {}
    lower = message.lower()
    
    # Name extraction patterns
    name_patterns = [
        r"(?:my name is|i'm|i am|call me|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"^([A-Z][a-z]+)(?:\s+here|,)",
        r"(?:name[:\s]+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    ]
    
    if "full_name" not in existing_fields:
        for pattern in name_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean name - remove trailing noise
                words = name.split()
                clean_words = []
                stop_words = {'and', 'or', 'but', 'i', 'my', 'am', 'is', 'the', 'want', 'would', 'like', 'to', 'here'}
                for word in words:
                    if word.lower() in stop_words:
                        break
                    if word[0].isupper() or len(clean_words) == 0:
                        clean_words.append(word)
                    else:
                        break
                if clean_words:
                    fields["full_name"] = " ".join(clean_words[:3]).title()
                    break
    
    # Email extraction
    if "email" not in existing_fields:
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', message)
        if emails:
            fields["email"] = emails[0].lower()
    
    # Phone extraction
    if "phone" not in existing_fields:
        phone_patterns = [
            r'\b(\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4})\b',
            r'\b(\d{10})\b',
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, message)
            if match:
                fields["phone"] = match.group(1)
                break
    
    # Location extraction
    if "location" not in existing_fields:
        location_signals = [
            r"(?:i(?:'m| am)? (?:from|in|at|based in|living in|located in))\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
            r"(?:based out of|working from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        ]
        for pattern in location_signals:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                fields["location"] = match.group(1).strip().title()
                break
    
    # Skill extraction with synonyms
    skill_keywords = {
        "teaching": ["teach", "teaching", "tutor", "tutoring", "instructor"],
        "mathematics": ["math", "maths", "mathematics", "algebra", "calculus"],
        "science": ["science", "physics", "chemistry", "biology"],
        "english": ["english", "grammar", "writing", "literature"],
        "programming": ["programming", "coding", "code", "software", "python", "java"],
        "art": ["art", "drawing", "painting", "creative"],
        "music": ["music", "singing", "instrument"],
        "communication": ["communication", "speaking", "presentation"],
        "mentoring": ["mentor", "mentoring", "guidance"],
    }
    
    found_skills = []
    for skill_name, keywords in skill_keywords.items():
        for keyword in keywords:
            if keyword in lower:
                if skill_name not in found_skills:
                    found_skills.append(skill_name)
                break
    
    if found_skills:
        existing_skills = existing_fields.get("skills", [])
        if isinstance(existing_skills, list):
            combined = list(set(existing_skills + found_skills))
            fields["skills"] = combined
        else:
            fields["skills"] = found_skills
    
    # Availability extraction
    if "availability" not in existing_fields:
        avail_patterns = [
            r"(\d+)\s*(?:hours?|hrs?)\s*(?:per|a)?\s*(?:week|wk)",
            r"(weekends?|saturday|sunday|weekdays?|evenings?|mornings?)",
            r"(few hours|couple of hours|some time)",
            r"(flexible)",
        ]
        for pattern in avail_patterns:
            match = re.search(pattern, lower)
            if match:
                fields["availability"] = match.group(0)
                break
    
    return fields

async def generate_llm_response(system_prompt: str, messages: List[Dict], user_message: str) -> str:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return "Welcome to eVidyaloka! We're so glad you're interested in supporting education for children in rural India. What brings you to volunteer with us today?"
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"onboarding-{uuid4()}",
            system_message=system_prompt
        )
        chat.with_model("anthropic", os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929"))
        
        context = ""
        for msg in messages[-5:]:
            role = "Volunteer" if msg.get("role") == "user" else "eVidyaloka"
            context += f"{role}: {msg.get('content', '')}\n"
        
        full_msg = f"{context}\nVolunteer: {user_message}" if context else user_message
        response = await chat.send_message(UserMessage(text=full_msg))
        return response
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return "Welcome to eVidyaloka! We're excited you want to help bring quality education to children who need it most. What draws you to volunteer with us?"


# ============ Memory Summarization ============

async def generate_memory_summary(conversation: List[Dict[str, str]]) -> tuple:
    """
    Generate a summary and key facts from conversation using LLM.
    Returns tuple of (summary_text, key_facts_list)
    """
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    
    if not conversation:
        return "", []
    
    # Format conversation
    formatted = []
    for msg in conversation[-10:]:
        role = "Volunteer" if msg.get("role") == "user" else "eVidyaloka"
        formatted.append(f"{role}: {msg.get('content', '')}")
    conv_text = "\n".join(formatted)
    
    if not api_key:
        # Basic fallback summary
        return "Volunteer expressed interest in supporting education through eVidyaloka.", ["Interested in volunteering"]
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        # Generate summary
        summary_prompt = f"""Create a brief summary (2-3 sentences) of this volunteer onboarding conversation:

{conv_text}

Summary:"""
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"memory-summary-{uuid4()}",
            system_message="You summarize volunteer conversations accurately and concisely."
        )
        chat.with_model("anthropic", os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929"))
        
        summary = await chat.send_message(UserMessage(text=summary_prompt))
        
        # Extract key facts
        facts_prompt = f"""Extract key facts from this conversation as a list (one per line, starting with -):

{conv_text}

Facts:"""
        
        facts_response = await chat.send_message(UserMessage(text=facts_prompt))
        
        # Parse facts
        key_facts = []
        for line in facts_response.strip().split("\n"):
            line = line.strip()
            if line.startswith("-"):
                fact = line[1:].strip()
                if fact and len(fact) > 5:
                    key_facts.append(fact)
        
        return summary.strip(), key_facts[:10]
        
    except Exception as e:
        logger.error(f"Memory summarization error: {e}")
        return "Volunteer started onboarding with eVidyaloka.", ["Started onboarding process"]


async def should_generate_summary(session_id: str, message_count: int) -> bool:
    """Check if we should generate a summary based on message count."""
    threshold = 6
    return message_count >= threshold and message_count % threshold == 0


async def save_memory_summary(session_id: str, summary_text: str, key_facts: List[str]) -> MCPResponse:
    """Save memory summary to store."""
    store.memory_summaries[session_id] = {
        "summary_text": summary_text,
        "key_facts": key_facts,
        "created_at": datetime.utcnow()
    }
    logger.info(f"Saved memory summary for session {session_id[:8]}...")
    return MCPResponse(status="success", data={"key_facts_count": len(key_facts)})


async def get_memory_summary(session_id: str) -> MCPResponse:
    """Get memory summary for a session."""
    summary = store.memory_summaries.get(session_id)
    if not summary:
        return MCPResponse(status="success", data=None)
    return MCPResponse(status="success", data=summary)


def get_memory_context(session_id: str, confirmed_fields: Dict) -> str:
    """Get memory context for prompting."""
    summary = store.memory_summaries.get(session_id)
    if not summary:
        return ""
    
    context_parts = []
    
    if summary.get("summary_text"):
        context_parts.append(f"Previous conversation: {summary['summary_text']}")
    
    if summary.get("key_facts"):
        facts = "\n".join(f"  - {f}" for f in summary["key_facts"][:5])
        context_parts.append(f"Key facts:\n{facts}")
    
    name = confirmed_fields.get("full_name")
    if name:
        context_parts.append(f"Remember: Their name is {name}. Use it naturally.")
    
    return "\n\n".join(context_parts)

async def process_agent_turn(request: AgentTurnRequest) -> AgentTurnResponse:
    start_time = datetime.utcnow()
    session_state = request.session_state
    current_state = session_state.stage
    telemetry = []
    
    # Make routing decision
    routing_decision = agent_router.make_routing_decision(session_state, request.user_message)
    agent_router.log_routing_decision(str(request.session_id), routing_decision)
    
    log_orchestration_event(
        OrchestrationEventType.AGENT_INVOKED,
        str(request.session_id),
        agent=routing_decision.target_agent,
        details={'confidence': routing_decision.confidence, 'reason': routing_decision.reason}
    )
    
    # Route to appropriate agent based on workflow
    if session_state.workflow == "need_coordination":
        return await process_need_agent_turn(request, routing_decision, start_time)
    else:
        return await process_onboarding_agent_turn(request, routing_decision, start_time)


async def process_onboarding_agent_turn(request: AgentTurnRequest, routing_decision: RoutingDecision, start_time: datetime) -> AgentTurnResponse:
    """Process turn for onboarding agent."""
    session_state = request.session_state
    current_state = session_state.stage
    telemetry = []
    
    # Get missing fields
    missing_result = await mcp_get_missing_fields(str(request.session_id))
    missing_fields = missing_result.data.get("missing_fields", []) if missing_result.data else []
    confirmed_fields = missing_result.data.get("confirmed_fields", {}) if missing_result.data else {}
    
    # Get memory context for returning volunteers
    memory_context = get_memory_context(str(request.session_id), confirmed_fields)
    
    # Extract fields from message (enhanced extraction with existing fields context)
    extracted = extract_fields(request.user_message, existing_fields=confirmed_fields)
    if extracted:
        await mcp_save_confirmed_fields(str(request.session_id), extracted)
        confirmed_fields.update(extracted)
        missing_fields = [f for f in missing_fields if f not in extracted]
        logger.info(f"Extracted fields: {list(extracted.keys())}")
    
    # Determine next state autonomously (data-driven)
    next_state = determine_next_state(current_state, request.user_message, missing_fields, confirmed_fields)
    
    # Validate transition
    if next_state != current_state:
        validation = workflow_validator.validate_transition(
            current_state, next_state, confirmed_fields
        )
        
        if not validation.is_valid:
            logger.warning(f"Agent proposed invalid transition: {validation.reason}")
            next_state = current_state
        else:
            telemetry.append(TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.STATE_TRANSITION,
                agent=AgentType.ONBOARDING,
                data={
                    "from": current_state, 
                    "to": next_state,
                    "validated": True,
                    "warnings": validation.warnings
                }
            ))
    
    # Build contextual prompt with memory context
    prompt = build_state_prompt(next_state, missing_fields, confirmed_fields)
    if memory_context:
        prompt += f"\n\nMEMORY CONTEXT (use naturally, don't mention having memory):\n{memory_context}"
    
    assistant_msg = await generate_llm_response(prompt, request.conversation_history, request.user_message)
    
    # Update memory summary periodically
    conversation_with_new = request.conversation_history + [
        {"role": "user", "content": request.user_message},
        {"role": "assistant", "content": assistant_msg}
    ]
    
    message_count = len(conversation_with_new)
    if await should_generate_summary(str(request.session_id), message_count):
        summary_text, key_facts = await generate_memory_summary(conversation_with_new)
        await save_memory_summary(str(request.session_id), summary_text, key_facts)
        telemetry.append(TelemetryEvent(
            session_id=request.session_id,
            event_type=EventType.MCP_CALL,
            agent=AgentType.ONBOARDING,
            data={"action": "save_memory_summary", "key_facts_count": len(key_facts)}
        ))
    
    # Calculate duration
    duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
    
    log_orchestration_event(
        OrchestrationEventType.AGENT_RESPONDED,
        str(request.session_id),
        agent=AgentType.ONBOARDING.value,
        stage=next_state,
        duration_ms=duration_ms,
        details={
            'response_length': len(assistant_msg),
            'fields_extracted': list(extracted.keys()) if extracted else [],
            'used_memory': bool(memory_context)
        }
    )
    
    handoff = None
    if next_state == "onboarding_complete":
        # Generate final summary before handoff
        summary_text, key_facts = await generate_memory_summary(conversation_with_new)
        await save_memory_summary(str(request.session_id), summary_text, key_facts)
        
        handoff = HandoffEvent(
            session_id=request.session_id,
            from_agent=AgentType.ONBOARDING,
            to_agent=AgentType.SELECTION,
            handoff_type=HandoffType.AGENT_TRANSITION,
            payload={
                "confirmed_fields": confirmed_fields,
                "memory_summary": summary_text,
                "key_facts": key_facts
            },
            reason="Onboarding completed"
        )
        log_orchestration_event(
            OrchestrationEventType.HANDOFF_INITIATED,
            str(request.session_id),
            agent=AgentType.SELECTION.value,
            details={'from_agent': AgentType.ONBOARDING.value, 'reason': 'Onboarding completed'}
        )
    
    # Generate summary when pausing
    elif next_state == "paused":
        summary_text, key_facts = await generate_memory_summary(conversation_with_new)
        await save_memory_summary(str(request.session_id), summary_text, key_facts)
    
    return AgentTurnResponse(
        assistant_message=assistant_msg,
        active_agent=AgentType.ONBOARDING,
        workflow=WorkflowType(session_state.workflow),
        state=next_state,
        completion_status="complete" if next_state == "onboarding_complete" else ("paused" if next_state == "paused" else "in_progress"),
        confirmed_fields=confirmed_fields,
        missing_fields=missing_fields,
        handoff_event=handoff,
        telemetry_events=telemetry
    )


# ============ Need Agent Processing ============

# Need workflow state transitions
NEED_VALID_TRANSITIONS = {
    'initiated': ['resolving_coordinator', 'paused'],
    'resolving_coordinator': ['resolving_school', 'human_review', 'paused'],
    'resolving_school': ['drafting_need', 'human_review', 'paused'],
    'drafting_need': ['pending_approval', 'paused'],
    'pending_approval': ['approved', 'refinement_required', 'drafting_need', 'rejected', 'paused'],
    'refinement_required': ['drafting_need', 'pending_approval', 'paused'],
    'approved': ['fulfillment_handoff_ready'],
    'fulfillment_handoff_ready': [],
    'human_review': ['resolving_coordinator', 'resolving_school', 'drafting_need', 'rejected'],
    'paused': ['initiated', 'resolving_coordinator', 'resolving_school', 'drafting_need', 'pending_approval', 'refinement_required'],
    'rejected': [],
}

# Mandatory need fields
MANDATORY_NEED_FIELDS = ['subjects', 'grade_levels', 'student_count', 'time_slots', 'start_date', 'duration_weeks']


def extract_need_details(message: str, existing_draft: Dict = None) -> Dict[str, Any]:
    """Extract need details from message."""
    existing_draft = existing_draft or {}
    extracted = {}
    message_lower = message.lower()
    
    # Subject extraction
    subject_keywords = {
        "mathematics": ["math", "maths", "mathematics", "arithmetic", "algebra"],
        "science": ["science", "physics", "chemistry", "biology"],
        "english": ["english", "grammar", "writing", "reading", "literature"],
        "hindi": ["hindi", "hindustani"],
        "social_studies": ["social", "history", "geography", "civics"],
        "computer_basics": ["computer", "computers", "computing", "it"],
        "spoken_english": ["spoken english", "speaking english", "english speaking"],
    }
    found_subjects = []
    for subject, keywords in subject_keywords.items():
        for kw in keywords:
            if kw in message_lower:
                if subject not in found_subjects:
                    found_subjects.append(subject)
                break
    if found_subjects:
        existing = existing_draft.get("subjects", [])
        extracted["subjects"] = list(set(existing + found_subjects))
    
    # Grade extraction
    grade_patterns = [
        r"(?:grade|class|std|standard)\s*(\d{1,2})",
        r"(\d{1,2})(?:th|st|nd|rd)?\s*(?:grade|class|std|standard)",
    ]
    found_grades = set()
    for pattern in grade_patterns:
        matches = re.findall(pattern, message, re.IGNORECASE)
        for m in matches:
            g = str(int(m))
            if 1 <= int(g) <= 12:
                found_grades.add(g)
    # Grade range
    range_pattern = r"(\d{1,2})\s*(?:to|-)\s*(\d{1,2})"
    for start, end in re.findall(range_pattern, message):
        for g in range(int(start), int(end) + 1):
            if 1 <= g <= 12:
                found_grades.add(str(g))
    if found_grades:
        existing = existing_draft.get("grade_levels", [])
        extracted["grade_levels"] = list(set(existing + list(found_grades)))
    
    # Student count
    if "student_count" not in existing_draft:
        count_patterns = [
            r"(\d+)\s*(?:students?|children|kids|learners)",
            r"(?:around|about|approximately)\s*(\d+)",
        ]
        for pattern in count_patterns:
            match = re.search(pattern, message_lower)
            if match:
                count = int(match.group(1))
                if 1 <= count <= 1000:
                    extracted["student_count"] = count
                    break
    
    # Time slots
    time_patterns = [
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
        r"(morning|afternoon|evening)",
        r"(weekdays?|weekends?|saturday|sunday)",
    ]
    found_slots = []
    for pattern in time_patterns:
        matches = re.findall(pattern, message_lower)
        found_slots.extend(matches)
    if found_slots:
        existing = existing_draft.get("time_slots", [])
        extracted["time_slots"] = list(set(existing + found_slots))
    
    # Start date
    if "start_date" not in existing_draft:
        from datetime import date, timedelta
        today = date.today()
        if "next week" in message_lower:
            days_ahead = 7 - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            extracted["start_date"] = (today + timedelta(days=days_ahead)).isoformat()
        elif "next month" in message_lower:
            if today.month == 12:
                extracted["start_date"] = f"{today.year + 1}-01-01"
            else:
                extracted["start_date"] = f"{today.year}-{today.month + 1:02d}-01"
        elif "immediately" in message_lower or "asap" in message_lower:
            extracted["start_date"] = today.isoformat()
    
    # Duration
    if "duration_weeks" not in existing_draft:
        duration_patterns = [
            r"(\d+)\s*(?:weeks?|wks?)",
            r"(\d+)\s*(?:months?)",
        ]
        for pattern in duration_patterns:
            match = re.search(pattern, message_lower)
            if match:
                value = int(match.group(1))
                if "month" in message_lower[match.start():match.end()]:
                    value = value * 4
                if 1 <= value <= 52:
                    extracted["duration_weeks"] = value
                    break
    
    return extracted


def extract_coordinator_info(message: str) -> Dict[str, Any]:
    """Extract coordinator name and info from message."""
    info = {}
    message_lower = message.lower()
    
    # Skip if this is just a greeting or general statement
    greeting_patterns = ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening']
    if any(message_lower.strip().startswith(g) for g in greeting_patterns):
        # Only extract from greetings if there's explicit name introduction
        if not any(p in message_lower for p in ['my name is', "i'm ", 'i am ', 'call me']):
            return info
    
    # Skip if message seems to be about school rather than personal name
    school_indicators = ['school', 'vidyalaya', 'academy', 'institute', 'public', 'college']
    
    # Strict name patterns with explicit introduction
    name_patterns = [
        r"(?:my name is|i'm|i am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:this is|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            name = match.group(1).strip().title()
            stop_words = {'and', 'from', 'at', 'the', 'i', 'am', 'here', 'public', 'school', 'sunrise', 'hello', 'hi'}
            words = name.split()
            clean = [w for w in words if w.lower() not in stop_words][:2]
            
            # Check if this looks like a school name, not a person name
            if clean and not any(ind in ' '.join(clean).lower() for ind in school_indicators):
                info["name"] = " ".join(clean)
            break
    return info


def extract_school_info(message: str) -> Dict[str, Any]:
    """Extract school information from message."""
    info = {}
    school_patterns = [
        r"(?:school|vidyalaya|vidya|shala)[:\s]+([A-Za-z\s]+?)(?:,|\.|\sin|\sat|$)",
        r"(?:from|at|represent)\s+([A-Za-z\s]+?)\s+(?:school|vidyalaya)",
    ]
    for pattern in school_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            school_name = match.group(1).strip().title()
            if len(school_name) > 3:
                info["name"] = school_name
            break
    
    location_patterns = [
        r"(?:in|at|from|located in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        r"(?:village|town|city|district)[:\s]+([A-Za-z\s]+?)(?:,|\.|\s|$)",
    ]
    for pattern in location_patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            location = match.group(1).strip().title()
            if len(location) > 2 and location.lower() not in ['school', 'vidyalaya']:
                info["location"] = location
            break
    return info


def get_missing_need_fields(draft: Dict) -> List[str]:
    """Get list of missing mandatory need fields."""
    missing = []
    for field in MANDATORY_NEED_FIELDS:
        value = draft.get(field)
        if not value or (isinstance(value, list) and len(value) == 0):
            missing.append(field)
    return missing


def determine_next_need_state(
    current_state: str,
    user_message: str,
    coordinator_resolved: bool,
    school_resolved: bool,
    missing_fields: List[str]
) -> str:
    """Determine next state for need workflow."""
    message_lower = user_message.lower()
    
    # Pause signals
    pause_signals = ["pause", "stop", "later", "bye", "quit", "not now"]
    if any(signal in message_lower for signal in pause_signals):
        return "paused"
    
    # Resume from pause
    if current_state == "paused":
        resume_signals = ["continue", "resume", "ready", "back", "let's go"]
        if any(signal in message_lower for signal in resume_signals):
            if not coordinator_resolved:
                return "resolving_coordinator"
            elif not school_resolved:
                return "resolving_school"
            elif missing_fields:
                return "drafting_need"
            else:
                return "pending_approval"
    
    # State progression
    if current_state == "initiated":
        return "resolving_coordinator"
    
    if current_state == "resolving_coordinator":
        if coordinator_resolved:
            return "resolving_school"
        return current_state
    
    if current_state == "resolving_school":
        if school_resolved:
            return "drafting_need"
        return current_state
    
    if current_state == "drafting_need":
        if not missing_fields:
            return "pending_approval"
        return current_state
    
    if current_state == "pending_approval":
        confirm_signals = ["yes", "correct", "confirm", "looks good", "that's right", "perfect", "ok", "okay", "submit"]
        if any(signal in message_lower for signal in confirm_signals):
            return "approved"
        change_signals = ["no", "wrong", "change", "update", "fix", "actually"]
        if any(signal in message_lower for signal in change_signals):
            return "drafting_need"
        return current_state
    
    if current_state == "approved":
        return "fulfillment_handoff_ready"
    
    return current_state


def build_need_state_prompt(state: str, missing_fields: List[str], need_draft: Dict, coordinator: Dict = None, school: Dict = None) -> str:
    """Build contextual prompt for need coordination."""
    base = """You are helping eVidyaloka coordinate educational support for schools in rural India.
You're speaking with a Need Coordinator - someone who represents a school and helps identify what teaching support their students need.

Communication Style:
- Professional yet warm - these are partners in our mission
- Clear and efficient - coordinators are busy people
- Never use technical jargon: avoid terms like workflow, MCP, agent, system, session
- Keep responses concise (2-3 sentences)
- Ask one question at a time
"""
    
    stage_prompts = {
        "initiated": "Warmly greet the coordinator. Ask them to introduce themselves and their school.",
        "resolving_coordinator": "We need to verify the coordinator's identity. Ask for their name if not provided.",
        "resolving_school": "Ask about the school - name and location where they need teaching support.",
        "drafting_need": "Gather the specific educational need. Focus on one question at a time.",
        "pending_approval": "Summarize the need details and ask the coordinator to confirm everything is correct.",
        "approved": "The need has been recorded. Thank them and let them know we'll work on matching volunteers.",
        "paused": "Be understanding. Let them know they can return anytime to continue.",
        "human_review": "Explain that someone from our team will review the details and follow up.",
    }
    
    prompt = f"{base}\n\nSTAGE: {stage_prompts.get(state, 'Continue the conversation naturally.')}"
    
    # Add context
    if coordinator and coordinator.get("name"):
        prompt += f"\n\nCOORDINATOR: {coordinator.get('name')}"
    
    if school and school.get("name"):
        prompt += f"\nSCHOOL: {school.get('name')}"
        if school.get("location"):
            prompt += f", {school.get('location')}"
    
    # Add captured details
    if need_draft:
        captured = []
        if need_draft.get("subjects"):
            captured.append(f"Subjects: {', '.join(need_draft['subjects'])}")
        if need_draft.get("grade_levels"):
            captured.append(f"Grades: {', '.join(need_draft['grade_levels'])}")
        if need_draft.get("student_count"):
            captured.append(f"Students: {need_draft['student_count']}")
        if need_draft.get("time_slots"):
            captured.append(f"Time slots: {', '.join(need_draft['time_slots'])}")
        if need_draft.get("start_date"):
            captured.append(f"Start date: {need_draft['start_date']}")
        if need_draft.get("duration_weeks"):
            captured.append(f"Duration: {need_draft['duration_weeks']} weeks")
        if captured:
            prompt += f"\n\nCAPTURED SO FAR:\n" + "\n".join(captured)
    
    # Add guidance for missing fields
    if missing_fields and state == "drafting_need":
        field_prompts = {
            "subjects": "what subjects they need help with",
            "grade_levels": "which grade levels",
            "student_count": "how many students",
            "time_slots": "what time slots work for classes",
            "start_date": "when they want to start",
            "duration_weeks": "how long they need support"
        }
        readable = [field_prompts.get(f, f) for f in missing_fields[:2]]
        prompt += f"\n\nSTILL NEED: {', '.join(readable)}. Ask about one naturally."
    
    return prompt


async def generate_need_llm_response(prompt: str, messages: List[Dict], user_message: str) -> str:
    """Generate LLM response for need coordination."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return "Hello! Welcome to eVidyaloka. I'm here to help coordinate teaching support for your school. Could you tell me your name and which school you represent?"
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"need-{uuid4()}",
            system_message=prompt
        )
        chat.with_model("anthropic", os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929"))
        
        context = ""
        for msg in messages[-5:]:
            role = "Coordinator" if msg.get("role") == "user" else "eVidyaloka"
            context += f"{role}: {msg.get('content', '')}\n"
        
        full_msg = f"{context}\nCoordinator: {user_message}" if context else user_message
        response = await chat.send_message(UserMessage(text=full_msg))
        return response
    except Exception as e:
        logger.error(f"LLM error in need agent: {e}")
        return "Hello! Welcome to eVidyaloka. I'm here to help coordinate teaching support for your school. Could you tell me your name and which school you represent?"


async def process_need_agent_turn(request: AgentTurnRequest, routing_decision: RoutingDecision, start_time: datetime) -> AgentTurnResponse:
    """Process turn for need agent."""
    session_state = request.session_state
    current_state = session_state.stage
    telemetry = []
    session_id = str(request.session_id)
    
    # Get or initialize need draft
    need_draft = store.need_drafts.get(session_id, {})
    
    # Get coordinator and school context
    coordinator = None
    school = None
    coordinator_resolved = False
    school_resolved = False
    
    # Check if coordinator is already resolved
    if need_draft.get("coordinator_id"):
        coordinator = store.coordinators.get(need_draft["coordinator_id"])
        coordinator_resolved = True
    
    if need_draft.get("school_id"):
        school = store.schools.get(need_draft["school_id"])
        school_resolved = True
    
    # Process based on current state - try to extract all relevant info
    # Coordinator resolution
    if current_state in ["initiated", "resolving_coordinator"] and not coordinator_resolved:
        coord_info = extract_coordinator_info(request.user_message)
        if coord_info.get("name"):
            if not coordinator:
                coordinator = {
                    "id": str(uuid4()),
                    "name": coord_info["name"],
                    "whatsapp_number": None,
                    "school_ids": [],
                    "is_verified": False
                }
                store.coordinators[coordinator["id"]] = coordinator
            need_draft["coordinator_id"] = coordinator["id"]
            need_draft["coordinator_name"] = coord_info["name"]
            coordinator_resolved = True
    
    # School resolution - try during coordinator or school resolution states
    if current_state in ["resolving_coordinator", "resolving_school"] and not school_resolved:
        school_info = extract_school_info(request.user_message)
        if school_info.get("name"):
            if not school:
                school = {
                    "id": str(uuid4()),
                    "name": school_info["name"],
                    "location": school_info.get("location", ""),
                    "coordinator_ids": [need_draft.get("coordinator_id")] if need_draft.get("coordinator_id") else [],
                    "previous_needs": []
                }
                store.schools[school["id"]] = school
            need_draft["school_id"] = school["id"]
            need_draft["school_name"] = school_info["name"]
            school_resolved = True
    
    # Need details extraction - try during drafting or earlier if info provided
    if current_state in ["resolving_school", "drafting_need"]:
        extracted = extract_need_details(request.user_message, need_draft)
        if extracted:
            need_draft.update(extracted)
            logger.info(f"Extracted need details: {list(extracted.keys())}")
    
    # Save updated draft
    store.need_drafts[session_id] = need_draft
    
    # Get missing fields
    missing_fields = get_missing_need_fields(need_draft)
    
    # Determine next state
    next_state = determine_next_need_state(
        current_state, request.user_message,
        coordinator_resolved, school_resolved, missing_fields
    )
    
    # Validate transition
    if next_state != current_state:
        valid_next = NEED_VALID_TRANSITIONS.get(current_state, [])
        if next_state not in valid_next and next_state != current_state:
            logger.warning(f"Invalid need transition: {current_state} -> {next_state}")
            next_state = current_state
        else:
            telemetry.append(TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.STATE_TRANSITION,
                agent=AgentType.NEED,
                data={"from": current_state, "to": next_state}
            ))
    
    # Build prompt and generate response
    prompt = build_need_state_prompt(next_state, missing_fields, need_draft, coordinator, school)
    assistant_msg = await generate_need_llm_response(prompt, request.conversation_history, request.user_message)
    
    # Calculate duration
    duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
    
    log_orchestration_event(
        OrchestrationEventType.AGENT_RESPONDED,
        session_id,
        agent=AgentType.NEED.value,
        stage=next_state,
        duration_ms=duration_ms,
        details={'response_length': len(assistant_msg)}
    )
    
    # Determine completion status
    completion_status = "in_progress"
    handoff = None
    
    if next_state in ["approved", "fulfillment_handoff_ready"]:
        completion_status = "approved"
        handoff = HandoffEvent(
            session_id=request.session_id,
            from_agent=AgentType.NEED,
            to_agent=AgentType.FULFILLMENT,
            handoff_type=HandoffType.AGENT_TRANSITION,
            payload={
                "need_draft": need_draft,
                "school": school,
                "coordinator": coordinator
            },
            reason="Need approved, ready for volunteer matching"
        )
    elif next_state == "paused":
        completion_status = "paused"
    elif next_state == "rejected":
        completion_status = "complete"
    elif next_state == "human_review":
        completion_status = "human_review"
    
    return AgentTurnResponse(
        assistant_message=assistant_msg,
        active_agent=AgentType.NEED,
        workflow=WorkflowType.NEED_COORDINATION,
        state=next_state,
        completion_status=completion_status,
        confirmed_fields=need_draft,
        missing_fields=missing_fields,
        handoff_event=handoff,
        telemetry_events=telemetry
    )


# ============ FastAPI Application ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SERVE AI Platform...")
    yield
    logger.info("Shutting down...")

app = FastAPI(
    title="SERVE AI Platform",
    description="Multi-agent volunteer management platform with clean orchestration",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ WhatsApp Channel Adapter ============

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")  # Sandbox default

# Initialize Twilio client if configured
twilio_client = None
try:
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        from twilio.rest import Client
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        logger.info("Twilio WhatsApp client initialized")
except ImportError:
    logger.warning("Twilio library not installed - WhatsApp integration disabled")
except Exception as e:
    logger.warning(f"Twilio initialization failed: {e}")


class PhoneSessionManager:
    """Maps WhatsApp phone numbers to orchestrator sessions."""
    
    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
    
    def get_session(self, phone: str) -> Optional[Dict[str, Any]]:
        """Get existing session for phone number."""
        session = self._sessions.get(phone)
        if session:
            # Check if session is still valid (24 hour timeout)
            last_activity = datetime.fromisoformat(session["last_activity"])
            if datetime.utcnow() - last_activity > timedelta(hours=24):
                del self._sessions[phone]
                return None
        return session
    
    def create_session(self, phone: str, session_id: str, workflow: str = "need_coordination") -> Dict:
        """Create new session mapping."""
        session = {
            "phone": phone,
            "session_id": session_id,
            "workflow": workflow,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            "message_count": 0
        }
        self._sessions[phone] = session
        logger.info(f"WhatsApp session created: {phone[:6]}*** -> {session_id[:8]}...")
        return session
    
    def update_session(self, phone: str, session_id: str = None) -> Optional[Dict]:
        """Update session activity."""
        session = self._sessions.get(phone)
        if session:
            session["last_activity"] = datetime.utcnow().isoformat()
            session["message_count"] += 1
            if session_id:
                session["session_id"] = session_id
        return session
    
    def clear_session(self, phone: str) -> bool:
        """Clear session for restart."""
        if phone in self._sessions:
            del self._sessions[phone]
            return True
        return False
    
    def get_all_sessions(self) -> Dict:
        """Get all active sessions."""
        return self._sessions.copy()


# Singleton
whatsapp_sessions = PhoneSessionManager()


async def send_whatsapp_reply(to_number: str, message: str) -> bool:
    """Send WhatsApp message via Twilio."""
    if not twilio_client:
        logger.warning("Twilio not configured - cannot send WhatsApp message")
        return False
    
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"
    
    try:
        msg = twilio_client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to_number
        )
        logger.info(f"WhatsApp sent: {msg.sid}")
        return True
    except Exception as e:
        logger.error(f"WhatsApp send failed: {e}")
        return False


# ============ Orchestrator Endpoints ============

@app.post("/api/orchestrator/interact", response_model=InteractionResponse)
async def orchestrator_interact(request: InteractionRequest):
    start_time = datetime.utcnow()
    session_id = request.session_id
    session_state = None
    conversation = []
    
    if session_id:
        resume = await mcp_resume_context(str(session_id))
        if resume.status == "success" and resume.data and resume.data.get("session"):
            s = resume.data["session"]
            session_state = SessionState(
                id=UUID(s["id"]),
                channel=request.channel.value,
                persona=request.persona.value if request.persona else "new_volunteer",
                workflow=s["workflow"],
                active_agent=s["active_agent"],
                status=s["status"],
                stage=s["stage"],
                sub_state=s.get("sub_state"),
                context_summary=s.get("context_summary")
            )
            conversation = resume.data.get("conversation_history", [])
    
    if not session_state:
        persona = request.persona or PersonaType.NEW_VOLUNTEER
        
        # Determine workflow and agent based on persona
        if persona == PersonaType.NEED_COORDINATOR:
            workflow = "need_coordination"
            agent = "need"
            initial_stage = "initiated"
        else:
            workflow = "new_volunteer_onboarding"
            agent = "onboarding"
            initial_stage = "init"
        
        start = await mcp_start_session(StartSessionRequest(
            channel=request.channel,
            persona=persona,
            channel_metadata=request.channel_metadata
        ))
        
        if start.status != "success":
            raise HTTPException(500, "Failed to create session")
        
        session_id = UUID(start.data["session_id"])
        
        # Update the session with correct workflow for need coordinator
        if persona == PersonaType.NEED_COORDINATOR:
            store.sessions[str(session_id)]["workflow"] = workflow
            store.sessions[str(session_id)]["active_agent"] = agent
            store.sessions[str(session_id)]["stage"] = initial_stage
            # Initialize need draft store for this session
            store.need_drafts[str(session_id)] = {}
        
        session_state = SessionState(
            id=session_id,
            channel=request.channel.value,
            persona=persona.value,
            workflow=workflow,
            active_agent=agent,
            status="active",
            stage=initial_stage
        )
    
    log_orchestration_event(
        OrchestrationEventType.MESSAGE_RECEIVED,
        str(session_state.id),
        details={'message_length': len(request.message)}
    )
    
    await mcp_save_message(str(session_state.id), "user", request.message, session_state.active_agent)
    
    agent_request = AgentTurnRequest(
        session_id=session_state.id,
        session_state=session_state,
        user_message=request.message,
        conversation_history=conversation
    )
    
    agent_response = await process_agent_turn(agent_request)
    
    await mcp_save_message(str(session_state.id), "assistant", agent_response.assistant_message, 
                          agent_response.active_agent.value)
    
    if agent_response.state != session_state.stage:
        await mcp_advance_state(str(session_state.id), agent_response.state, agent_response.sub_state)
    
    progress = workflow_validator.get_completion_percentage(agent_response.state, session_state.workflow)
    is_terminal = workflow_validator.is_terminal_stage(agent_response.state, session_state.workflow)
    
    total_duration = (datetime.utcnow() - start_time).total_seconds() * 1000
    
    return InteractionResponse(
        session_id=session_state.id,
        assistant_message=agent_response.assistant_message,
        active_agent=agent_response.active_agent,
        workflow=agent_response.workflow,
        state=agent_response.state,
        sub_state=agent_response.sub_state,
        status=SessionStatus.COMPLETED if is_terminal else SessionStatus.ACTIVE,
        journey_progress={
            "current_state": agent_response.state,
            "progress_percent": progress,
            "confirmed_fields": agent_response.confirmed_fields,
            "missing_fields": agent_response.missing_fields
        },
        debug_info={
            "timing_ms": total_duration,
            "telemetry_events": [e.model_dump(mode="json") for e in agent_response.telemetry_events]
        } if agent_response.telemetry_events else None
    )

@app.get("/api/orchestrator/session/{session_id}")
async def get_session(session_id: UUID):
    result = await mcp_resume_context(str(session_id))
    if result.status == "error":
        raise HTTPException(404, result.error)
    return result.data

@app.get("/api/orchestrator/sessions")
async def list_sessions(status: Optional[str] = None, limit: int = 50):
    sessions = []
    for sid, s in store.sessions.items():
        if status and s["status"] != status:
            continue
        profile = store.profiles.get(sid, {})
        sessions.append({
            "id": sid,
            "status": s["status"],
            "stage": s["stage"],
            "active_agent": s["active_agent"],
            "volunteer_name": profile.get("full_name"),
            "created_at": s["created_at"],
            "updated_at": s["updated_at"]
        })
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return MCPResponse(status="success", data={"sessions": sessions[:limit]})

@app.get("/api/orchestrator/health")
async def orchestrator_health():
    return {"service": "serve-orchestrator", "status": "healthy", "version": "1.1.0"}


# ============ Onboarding Agent Endpoints ============

@app.post("/api/agents/onboarding/turn", response_model=AgentTurnResponse)
async def agent_turn(request: AgentTurnRequest):
    return await process_agent_turn(request)

@app.get("/api/agents/onboarding/health")
async def agent_health():
    return {"service": "serve-onboarding-agent-service", "status": "healthy", "version": "1.1.0"}


# ============ WhatsApp Channel Endpoints ============

# WhatsApp routes — delegated to Cloud API adapter
from channels.whatsapp_adapter import (
    whatsapp_router as _wa_router,
    set_orchestrator as _wa_set_orchestrator,
)

async def _orchestrator_interact_for_wa(
    session_id, message, channel, persona, channel_metadata
):
    """Thin wrapper so the adapter can call the orchestrator."""
    req = InteractionRequest(
        session_id=session_id,
        message=message,
        channel=ChannelType(channel),
        persona=PersonaType(persona),
        channel_metadata=channel_metadata,
    )
    resp = await orchestrator_interact(req)
    return {
        "session_id": str(resp.session_id),
        "assistant_message": resp.assistant_message,
        "workflow": resp.workflow,
    }

_wa_set_orchestrator(_orchestrator_interact_for_wa)
app.include_router(_wa_router)


# ============ MCP Capability Endpoints ============

@app.post("/api/mcp/capabilities/onboarding/start-session", response_model=MCPResponse)
async def mcp_start(request: StartSessionRequest):
    return await mcp_start_session(request)

@app.post("/api/mcp/capabilities/onboarding/resume-context", response_model=MCPResponse)
async def mcp_resume(request: ResumeContextRequest):
    return await mcp_resume_context(str(request.session_id))

@app.post("/api/mcp/capabilities/onboarding/advance-state", response_model=MCPResponse)
async def mcp_advance(request: AdvanceStateRequest):
    return await mcp_advance_state(str(request.session_id), request.new_state, request.sub_state)

@app.post("/api/mcp/capabilities/onboarding/get-missing-fields", response_model=MCPResponse)
async def mcp_missing(request: GetMissingFieldsRequest):
    return await mcp_get_missing_fields(str(request.session_id))

@app.post("/api/mcp/capabilities/onboarding/save-confirmed-fields", response_model=MCPResponse)
async def mcp_save_fields(request: SaveConfirmedFieldsRequest):
    return await mcp_save_confirmed_fields(str(request.session_id), request.fields)

@app.post("/api/mcp/capabilities/onboarding/save-message", response_model=MCPResponse)
async def mcp_message(request: SaveMessageRequest):
    return await mcp_save_message(str(request.session_id), request.role, request.content, 
                                  request.agent.value if request.agent else None)

@app.post("/api/mcp/capabilities/onboarding/get-conversation", response_model=MCPResponse)
async def mcp_conv(request: GetConversationRequest):
    messages = store.messages.get(str(request.session_id), [])
    return MCPResponse(status="success", data={"messages": messages[:request.limit]})

@app.post("/api/mcp/capabilities/onboarding/log-event", response_model=MCPResponse)
async def mcp_log(request: LogEventRequest):
    return await mcp_log_event(str(request.session_id), request.event_type.value,
                               request.agent.value if request.agent else None, request.data)

@app.post("/api/mcp/capabilities/onboarding/emit-handoff-event", response_model=MCPResponse)
async def mcp_handoff(request: EmitHandoffRequest):
    session = store.sessions.get(str(request.session_id))
    if session:
        session["active_agent"] = request.to_agent.value
    
    log_orchestration_event(
        OrchestrationEventType.HANDOFF_INITIATED,
        str(request.session_id),
        agent=request.to_agent.value,
        details={'from_agent': request.from_agent.value, 'reason': request.reason}
    )
    
    return MCPResponse(status="success", data={
        "handoff_id": str(uuid4()),
        "from_agent": request.from_agent.value,
        "to_agent": request.to_agent.value
    })

@app.post("/api/mcp/capabilities/onboarding/pause-session", response_model=MCPResponse)
async def mcp_pause(request: PauseSessionRequest):
    session = store.sessions.get(str(request.session_id))
    if not session:
        return MCPResponse(status="error", error="Session not found")
    session["status"] = "paused"
    session["stage"] = "paused"
    return MCPResponse(status="success", data={"status": "paused"})

@app.post("/api/mcp/capabilities/onboarding/evaluate-prerequisites", response_model=MCPResponse)
async def mcp_prereqs(request: GetMissingFieldsRequest):
    session = store.sessions.get(str(request.session_id))
    if not session:
        return MCPResponse(status="error", error="Session not found")
    return MCPResponse(status="success", data={"prerequisites_met": session["status"] == "active", "issues": []})

@app.post("/api/mcp/capabilities/onboarding/evaluate-readiness", response_model=MCPResponse)
async def mcp_ready(request: GetMissingFieldsRequest):
    result = await mcp_get_missing_fields(str(request.session_id))
    missing = result.data.get("missing_fields", []) if result.data else []
    return MCPResponse(status="success", data={
        "ready_for_selection": len(missing) == 0,
        "missing_fields": missing,
        "recommendation": "proceed" if len(missing) == 0 else "gather_more_info"
    })

@app.post("/api/mcp/capabilities/onboarding/prepare-selection-handoff", response_model=MCPResponse)
async def mcp_prep_handoff(request: PrepareHandoffRequest):
    session = store.sessions.get(str(request.session_id))
    profile = store.profiles.get(str(request.session_id), {})
    if not session:
        return MCPResponse(status="error", error="Session not found")
    return MCPResponse(status="success", data={
        "handoff_payload": {
            "session_id": str(request.session_id),
            "volunteer_profile": profile,
            "workflow": session["workflow"]
        },
        "target_agent": request.target_agent.value
    })

@app.get("/api/mcp/capabilities/onboarding/session/{session_id}", response_model=MCPResponse)
async def mcp_get_session(session_id: UUID):
    session = store.sessions.get(str(session_id))
    profile = store.profiles.get(str(session_id))
    if not session:
        return MCPResponse(status="error", error="Session not found")
    return MCPResponse(status="success", data={"session": session, "volunteer_profile": profile})

@app.get("/api/mcp/capabilities/onboarding/sessions", response_model=MCPResponse)
async def mcp_list_sessions(status: Optional[str] = None, limit: int = 50):
    sessions = []
    for sid, s in store.sessions.items():
        if status and s["status"] != status:
            continue
        profile = store.profiles.get(sid, {})
        sessions.append({
            "id": sid,
            "status": s["status"],
            "stage": s["stage"],
            "active_agent": s["active_agent"],
            "volunteer_name": profile.get("full_name"),
            "created_at": s["created_at"],
            "updated_at": s["updated_at"]
        })
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return MCPResponse(status="success", data={"sessions": sessions[:limit]})

@app.get("/api/mcp/capabilities/onboarding/telemetry/{session_id}", response_model=MCPResponse)
async def mcp_telemetry(session_id: UUID, limit: int = 100):
    events = store.telemetry.get(str(session_id), [])
    events.sort(key=lambda x: x["timestamp"], reverse=True)
    return MCPResponse(status="success", data={"events": events[:limit]})


# ============ Memory Summary Endpoints ============

class SaveMemorySummaryRequest(BaseModel):
    session_id: UUID
    summary_text: str
    key_facts: List[str] = []

class GetMemorySummaryRequest(BaseModel):
    session_id: UUID


@app.post("/api/mcp/capabilities/onboarding/save-memory-summary", response_model=MCPResponse)
async def mcp_save_memory(request: SaveMemorySummaryRequest):
    return await save_memory_summary(str(request.session_id), request.summary_text, request.key_facts)


@app.post("/api/mcp/capabilities/onboarding/get-memory-summary", response_model=MCPResponse)
async def mcp_get_memory(request: GetMemorySummaryRequest):
    return await get_memory_summary(str(request.session_id))


@app.get("/api/mcp/capabilities/onboarding/memory/{session_id}", response_model=MCPResponse)
async def mcp_memory_get(session_id: UUID):
    return await get_memory_summary(str(session_id))


@app.get("/api/mcp/health")
async def mcp_health():
    return {"service": "serve-agentic-mcp-service", "status": "healthy", "version": "1.2.0"}


# ============ Platform Health ============

@app.get("/api/health")
async def health():
    return {
        "platform": "SERVE AI",
        "status": "healthy",
        "version": "1.2.0",
        "services": {
            "orchestrator": "healthy",
            "onboarding_agent": "healthy",
            "mcp_service": "healthy"
        },
        "features": {
            "agent_router": True,
            "workflow_validator": True,
            "structured_logging": True,
            "memory_summarization": True
        }
    }

@app.get("/api/")
async def root():
    return {
        "message": "Welcome to SERVE AI Platform",
        "version": "1.2.0",
        "architecture": {
            "agent_router": "Intelligent routing based on workflow and stage",
            "workflow_validator": "State transition validation with field requirements",
            "structured_logging": "Comprehensive event logging for debugging",
            "memory_summarization": "Long-term conversation memory for returning volunteers"
        }
    }
