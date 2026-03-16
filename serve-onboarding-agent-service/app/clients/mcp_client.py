"""
SERVE Onboarding Agent Service - MCP Client
HTTP client for calling MCP service capabilities
"""
import httpx
import os
import logging
from typing import Dict, Any, List
from uuid import UUID

logger = logging.getLogger(__name__)

MCP_SERVICE_URL = os.environ.get("MCP_SERVICE_URL", "http://serve-agentic-mcp-service:8003")


class MCPClient:
    """HTTP client for MCP service communication"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or MCP_SERVICE_URL
        self.timeout = 30.0
    
    async def call_capability(self, endpoint: str, payload: Dict[str, Any]) -> Dict:
        """Call an MCP capability endpoint"""
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
                logger.error(f"MCP call failed: {endpoint} - {e}")
                return {"status": "error", "error": str(e)}
    
    async def get_missing_fields(self, session_id: UUID) -> Dict:
        """Get missing profile fields"""
        return await self.call_capability("get-missing-fields", {
            "session_id": str(session_id)
        })
    
    async def save_confirmed_fields(self, session_id: UUID, fields: Dict[str, Any]) -> Dict:
        """Save confirmed profile fields"""
        return await self.call_capability("save-confirmed-fields", {
            "session_id": str(session_id),
            "fields": fields
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
    
    async def log_event(self, session_id: UUID, event_type: str, agent: str = None, data: Dict = None) -> Dict:
        """Log telemetry event"""
        payload = {
            "session_id": str(session_id),
            "event_type": event_type
        }
        if agent:
            payload["agent"] = agent
        if data:
            payload["data"] = data
        return await self.call_capability("log-event", payload)
    
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

    async def save_memory_summary(
        self,
        session_id: UUID,
        summary_text: str,
        key_facts: List[str] = None
    ) -> Dict[str, Any]:
        """Save a memory summary for the session."""
        return await self.call_capability("save-memory-summary", {
            "session_id": str(session_id),
            "summary_text": summary_text,
            "key_facts": key_facts or []
        })
    
    async def get_memory_summary(self, session_id: UUID) -> Dict[str, Any]:
        """Get memory summary for a session."""
        return await self.call_capability("get-memory-summary", {
            "session_id": str(session_id)
        })


# Singleton instance
mcp_client = MCPClient()
