"""
SERVE Orchestrator Service - Orchestration Logic (Refactored)
Central coordination layer for SERVE AI with clean abstractions.

This module integrates:
- AgentRouter for intelligent request routing
- WorkflowValidator for state transition validation
- Structured contracts for inter-service communication
"""
from uuid import UUID
from datetime import datetime
import logging

from app.schemas import (
    InteractionRequest, InteractionResponse, SessionState,
    AgentTurnRequest, AgentTurnResponse,
    PersonaType, WorkflowType, AgentType, SessionStatus, OnboardingState
)
from app.schemas.contracts import (
    RoutingDecision, TransitionValidation, SessionContext,
    OrchestrationEvent, OrchestrationEventType
)
from app.clients import mcp_client
from app.service.agent_router import agent_router
from app.service.workflow_validator import workflow_validator

logger = logging.getLogger(__name__)


def determine_workflow(persona: PersonaType) -> WorkflowType:
    """
    Determine the appropriate workflow based on persona type.
    
    This mapping defines which workflow handles each persona:
    - New volunteers → Onboarding workflow
    - Returning volunteers → Engagement workflow (future)
    - Need coordinators → Need coordination workflow (future)
    """
    persona_workflow_map = {
        PersonaType.NEW_VOLUNTEER: WorkflowType.NEW_VOLUNTEER_ONBOARDING,
        PersonaType.RETURNING_VOLUNTEER: WorkflowType.RETURNING_VOLUNTEER,
        PersonaType.NEED_COORDINATOR: WorkflowType.NEED_COORDINATION,
    }
    return persona_workflow_map.get(persona, WorkflowType.NEW_VOLUNTEER_ONBOARDING)


def determine_initial_agent(workflow: WorkflowType) -> AgentType:
    """
    Determine the initial agent for a workflow.
    
    Each workflow starts with a specific agent:
    - Onboarding workflow → Onboarding agent
    - Returning volunteer → Engagement agent (future)
    - Need coordination → Need agent (future)
    """
    workflow_agent_map = {
        WorkflowType.NEW_VOLUNTEER_ONBOARDING: AgentType.ONBOARDING,
        WorkflowType.RETURNING_VOLUNTEER: AgentType.ENGAGEMENT,
        WorkflowType.NEED_COORDINATION: AgentType.NEED,
    }
    return workflow_agent_map.get(workflow, AgentType.ONBOARDING)


