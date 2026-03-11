"""
SERVE Orchestrator Service - Orchestration Logic
Central coordination layer for SERVE AI
"""
from uuid import UUID
from datetime import datetime
import logging

from app.schemas import (
    InteractionRequest, InteractionResponse, SessionState,
    AgentTurnRequest, AgentTurnResponse,
    PersonaType, WorkflowType, AgentType, SessionStatus, OnboardingState
)
from app.clients import mcp_client, agent_client

logger = logging.getLogger(__name__)


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


class OrchestrationService:
    """Service implementing orchestration logic"""
    
    async def process_interaction(self, request: InteractionRequest) -> InteractionResponse:
        """
        Process incoming user interaction.
        Main entry point from channel adapters.
        """
        session_id = request.session_id
        session_state = None
        conversation = []
        
        # Resolve or create session
        if session_id:
            # Resume existing session
            resume_result = await mcp_client.resume_context(session_id)
            
            if resume_result.get("status") == "success" and resume_result.get("data", {}).get("session"):
                session_data = resume_result["data"]["session"]
                session_state = SessionState(
                    id=UUID(session_data["id"]),
                    channel=request.channel.value,
                    persona=request.persona.value if request.persona else "new_volunteer",
                    workflow=session_data["workflow"],
                    active_agent=session_data["active_agent"],
                    status=session_data["status"],
                    stage=session_data["stage"],
                    sub_state=session_data.get("sub_state"),
                    context_summary=session_data.get("context_summary"),
                    created_at=session_data.get("created_at"),
                    updated_at=session_data.get("updated_at")
                )
                conversation = resume_result["data"].get("conversation_history", [])
        
        if not session_state:
            # Create new session
            persona = request.persona or PersonaType.NEW_VOLUNTEER
            workflow = determine_workflow(persona)
            
            start_result = await mcp_client.start_session(
                channel=request.channel.value,
                persona=persona.value,
                channel_metadata=request.channel_metadata
            )
            
            if start_result.get("status") != "success":
                raise Exception("Failed to create session")
            
            session_id = UUID(start_result["data"]["session_id"])
            now = datetime.utcnow().isoformat()
            
            session_state = SessionState(
                id=session_id,
                channel=request.channel.value,
                persona=persona.value,
                workflow=workflow.value,
                active_agent=determine_initial_agent(workflow).value,
                status=SessionStatus.ACTIVE.value,
                stage=OnboardingState.INIT.value,
                created_at=now,
                updated_at=now
            )
            conversation = []
        
        # Save user message
        await mcp_client.save_message(
            session_id=session_state.id,
            role="user",
            content=request.message,
            agent=session_state.active_agent
        )
        
        # Route to agent
        agent_request = AgentTurnRequest(
            session_id=session_state.id,
            session_state=session_state,
            user_message=request.message,
            conversation_history=conversation
        )
        
        agent_response = await agent_client.call_agent(
            AgentType(session_state.active_agent),
            agent_request
        )
        
        # Save assistant message
        await mcp_client.save_message(
            session_id=session_state.id,
            role="assistant",
            content=agent_response.assistant_message,
            agent=agent_response.active_agent.value
        )
        
        # Update session state if changed
        if agent_response.state != session_state.stage:
            await mcp_client.advance_state(
                session_id=session_state.id,
                new_state=agent_response.state,
                sub_state=agent_response.sub_state
            )
        
        # Handle handoff if present
        if agent_response.handoff_event:
            await mcp_client.emit_handoff_event(
                session_id=session_state.id,
                from_agent=agent_response.handoff_event.from_agent.value,
                to_agent=agent_response.handoff_event.to_agent.value,
                handoff_type=agent_response.handoff_event.handoff_type.value,
                payload=agent_response.handoff_event.payload,
                reason=agent_response.handoff_event.reason
            )
        
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
    
    async def get_session(self, session_id: UUID) -> dict:
        """Get session state"""
        return await mcp_client.get_session(session_id)
    
    async def list_sessions(self, status: str = None, limit: int = 50) -> dict:
        """List all sessions"""
        return await mcp_client.list_sessions(status, limit)


# Singleton instance
orchestration_service = OrchestrationService()
