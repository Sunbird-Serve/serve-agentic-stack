"""
SERVE AI Platform - Combined Backend Server
This runs all services together for development/demo environment.
In production, each service runs independently on its own port.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import sys
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ Inline Schemas (to avoid import complexity) ============

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


# ============ Request/Response Models ============

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


# ============ In-Memory Store (for demo without Postgres) ============

from uuid import uuid4
import re

class InMemoryStore:
    def __init__(self):
        self.sessions = {}
        self.profiles = {}
        self.messages = {}
        self.telemetry = {}

store = InMemoryStore()


# ============ MCP Capabilities (inline implementation) ============

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
    session["stage"] = new_state
    session["sub_state"] = sub_state
    session["updated_at"] = datetime.utcnow().isoformat()
    
    if new_state == "onboarding_complete":
        session["status"] = "completed"
    
    return MCPResponse(status="success", data={
        "session_id": session_id,
        "previous_state": old_state,
        "current_state": new_state
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


# ============ Onboarding Agent Logic ============

STATE_PROMPTS = {
    "init": """You are SERVE AI, a friendly volunteer onboarding assistant. Warmly greet the user and ask what brings them to volunteer. Keep response to 2-3 sentences.""",
    "intent_discovery": """You are SERVE AI in Intent Discovery. Understand why the volunteer wants to participate and what impact they hope to make. Acknowledge their motivation.""",
    "purpose_orientation": """You are SERVE AI in Purpose Orientation. Share briefly how SERVE connects volunteers with opportunities. Ask what activities interest them.""",
    "eligibility_confirmation": """You are SERVE AI in Eligibility Confirmation. Gather basic info: name, email, location. Ask for one piece at a time.""",
    "capability_discovery": """You are SERVE AI in Capability Discovery. Explore skills, availability, and preferred volunteer work. Be encouraging.""",
    "profile_confirmation": """You are SERVE AI in Profile Confirmation. Summarize what you've learned and ask if anything needs updating.""",
    "onboarding_complete": """You are SERVE AI completing onboarding. Congratulate them and explain what happens next (matching with opportunities).""",
}

def determine_next_state(current_state: str, message: str, missing_fields: List[str]) -> str:
    pause_signals = ["pause", "stop", "later", "bye", "quit", "exit"]
    if any(s in message.lower() for s in pause_signals):
        return "paused"
    
    if current_state == "init":
        return "intent_discovery"
    elif current_state == "intent_discovery" and len(message.split()) > 5:
        return "purpose_orientation"
    elif current_state == "purpose_orientation":
        return "eligibility_confirmation"
    elif current_state == "eligibility_confirmation" and len(missing_fields) < 3:
        return "capability_discovery"
    elif current_state == "capability_discovery" and ("skill" in message.lower() or len(missing_fields) < 2):
        return "profile_confirmation"
    elif current_state == "profile_confirmation":
        confirms = ["yes", "correct", "confirm", "looks good", "that's right"]
        if any(c in message.lower() for c in confirms):
            return "onboarding_complete"
    
    return current_state

def extract_fields(message: str) -> Dict[str, Any]:
    fields = {}
    lower = message.lower()
    
    for signal in ["my name is", "i'm ", "i am ", "call me "]:
        if signal in lower:
            start = lower.index(signal) + len(signal)
            words = message[start:].split()[:3]
            name = " ".join(words).strip(".,!?")
            if name and len(name) > 1:
                fields["full_name"] = name.title()
                break
    
    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', message)
    if emails:
        fields["email"] = emails[0]
    
    skills = ["programming", "teaching", "writing", "design", "marketing", "cooking", 
              "driving", "healthcare", "communication", "leadership", "organizing"]
    found = [s for s in skills if s in lower]
    if found:
        fields["skills"] = found
    
    for signal in ["i live in", "i'm from", "located in", "based in"]:
        if signal in lower:
            start = lower.index(signal) + len(signal)
            words = message[start:].split()[:3]
            loc = " ".join(words).strip(".,!?")
            if loc:
                fields["location"] = loc.title()
                break
    
    return fields

