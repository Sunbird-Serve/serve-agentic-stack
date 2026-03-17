"""
SERVE Orchestrator - Agent Router
Handles intelligent routing of requests to the appropriate agent service.

The AgentRouter abstracts away the complexity of:
1. Determining which agent should handle a request
2. Managing agent service URLs and health
3. Providing fallback behavior when agents are unavailable
"""
import httpx
import os
import logging
from typing import Dict, Optional
from datetime import datetime
from uuid import UUID

from app.schemas import (
    AgentTurnRequest, AgentTurnResponse, AgentType, WorkflowType,
    SessionState
)
from app.schemas.contracts import (
    RoutingDecision, AgentInvocationContext, AgentInvocationResult,
    OrchestrationEvent, OrchestrationEventType
)

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Registry of available agent services and their configurations.
    """
    
    def __init__(self):
        self._agents: Dict[str, Dict] = {}
        self._load_from_environment()
    
    def _load_from_environment(self):
        """Load agent configurations from environment variables."""
        # Onboarding Agent
        self._agents['onboarding'] = {
            'url': os.environ.get('ONBOARDING_AGENT_URL', 'http://serve-onboarding-agent-service:8002'),
            'endpoint': '/api/turn',
            'timeout': 60.0,
            'healthy': True,
            'last_check': None,
            'workflows': ['new_volunteer_onboarding'],
            'stages': ['init', 'intent_discovery', 'purpose_orientation', 
                      'eligibility_confirmation', 'capability_discovery', 
                      'profile_confirmation', 'onboarding_complete', 'paused']
        }
        
        # Need Agent
        self._agents['need'] = {
            'url': os.environ.get('NEED_AGENT_URL', 'http://serve-need-agent-service:8005'),
            'endpoint': '/api/turn',
            'timeout': 60.0,
            'healthy': True,
            'last_check': None,
            'workflows': ['need_coordination'],
            'stages': ['initiated', 'resolving_coordinator', 'resolving_school',
                      'drafting_need', 'pending_approval', 'refinement_required',
                      'approved', 'paused', 'rejected', 'human_review',
                      'fulfillment_handoff_ready']
        }
        
        # Future agents would be registered here
        # self._agents['selection'] = {...}
        # self._agents['fulfillment'] = {...}
    
    def get_agent_config(self, agent_id: str) -> Optional[Dict]:
        """Get configuration for a specific agent."""
        return self._agents.get(agent_id)
    
    def is_agent_available(self, agent_id: str) -> bool:
        """Check if an agent is registered and marked as healthy."""
        config = self._agents.get(agent_id)
        return config is not None and config.get('healthy', False)
    
    def get_agents_for_workflow(self, workflow: str) -> list:
        """Get all agents that can handle a given workflow."""
        return [
            agent_id for agent_id, config in self._agents.items()
            if workflow in config.get('workflows', [])
        ]
    
    def get_agent_for_stage(self, stage: str) -> Optional[str]:
        """Get the agent responsible for a given stage."""
        for agent_id, config in self._agents.items():
            if stage in config.get('stages', []):
                return agent_id
        return None


class AgentRouter:
    """
    Central router for directing requests to appropriate agent services.
    
    Responsibilities:
    - Route requests based on workflow, stage, and context
    - Handle agent unavailability gracefully
    - Log routing decisions for debugging
    - Provide consistent fallback behavior
    """
    
    def __init__(self):
        self.registry = AgentRegistry()
        self.http_timeout = 60.0
    
    def make_routing_decision(
        self,
        session_context: SessionState,
        user_message: str
    ) -> RoutingDecision:
        """
        Determine which agent should handle the current request.
        
        Args:
            session_context: Current session state
            user_message: The user's message
            
        Returns:
            RoutingDecision with target agent and reasoning
        """
        current_agent = session_context.active_agent
        current_stage = session_context.stage
        workflow = session_context.workflow
        
        # Check if current agent can continue handling
        if self.registry.is_agent_available(current_agent):
            config = self.registry.get_agent_config(current_agent)
            if current_stage in config.get('stages', []):
                return RoutingDecision(
                    target_agent=current_agent,
                    confidence=1.0,
                    reason=f"Continuing with {current_agent} for stage {current_stage}",
                    routing_context={
                        'decision_type': 'continue',
                        'stage': current_stage,
                        'workflow': workflow
                    }
                )
        
        # Find agent for current stage
        stage_agent = self.registry.get_agent_for_stage(current_stage)
        if stage_agent and self.registry.is_agent_available(stage_agent):
            return RoutingDecision(
                target_agent=stage_agent,
                confidence=0.9,
                reason=f"Routing to {stage_agent} as handler for stage {current_stage}",
                fallback_agent=current_agent,
                routing_context={
                    'decision_type': 'stage_based',
                    'stage': current_stage,
                    'workflow': workflow
                }
            )
        
        # Fallback to current agent
        return RoutingDecision(
            target_agent=current_agent,
            confidence=0.5,
            reason=f"Fallback to {current_agent} - no specific handler found",
            routing_context={
                'decision_type': 'fallback',
                'stage': current_stage,
                'workflow': workflow
            }
        )
    
    async def invoke_agent(
        self,
        routing_decision: RoutingDecision,
        request: AgentTurnRequest
    ) -> AgentTurnResponse:
        """
        Invoke the target agent with the given request.
        
        Args:
            routing_decision: The routing decision specifying target agent
            request: The agent turn request
            
        Returns:
            AgentTurnResponse from the agent
        """
        target_agent = routing_decision.target_agent
        config = self.registry.get_agent_config(target_agent)
        
        if not config:
            logger.error(f"Agent {target_agent} not configured")
            return self._create_error_response(
                request,
                f"Agent {target_agent} is not configured"
            )
        
        url = f"{config['url']}{config['endpoint']}"
        timeout = config.get('timeout', self.http_timeout)
        
        start_time = datetime.utcnow()
        
        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"Invoking agent {target_agent} at {url}")
                
                response = await client.post(
                    url,
                    json=request.model_dump(mode='json'),
                    timeout=timeout
                )
                response.raise_for_status()
                
                duration_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
                logger.info(f"Agent {target_agent} responded in {duration_ms:.2f}ms")
                
                return AgentTurnResponse(**response.json())
                
            except httpx.TimeoutException:
                logger.error(f"Agent {target_agent} timed out after {timeout}s")
                return self._create_error_response(
                    request,
                    "The request took too long. Please try again.",
                    use_fallback=routing_decision.fallback_agent
                )
                
            except httpx.HTTPStatusError as e:
                logger.error(f"Agent {target_agent} returned error: {e.response.status_code}")
                return self._create_error_response(
                    request,
                    "There was an issue processing your request.",
                    use_fallback=routing_decision.fallback_agent
                )
                
            except Exception as e:
                logger.error(f"Agent invocation failed: {e}")
                return self._create_error_response(
                    request,
                    "I encountered an issue. Please try again.",
                    use_fallback=routing_decision.fallback_agent
                )
    
    def _create_error_response(
        self,
        request: AgentTurnRequest,
        error_message: str,
        use_fallback: Optional[str] = None
    ) -> AgentTurnResponse:
        """Create a graceful error response."""
        return AgentTurnResponse(
            assistant_message=error_message,
            active_agent=AgentType(use_fallback or request.session_state.active_agent),
            workflow=WorkflowType(request.session_state.workflow),
            state=request.session_state.stage,
            telemetry_events=[]
        )
    
    def log_routing_event(
        self,
        session_id: UUID,
        decision: RoutingDecision,
        success: bool = True,
        duration_ms: Optional[float] = None
    ) -> OrchestrationEvent:
        """
        Create a structured log event for a routing decision.
        """
        event = OrchestrationEvent(
            event_type=OrchestrationEventType.ROUTING_DECISION,
            session_id=session_id,
            agent=decision.target_agent,
            success=success,
            duration_ms=duration_ms,
            details={
                'confidence': decision.confidence,
                'reason': decision.reason,
                'fallback': decision.fallback_agent,
                'context': decision.routing_context
            }
        )
        
        logger.info(f"Routing: {event.to_log_dict()}")
        return event


# Singleton instance
agent_router = AgentRouter()
