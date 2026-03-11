"""
SERVE Orchestrator Service - Agent Client
HTTP client for calling agent services
"""
import httpx
import os
import logging
from typing import Dict, Any

from app.schemas import AgentTurnRequest, AgentTurnResponse, AgentType

logger = logging.getLogger(__name__)

ONBOARDING_AGENT_URL = os.environ.get("ONBOARDING_AGENT_URL", "http://serve-onboarding-agent-service:8002")


class AgentClient:
    """HTTP client for agent service communication"""
    
    def __init__(self):
        self.timeout = 60.0
        self.agent_urls = {
            AgentType.ONBOARDING: ONBOARDING_AGENT_URL,
            # Future agents would be added here
        }
    
    async def call_agent(self, agent: AgentType, request: AgentTurnRequest) -> AgentTurnResponse:
        """Route request to the appropriate agent service"""
        url = self.agent_urls.get(agent)
        if not url:
            logger.error(f"Agent {agent} not configured")
            return AgentTurnResponse(
                assistant_message="I apologize, but this agent is not yet available.",
                active_agent=agent,
                workflow=request.session_state.workflow,
                state=request.session_state.stage,
                telemetry_events=[]
            )
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{url}/api/turn",
                    json=request.model_dump(mode="json"),
                    timeout=self.timeout
                )
                response.raise_for_status()
                return AgentTurnResponse(**response.json())
            except httpx.HTTPError as e:
                logger.error(f"Agent call failed: {agent} - {e}")
                return AgentTurnResponse(
                    assistant_message="I apologize, but I encountered an issue. Please try again.",
                    active_agent=agent,
                    workflow=request.session_state.workflow,
                    state=request.session_state.stage,
                    telemetry_events=[]
                )


# Singleton instance
agent_client = AgentClient()
