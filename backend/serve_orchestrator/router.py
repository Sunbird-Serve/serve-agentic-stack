"""
SERVE AI - Orchestrator Service
Central coordination layer for the SERVE ecosystem
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import Optional
from uuid import UUID
import httpx
import os

from shared.contracts import (
    InteractionRequest, InteractionResponse, SessionState,
    AgentTurnRequest, AgentTurnResponse, HealthResponse
)
from shared.enums import (
    AgentType, WorkflowType, SessionStatus, OnboardingState,
    ChannelType, PersonaType
)

orchestrator_router = APIRouter(prefix="/orchestrator", tags=["Orchestrator"])

# Internal service URLs (same server for now, but separate logical services)
MCP_BASE_URL = os.environ.get("MCP_SERVICE_URL", "http://localhost:8001/api/mcp")
ONBOARDING_AGENT_URL = os.environ.get("ONBOARDING_AGENT_URL", "http://localhost:8001/api/agents/onboarding")


async def call_mcp_capability(endpoint: str, payload: dict) -> dict:
    """Call MCP capability endpoint"""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{MCP_BASE_URL}/capabilities/onboarding/{endpoint}",
                json=payload,
                timeout=30.0
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}


async def call_agent(agent: AgentType, request: AgentTurnRequest) -> AgentTurnResponse:
    """Route request to the appropriate agent service"""
    agent_urls = {
        AgentType.ONBOARDING: ONBOARDING_AGENT_URL,
    }
    
    url = agent_urls.get(agent)
    if not url:
        raise HTTPException(status_code=400, detail=f"Agent {agent} not implemented")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{url}/turn",
                json=request.model_dump(mode="json"),
                timeout=60.0
            )
            return AgentTurnResponse(**response.json())
        except Exception as e:
            # Return error response
            return AgentTurnResponse(
                assistant_message=f"I apologize, but I encountered an issue. Please try again.",
                active_agent=agent,
                workflow=request.session_state.workflow,
                state=request.session_state.stage,
                telemetry_events=[]
            )


def determine_workflow(persona: PersonaType) -> WorkflowType:
    """Determine workflow based on persona"""
    persona_workflow_map = {
        PersonaType.NEW_VOLUNTEER: WorkflowType.NEW_VOLUNTEER_ONBOARDING,
        PersonaType.RETURNING_VOLUNTEER: WorkflowType.RETURNING_VOLUNTEER,
        PersonaType.NEED_COORDINATOR: WorkflowType.NEED_COORDINATION,
    }
    return persona_workflow_map.get(persona, WorkflowType.NEW_VOLUNTEER_ONBOARDING)


def determine_initial_agent(workflow: WorkflowType) -> AgentType:
    """Determine initial agent based on workflow"""
    workflow_agent_map = {
        WorkflowType.NEW_VOLUNTEER_ONBOARDING: AgentType.ONBOARDING,
        WorkflowType.RETURNING_VOLUNTEER: AgentType.ENGAGEMENT,
        WorkflowType.NEED_COORDINATION: AgentType.NEED,
    }
    return workflow_agent_map.get(workflow, AgentType.ONBOARDING)


@orchestrator_router.post("/interact", response_model=InteractionResponse)
async def process_interaction(request: InteractionRequest):
    """
    Process incoming user interaction.
    Main entry point from channel adapters.
    """
    session_id = request.session_id
    session_state = None
    
    # Resolve or create session
    if session_id:
        # Resume existing session
        resume_result = await call_mcp_capability("resume-context", {"session_id": str(session_id)})
        
        if resume_result.get("status") == "success" and resume_result.get("data", {}).get("session"):
            session_data = resume_result["data"]["session"]
            session_state = SessionState(
                id=UUID(session_data["id"]),
                channel=request.channel,
                persona=PersonaType(request.persona.value) if request.persona else PersonaType.NEW_VOLUNTEER,
                workflow=WorkflowType(session_data["workflow"]),
                active_agent=AgentType(session_data["active_agent"]),
                status=SessionStatus(session_data["status"]),
                stage=session_data["stage"],
                sub_state=session_data.get("sub_state"),
                context_summary=session_data.get("context_summary"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            # Get conversation history
            conversation = resume_result["data"].get("conversation_history", [])
    
    if not session_state:
        # Create new session
        persona = request.persona or PersonaType.NEW_VOLUNTEER
        workflow = determine_workflow(persona)
        
        start_result = await call_mcp_capability("start-session", {
            "channel": request.channel.value,
            "persona": persona.value,
            "channel_metadata": request.channel_metadata
        })
        
        if start_result.get("status") != "success":
            raise HTTPException(status_code=500, detail="Failed to create session")
        
        session_id = UUID(start_result["data"]["session_id"])
        
        session_state = SessionState(
            id=session_id,
            channel=request.channel,
            persona=persona,
            workflow=workflow,
            active_agent=determine_initial_agent(workflow),
            status=SessionStatus.ACTIVE,
            stage=OnboardingState.INIT.value,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        conversation = []
    
    # Save user message
    await call_mcp_capability("save-message", {
        "session_id": str(session_state.id),
        "role": "user",
        "content": request.message,
        "agent": session_state.active_agent.value
    })
    
    # Route to agent
    agent_request = AgentTurnRequest(
        session_id=session_state.id,
        session_state=session_state,
        user_message=request.message,
        conversation_history=conversation
    )
    
    agent_response = await call_agent(session_state.active_agent, agent_request)
    
    # Save assistant message
    await call_mcp_capability("save-message", {
        "session_id": str(session_state.id),
        "role": "assistant",
        "content": agent_response.assistant_message,
        "agent": agent_response.active_agent.value
    })
    
    # Update session state if changed
    if agent_response.state != session_state.stage:
        await call_mcp_capability("advance-state", {
            "session_id": str(session_state.id),
            "new_state": agent_response.state,
            "sub_state": agent_response.sub_state
        })
    
    # Handle handoff if present
    if agent_response.handoff_event:
        await call_mcp_capability("emit-handoff-event", {
            "session_id": str(session_state.id),
            "from_agent": agent_response.handoff_event.from_agent.value,
            "to_agent": agent_response.handoff_event.to_agent.value,
            "handoff_type": agent_response.handoff_event.handoff_type.value,
            "payload": agent_response.handoff_event.payload,
            "reason": agent_response.handoff_event.reason
        })
    
    # Calculate journey progress
    state_order = [s.value for s in OnboardingState]
    current_index = state_order.index(agent_response.state) if agent_response.state in state_order else 0
    total_states = len(state_order) - 1  # Exclude PAUSED
    progress = round((current_index / total_states) * 100) if total_states > 0 else 0
    
    return InteractionResponse(
        session_id=session_state.id,
        assistant_message=agent_response.assistant_message,
        active_agent=agent_response.active_agent,
        workflow=agent_response.workflow,
        state=agent_response.state,
        sub_state=agent_response.sub_state,
        status=SessionStatus.COMPLETED if agent_response.state == OnboardingState.ONBOARDING_COMPLETE.value else SessionStatus.ACTIVE,
        journey_progress={
            "current_state": agent_response.state,
            "progress_percent": progress,
            "confirmed_fields": agent_response.confirmed_fields,
            "missing_fields": agent_response.missing_fields,
        },
        debug_info={
            "telemetry_events": [e.model_dump(mode="json") for e in agent_response.telemetry_events]
        } if agent_response.telemetry_events else None
    )


@orchestrator_router.get("/session/{session_id}")
async def get_session_state(session_id: UUID):
    """Get current session state"""
    result = await call_mcp_capability("resume-context", {"session_id": str(session_id)})
    
    if result.get("status") != "success":
        raise HTTPException(status_code=404, detail="Session not found")
    
    return result["data"]


@orchestrator_router.get("/sessions")
async def list_sessions(status: Optional[str] = None, limit: int = 50):
    """List all sessions for ops view"""
    async with httpx.AsyncClient() as client:
        try:
            params = {"limit": limit}
            if status:
                params["status"] = status
            response = await client.get(
                f"{MCP_BASE_URL}/capabilities/onboarding/sessions",
                params=params,
                timeout=30.0
            )
            return response.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@orchestrator_router.get("/health", response_model=HealthResponse)
async def orchestrator_health():
    """Health check for orchestrator service"""
    return HealthResponse(
        service="serve-orchestrator",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )
