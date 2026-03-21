"""
SERVE Orchestrator - Agent Router
Handles intelligent routing of requests to the appropriate agent service.

The AgentRouter abstracts away the complexity of:
1. Determining which agent should handle a request
2. Managing agent service URLs and health
3. Providing fallback behavior when agents are unavailable
"""
import asyncio
import httpx
import os
import logging
from typing import Dict, Optional
from datetime import datetime
from uuid import UUID

from app.schemas import (
    AgentTurnRequest, AgentTurnResponse, AgentType, WorkflowType,
    SessionState, IntentType, IntentResult,
)
from app.schemas.contracts import (
    RoutingDecision, AgentInvocationContext, AgentInvocationResult,
    OrchestrationEvent, OrchestrationEventType
)

logger = logging.getLogger(__name__)

# How often (seconds) the background health-probe loop runs
_HEALTH_PROBE_INTERVAL = int(os.environ.get("AGENT_HEALTH_PROBE_INTERVAL", "30"))
# Connect + read timeout for health probes (seconds)
_HEALTH_PROBE_TIMEOUT = float(os.environ.get("AGENT_HEALTH_PROBE_TIMEOUT", "3"))


class AgentRegistry:
    """
    Registry of available agent services and their configurations.

    Health state is kept inside each agent's config dict under the 'healthy' key.
    A background asyncio task (started from main.py startup) calls
    start_health_probing() which probes each agent's /health endpoint and
    updates the 'healthy' flag so make_routing_decision always has fresh data.
    """

    def __init__(self):
        self._agents: Dict[str, Dict] = {}
        self._load_from_environment()

    def _load_from_environment(self):
        """Load agent configurations from environment variables."""
        # ── Primary agents ──────────────────────────────────────────────────
        self._agents['onboarding'] = {
            'url': os.environ.get('ONBOARDING_AGENT_URL', 'http://serve-onboarding-agent-service:8002'),
            'health_path': '/api/health',
            'endpoint': '/api/turn',
            'timeout': 60.0,
            'healthy': True,   # Optimistic until first probe
            'last_check': None,
            'workflows': ['new_volunteer_onboarding'],
            'stages': ['init', 'intent_discovery', 'purpose_orientation',
                       'eligibility_confirmation', 'capability_discovery',
                       'profile_confirmation', 'onboarding_complete', 'paused'],
        }

        self._agents['need'] = {
            'url': os.environ.get('NEED_AGENT_URL', 'http://serve-need-agent-service:8005'),
            'health_path': '/api/health',
            'endpoint': '/api/turn',
            'timeout': 60.0,
            'healthy': True,   # Optimistic until first probe
            'last_check': None,
            'workflows': ['need_coordination'],
            'stages': ['initiated', 'capturing_phone', 'resolving_coordinator',
                       'resolving_school', 'drafting_need', 'pending_approval',
                       'refinement_required', 'submitted', 'approved', 'paused',
                       'rejected', 'human_review', 'fulfillment_handoff_ready'],
        }

        # ── Engagement agent — re-engages returning volunteers ───────────────
        # This agent is not yet deployed; it starts unhealthy and the router
        # falls back gracefully to onboarding until the service is available.
        self._agents['engagement'] = {
            'url': os.environ.get('ENGAGEMENT_AGENT_URL', 'http://serve-engagement-agent-service:8006'),
            'health_path': '/api/health',
            'endpoint': '/api/turn',
            'timeout': 60.0,
            'healthy': False,  # Conservative — undeployed; first probe may flip to True
            'last_check': None,
            'workflows': ['returning_volunteer', 'volunteer_engagement'],
            'stages': ['re_engaging', 'profile_refresh', 'matching_ready', 'paused'],
        }

        # ── Helpline agent — cross-cutting support queries ───────────────────
        self._agents['helpline'] = {
            'url': os.environ.get('HELPLINE_AGENT_URL', 'http://serve-helpline-agent-service:8007'),
            'health_path': '/api/health',
            'endpoint': '/api/turn',
            'timeout': 60.0,
            'healthy': False,  # Conservative — undeployed
            'last_check': None,
            'workflows': [],   # Cross-cutting — activated by intent, not workflow
            'stages': [],
        }

    # ── Health probing ───────────────────────────────────────────────────────

    async def _probe_health(self, agent_id: str, config: Dict) -> None:
        """Probe a single agent's /health endpoint and update config['healthy']."""
        url = f"{config['url']}{config.get('health_path', '/api/health')}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=_HEALTH_PROBE_TIMEOUT)
                is_healthy = resp.status_code < 400
        except Exception:
            is_healthy = False

        previous = config.get('healthy')
        config['healthy'] = is_healthy
        config['last_check'] = datetime.utcnow()

        if previous != is_healthy:
            level = logger.info if is_healthy else logger.warning
            level(
                f"Agent '{agent_id}' health changed: "
                f"{'HEALTHY' if is_healthy else 'UNHEALTHY'} ({url})"
            )

    async def start_health_probing(self, interval_seconds: int = _HEALTH_PROBE_INTERVAL) -> None:
        """
        Background loop — probe every agent every `interval_seconds` seconds.

        Start this as an asyncio task from the FastAPI startup event:
            asyncio.create_task(agent_router.registry.start_health_probing())
        """
        logger.info(
            f"Agent health-probe loop starting — interval={interval_seconds}s, "
            f"agents={list(self._agents)}"
        )
        while True:
            for agent_id, config in self._agents.items():
                try:
                    await self._probe_health(agent_id, config)
                except Exception as exc:
                    logger.warning(f"Health probe for '{agent_id}' raised unexpectedly: {exc}")
            await asyncio.sleep(interval_seconds)

    # ── Registry queries ─────────────────────────────────────────────────────

    def get_agent_config(self, agent_id: str) -> Optional[Dict]:
        """Get configuration for a specific agent."""
        return self._agents.get(agent_id)

    def is_agent_available(self, agent_id: str) -> bool:
        """Check if an agent is registered and currently healthy."""
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
        user_message: str,
        intent: Optional[IntentResult] = None,
    ) -> RoutingDecision:
        """
        Determine which agent should handle the current request.

        Intent is now factored in:
          - SEEK_HELP  → route to current agent with reduced confidence so it
                         knows to slow down and be more explanatory.
          - RESUME_SESSION → same as CONTINUE but flagged in routing_context.
          - All others → standard stage/workflow routing.

        Args:
            session_context: Current session state.
            user_message:    The user's message text.
            intent:          Resolved IntentResult (may be None for legacy callers).

        Returns:
            RoutingDecision with target agent and reasoning.
        """
        current_agent = session_context.active_agent
        current_stage = session_context.stage
        workflow = session_context.workflow
        intent_value = intent.intent.value if intent else "unknown"

        # ── SEEK_HELP: route to current agent but signal lower confidence so the
        #    agent knows to be more patient and explanatory in its response.
        if intent and intent.intent == IntentType.SEEK_HELP:
            if self.registry.is_agent_available(current_agent):
                return RoutingDecision(
                    target_agent=current_agent,
                    confidence=0.75,
                    reason=f"User needs help at stage '{current_stage}' — routing to {current_agent} with help hint",
                    routing_context={
                        'decision_type': 'help',
                        'stage': current_stage,
                        'workflow': workflow,
                        'intent': intent_value,
                    }
                )

        # ── Returning-volunteer workflow: prefer engagement agent, fall back to
        #    onboarding if engagement is not yet deployed / unhealthy.
        if workflow == 'returning_volunteer':
            if self.registry.is_agent_available('engagement'):
                return RoutingDecision(
                    target_agent='engagement',
                    confidence=1.0,
                    reason=f"Returning volunteer workflow — routing to engagement agent (stage '{current_stage}')",
                    fallback_agent='onboarding',
                    routing_context={
                        'decision_type': 'returning_volunteer',
                        'stage': current_stage,
                        'workflow': workflow,
                        'intent': intent_value,
                    }
                )
            else:
                # Engagement service not yet deployed — graceful degradation
                logger.warning(
                    f"Engagement agent unavailable for returning_volunteer workflow "
                    f"(session stage='{current_stage}'). Falling back to onboarding."
                )
                return RoutingDecision(
                    target_agent='onboarding',
                    confidence=0.6,
                    reason="Returning-volunteer: engagement agent unavailable, gracefully routing to onboarding",
                    routing_context={
                        'decision_type': 'returning_volunteer_fallback',
                        'stage': current_stage,
                        'workflow': workflow,
                        'intent': intent_value,
                    }
                )

        # ── Standard routing: current agent can handle this stage
        if self.registry.is_agent_available(current_agent):
            config = self.registry.get_agent_config(current_agent)
            if current_stage in config.get('stages', []):
                decision_type = (
                    'resume' if intent and intent.intent == IntentType.RESUME_SESSION
                    else 'continue'
                )
                return RoutingDecision(
                    target_agent=current_agent,
                    confidence=1.0,
                    reason=f"Continuing with {current_agent} for stage '{current_stage}'",
                    routing_context={
                        'decision_type': decision_type,
                        'stage': current_stage,
                        'workflow': workflow,
                        'intent': intent_value,
                    }
                )

        # ── Stage-based lookup: find the right agent for this stage
        stage_agent = self.registry.get_agent_for_stage(current_stage)
        if stage_agent and self.registry.is_agent_available(stage_agent):
            return RoutingDecision(
                target_agent=stage_agent,
                confidence=0.9,
                reason=f"Routing to {stage_agent} as handler for stage '{current_stage}'",
                fallback_agent=current_agent,
                routing_context={
                    'decision_type': 'stage_based',
                    'stage': current_stage,
                    'workflow': workflow,
                    'intent': intent_value,
                }
            )

        # ── Fallback: stay with current agent
        return RoutingDecision(
            target_agent=current_agent,
            confidence=0.5,
            reason=f"Fallback to {current_agent} — no specific handler found for stage '{current_stage}'",
            routing_context={
                'decision_type': 'fallback',
                'stage': current_stage,
                'workflow': workflow,
                'intent': intent_value,
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