async def generate_llm_response(system_prompt: str, messages: List[Dict], user_message: str) -> str:
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        return "Thank you for your message! I'm here to help you with volunteer onboarding. Could you tell me about yourself and what motivates you to volunteer?"
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        
        chat = LlmChat(
            api_key=api_key,
            session_id=f"onboarding-{id(chat)}",
            system_message=system_prompt
        )
        chat.with_model("anthropic", os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929"))
        
        context = ""
        for msg in messages[-5:]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            context += f"{role}: {msg.get('content', '')}\n"
        
        full_msg = f"{context}\nUser: {user_message}" if context else user_message
        response = await chat.send_message(UserMessage(text=full_msg))
        return response
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return "Thank you! I'm here to help with your volunteer onboarding. What brings you to SERVE today?"

async def process_agent_turn(request: AgentTurnRequest) -> AgentTurnResponse:
    session_state = request.session_state
    current_state = session_state.stage
    telemetry = []
    
    # Get missing fields
    missing_result = await mcp_get_missing_fields(str(request.session_id))
    missing_fields = missing_result.data.get("missing_fields", []) if missing_result.data else []
    confirmed_fields = missing_result.data.get("confirmed_fields", {}) if missing_result.data else {}
    
    # Extract fields from message
    extracted = extract_fields(request.user_message)
    if extracted:
        await mcp_save_confirmed_fields(str(request.session_id), extracted)
        confirmed_fields.update(extracted)
        missing_fields = [f for f in missing_fields if f not in extracted]
    
    # Determine next state
    next_state = determine_next_state(current_state, request.user_message, missing_fields)
    
    if next_state != current_state:
        telemetry.append(TelemetryEvent(
            session_id=request.session_id,
            event_type=EventType.STATE_TRANSITION,
            agent=AgentType.ONBOARDING,
            data={"from": current_state, "to": next_state}
        ))
    
    # Get prompt and generate response
    prompt = STATE_PROMPTS.get(next_state, STATE_PROMPTS["init"])
    if missing_fields:
        prompt += f"\n\nStill needed: {', '.join(missing_fields)}. Ask about one naturally."
    if confirmed_fields:
        prompt += f"\n\nConfirmed: {confirmed_fields}"
    
    assistant_msg = await generate_llm_response(prompt, request.conversation_history, request.user_message)
    
    handoff = None
    if next_state == "onboarding_complete":
        handoff = HandoffEvent(
            session_id=request.session_id,
            from_agent=AgentType.ONBOARDING,
            to_agent=AgentType.SELECTION,
            handoff_type=HandoffType.AGENT_TRANSITION,
            payload={"confirmed_fields": confirmed_fields},
            reason="Onboarding completed"
        )
    
    return AgentTurnResponse(
        assistant_message=assistant_msg,
        active_agent=AgentType.ONBOARDING,
        workflow=WorkflowType(session_state.workflow),
        state=next_state,
        completion_status="complete" if next_state == "onboarding_complete" else "in_progress",
        confirmed_fields=confirmed_fields,
        missing_fields=missing_fields,
        handoff_event=handoff,
        telemetry_events=telemetry
    )


# ============ FastAPI Application ============

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SERVE AI Platform (Combined Mode)...")
    yield
    logger.info("Shutting down...")

app = FastAPI(
    title="SERVE AI Platform",
    description="Multi-agent volunteer management platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ Orchestrator Endpoints ============

@app.post("/api/orchestrator/interact", response_model=InteractionResponse)
async def orchestrator_interact(request: InteractionRequest):
    """Process user interaction through orchestrator"""
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
        start = await mcp_start_session(StartSessionRequest(
            channel=request.channel,
            persona=persona,
            channel_metadata=request.channel_metadata
        ))
        
        if start.status != "success":
            raise HTTPException(500, "Failed to create session")
        
        session_id = UUID(start.data["session_id"])
        session_state = SessionState(
            id=session_id,
            channel=request.channel.value,
            persona=persona.value,
            workflow="new_volunteer_onboarding",
            active_agent="onboarding",
            status="active",
            stage="init"
        )
    
    # Save user message
    await mcp_save_message(str(session_state.id), "user", request.message, session_state.active_agent)
    
    # Process through agent
    agent_request = AgentTurnRequest(
        session_id=session_state.id,
        session_state=session_state,
        user_message=request.message,
        conversation_history=conversation
    )
    
    agent_response = await process_agent_turn(agent_request)
    
    # Save assistant response
    await mcp_save_message(str(session_state.id), "assistant", agent_response.assistant_message, 
                          agent_response.active_agent.value)
    
    # Update state
    if agent_response.state != session_state.stage:
        await mcp_advance_state(str(session_state.id), agent_response.state, agent_response.sub_state)
    
    # Calculate progress
    states = ["init", "intent_discovery", "purpose_orientation", "eligibility_confirmation",
              "capability_discovery", "profile_confirmation", "onboarding_complete"]
    idx = states.index(agent_response.state) if agent_response.state in states else 0
    progress = round((idx / (len(states) - 1)) * 100)
    
    return InteractionResponse(
        session_id=session_state.id,
        assistant_message=agent_response.assistant_message,
        active_agent=agent_response.active_agent,
        workflow=agent_response.workflow,
        state=agent_response.state,
        sub_state=agent_response.sub_state,
        status=SessionStatus.COMPLETED if agent_response.state == "onboarding_complete" else SessionStatus.ACTIVE,
        journey_progress={
            "current_state": agent_response.state,
            "progress_percent": progress,
            "confirmed_fields": agent_response.confirmed_fields,
            "missing_fields": agent_response.missing_fields
        }
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
    return {"service": "serve-orchestrator", "status": "healthy", "version": "1.0.0"}


# ============ Onboarding Agent Endpoints ============

@app.post("/api/agents/onboarding/turn", response_model=AgentTurnResponse)
async def agent_turn(request: AgentTurnRequest):
    return await process_agent_turn(request)

@app.get("/api/agents/onboarding/health")
async def agent_health():
    return {"service": "serve-onboarding-agent-service", "status": "healthy", "version": "1.0.0"}


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

@app.get("/api/mcp/health")
async def mcp_health():
    return {"service": "serve-agentic-mcp-service", "status": "healthy", "version": "1.0.0"}


# ============ Platform Health ============

@app.get("/api/health")
async def health():
    return {
        "platform": "SERVE AI",
        "status": "healthy",
        "mode": "combined",
        "services": {
            "orchestrator": "healthy",
            "onboarding_agent": "healthy",
            "mcp_service": "healthy"
        }
    }

@app.get("/api/")
async def root():
    return {
        "message": "Welcome to SERVE AI Platform",
        "mode": "combined (development)",
        "version": "1.0.0",
        "note": "In production, each service runs independently"
    }
