"""
SERVE Orchestrator Service - Domain Client
HTTP client for calling Domain Service capabilities

Note: This client uses HTTP to communicate with serve-domain-service.
For MCP protocol access, use a separate MCP client.
"""
import httpx
import os
import logging
from typing import Dict, Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Domain service URL (HTTP API, renamed from MCP service)
DOMAIN_SERVICE_URL = os.environ.get(
    "DOMAIN_SERVICE_URL",
    os.environ.get("MCP_SERVICE_URL", "http://serve-domain-service:8003")  # Backward compat
)


class DomainClient:
    """HTTP client for Domain Service communication"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or DOMAIN_SERVICE_URL
        self.timeout = 30.0
    
    async def call_capability(self, endpoint: str, payload: Dict[str, Any]) -> Dict:
        """Call a domain capability endpoint"""
        url = f"{self.base_url}/api/capabilities/onboarding/{endpoint}"
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(f"Domain call failed: {endpoint} - {e}")
                return {"status": "error", "error": str(e)}
    
    async def start_session(self, channel: str, persona: str, channel_metadata: Optional[Dict] = None) -> Dict:
        """Start a new session"""
        return await self.call_capability("start-session", {
            "channel": channel,
            "persona": persona,
            "channel_metadata": channel_metadata
        })
    
    async def resume_context(self, session_id: UUID) -> Dict:
        """Resume existing session context"""
        return await self.call_capability("resume-context", {
            "session_id": str(session_id)
        })
    
    async def advance_state(self, session_id: UUID, new_state: str, sub_state: str = None) -> Dict:
        """Advance session state"""
        return await self.call_capability("advance-state", {
            "session_id": str(session_id),
            "new_state": new_state,
            "sub_state": sub_state
        })
    
    async def save_message(self, session_id: UUID, role: str, content: str, agent: str = None) -> Dict:
        """Save conversation message"""
        payload = {
            "session_id": str(session_id),
            "role": role,
            "content": content
        }
        if agent:
            payload["agent"] = agent
        return await self.call_capability("save-message", payload)
    
    async def emit_handoff_event(
        self, 
        session_id: UUID, 
        from_agent: str, 
        to_agent: str, 
        handoff_type: str,
        payload: Dict = None,
        reason: str = None
    ) -> Dict:
        """Emit handoff event"""
        request_payload = {
            "session_id": str(session_id),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "handoff_type": handoff_type,
            "payload": payload or {},
        }
        if reason:
            request_payload["reason"] = reason
        return await self.call_capability("emit-handoff-event", request_payload)
    
    async def get_session(self, session_id: UUID) -> Dict:
        """Get session details"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/api/capabilities/onboarding/session/{session_id}",
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(f"Get session failed: {e}")
                return {"status": "error", "error": str(e)}
    
    async def list_sessions(self, status: str = None, limit: int = 50) -> Dict:
        """List all sessions"""
        async with httpx.AsyncClient() as client:
            try:
                params = {"limit": limit}
                if status:
                    params["status"] = status
                response = await client.get(
                    f"{self.base_url}/api/capabilities/onboarding/sessions",
                    params=params,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                logger.error(f"List sessions failed: {e}")
                return {"status": "error", "error": str(e)}


# Singleton instances
domain_client = DomainClient()

# Backward compatibility alias
mcp_client = domain_client