class OrchestrationService:
    """
    Central orchestration service implementing the coordination pattern.
    
    Responsibilities:
    1. Session lifecycle management (create, resume, complete)
    2. Request routing to appropriate agents
    3. State transition validation and persistence
    4. Structured logging of all orchestration events
    """
    
    async def process_interaction(self, request: InteractionRequest) -> InteractionResponse:
        """
        Process an incoming user interaction.
        
        This is the main entry point from channel adapters. The flow:
        1. Resolve or create session
        2. Route request to appropriate agent
        3. Validate and apply state transitions
        4. Return structured response
        """
        start_time = datetime.utcnow()
        session_context = None
        conversation = []
        
        # Step 1: Resolve or create session
        if request.session_id:
            session_context, conversation = await self._resume_session(request)
        
        if not session_context:
            session_context = await self._create_session(request)
        
        # Log session context established
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.SESSION_RESUMED if request.session_id 
                       else OrchestrationEventType.SESSION_CREATED,
            workflow=session_context.workflow,
            stage=session_context.current_stage,
            details={'channel': session_context.channel, 'persona': session_context.persona}
        )
        
        # Step 2: Save user message
        await mcp_client.save_message(
            session_id=session_context.session_id,
            role="user",
            content=request.message,
            agent=session_context.active_agent
        )
        
        # Log message received
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.MESSAGE_RECEIVED,
            details={'message_length': len(request.message)}
        )
        
        # Step 3: Make routing decision
        session_state = SessionState(
            id=session_context.session_id,
            channel=session_context.channel,
            persona=session_context.persona,
            workflow=session_context.workflow,
            active_agent=session_context.active_agent,
            status=session_context.status,
            stage=session_context.current_stage,
            sub_state=session_context.sub_state,
            context_summary=session_context.context_summary,
            created_at=session_context.created_at.isoformat() if session_context.created_at else None,
            updated_at=session_context.updated_at.isoformat() if session_context.updated_at else None
        )
        
        routing_decision = agent_router.make_routing_decision(session_state, request.message)
        
        # Log routing decision
        agent_router.log_routing_event(
            session_id=session_context.session_id,
            decision=routing_decision
        )
        
        # Step 4: Invoke agent
        agent_request = AgentTurnRequest(
            session_id=session_context.session_id,
            session_state=session_state,
            user_message=request.message,
            conversation_history=conversation
        )
        
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.AGENT_INVOKED,
            agent=routing_decision.target_agent,
            details={'confidence': routing_decision.confidence}
        )
        
        agent_response = await agent_router.invoke_agent(routing_decision, agent_request)
        
        # Log agent response
        agent_duration = (datetime.utcnow() - start_time).total_seconds() * 1000
        self._log_event(
            session_id=session_context.session_id,
            event_type=OrchestrationEventType.AGENT_RESPONDED,
            agent=agent_response.active_agent.value,
            stage=agent_response.state,
            duration_ms=agent_duration,
            details={
                'response_length': len(agent_response.assistant_message),
                'completion_status': agent_response.completion_status
            }
        )
        
        # Step 5: Validate and apply state transition
        if agent_response.state != session_context.current_stage:
            validation = workflow_validator.validate_transition(
                workflow_id=session_context.workflow,
                from_state=session_context.current_stage,
                to_state=agent_response.state,
                confirmed_fields=agent_response.confirmed_fields,
                session_id=session_context.session_id
            )
            
            workflow_validator.log_validation_event(
                session_id=session_context.session_id,
                validation=validation,
                workflow_id=session_context.workflow
            )
            
            if validation.is_valid:
                await mcp_client.advance_state(
                    session_id=session_context.session_id,
                    new_state=agent_response.state,
                    sub_state=agent_response.sub_state
                )
            else:
                logger.warning(f"Invalid transition blocked: {validation.reason}")
        
        # Step 6: Save assistant message
        await mcp_client.save_message(
            session_id=session_context.session_id,
            role="assistant",
            content=agent_response.assistant_message,
            agent=agent_response.active_agent.value
        )
        
        # Step 7: Handle handoff if present
        if agent_response.handoff_event:
            await mcp_client.emit_handoff_event(
                session_id=session_context.session_id,
                from_agent=agent_response.handoff_event.from_agent.value,
                to_agent=agent_response.handoff_event.to_agent.value,
                handoff_type=agent_response.handoff_event.handoff_type.value,
                payload=agent_response.handoff_event.payload,
                reason=agent_response.handoff_event.reason
            )
            
            self._log_event(
                session_id=session_context.session_id,
                event_type=OrchestrationEventType.HANDOFF_INITIATED,
                agent=agent_response.handoff_event.to_agent.value,
                details={
                    'from_agent': agent_response.handoff_event.from_agent.value,
                    'reason': agent_response.handoff_event.reason
                }
            )
        
        # Step 8: Calculate progress and build response
        progress_percent = workflow_validator.get_completion_percentage(
            workflow_id=session_context.workflow,
            current_stage=agent_response.state
        )
        
        is_complete = workflow_validator.is_terminal_stage(
            workflow_id=session_context.workflow,
            stage=agent_response.state
        )
        
        total_duration = (datetime.utcnow() - start_time).total_seconds() * 1000
        
        return InteractionResponse(
            session_id=session_context.session_id,
            assistant_message=agent_response.assistant_message,
            active_agent=agent_response.active_agent,
            workflow=agent_response.workflow,
            state=agent_response.state,
            sub_state=agent_response.sub_state,
            status=SessionStatus.COMPLETED if is_complete else SessionStatus.ACTIVE,
            journey_progress={
                "current_state": agent_response.state,
                "progress_percent": progress_percent,
                "confirmed_fields": agent_response.confirmed_fields,
                "missing_fields": agent_response.missing_fields,
            },
            debug_info={
                "routing": {
                    "target_agent": routing_decision.target_agent,
                    "confidence": routing_decision.confidence,
                    "reason": routing_decision.reason
                },
                "timing_ms": total_duration,
                "telemetry_events": [e.model_dump(mode="json") for e in agent_response.telemetry_events]
            } if agent_response.telemetry_events else None
        )
    
    async def _resume_session(self, request: InteractionRequest) -> tuple:
        """
        Resume an existing session.
        
        Returns:
            Tuple of (SessionContext, conversation_history)
        """
        resume_result = await mcp_client.resume_context(request.session_id)
        
        if resume_result.get("status") != "success":
            return None, []
        
        data = resume_result.get("data", {})
        session_data = data.get("session")
        
        if not session_data:
            return None, []
        
        session_context = SessionContext(
            session_id=UUID(session_data["id"]),
            channel=request.channel.value,
            persona=request.persona.value if request.persona else session_data.get("persona", "new_volunteer"),
            workflow=session_data["workflow"],
            active_agent=session_data["active_agent"],
            status=session_data["status"],
            current_stage=session_data["stage"],
            sub_state=session_data.get("sub_state"),
            context_summary=session_data.get("context_summary"),
            volunteer_profile=data.get("volunteer_profile"),
            created_at=datetime.fromisoformat(session_data["created_at"]) if session_data.get("created_at") else None,
            updated_at=datetime.fromisoformat(session_data["updated_at"]) if session_data.get("updated_at") else None
        )
        
        conversation = data.get("conversation_history", [])
        
        return session_context, conversation
    
    async def _create_session(self, request: InteractionRequest) -> SessionContext:
        """
        Create a new session.
        
        Returns:
            SessionContext for the new session
        """
        persona = request.persona or PersonaType.NEW_VOLUNTEER
        workflow = determine_workflow(persona)
        initial_agent = determine_initial_agent(workflow)
        
        start_result = await mcp_client.start_session(
            channel=request.channel.value,
            persona=persona.value,
            channel_metadata=request.channel_metadata
        )
        
        if start_result.get("status") != "success":
            raise Exception("Failed to create session")
        
        session_id = UUID(start_result["data"]["session_id"])
        now = datetime.utcnow()
        
        return SessionContext(
            session_id=session_id,
            channel=request.channel.value,
            persona=persona.value,
            workflow=workflow.value,
            active_agent=initial_agent.value,
            status=SessionStatus.ACTIVE.value,
            current_stage=OnboardingState.INIT.value,
            created_at=now,
            updated_at=now
        )
    
    def _log_event(
        self,
        session_id: UUID,
        event_type: OrchestrationEventType,
        agent: str = None,
        workflow: str = None,
        stage: str = None,
        duration_ms: float = None,
        details: dict = None
    ):
        """
        Create and log an orchestration event.
        """
        event = OrchestrationEvent(
            event_type=event_type,
            session_id=session_id,
            agent=agent,
            workflow=workflow,
            stage=stage,
            duration_ms=duration_ms,
            details=details or {}
        )
        
        logger.info(f"Orchestration: {event.to_log_dict()}")
    
    async def get_session(self, session_id: UUID) -> dict:
        """Get session state."""
        return await mcp_client.get_session(session_id)
    
    async def list_sessions(self, status: str = None, limit: int = 50) -> dict:
        """List all sessions."""
        return await mcp_client.list_sessions(status, limit)


# Singleton instance
orchestration_service = OrchestrationService()
