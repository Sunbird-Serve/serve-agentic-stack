"""
SERVE Need Agent Service - Domain Client
HTTP client for calling Domain Service capabilities.
"""
import httpx
import os
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

DOMAIN_SERVICE_URL = os.environ.get("DOMAIN_SERVICE_URL", "http://serve-domain-service:8003")


class DomainClient:
    """HTTP client for Domain Service communication."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or DOMAIN_SERVICE_URL
        self.timeout = 30.0
    
    async def call_capability(self, endpoint: str, payload: Dict[str, Any]) -> Dict:
        """Call a domain service capability endpoint."""
        url = f"{self.base_url}/api/capabilities/need/{endpoint}"
        
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
                logger.error(f"Domain service call failed: {endpoint} - {e}")
                return {"status": "error", "error": str(e)}
    
    # ============ Coordinator Operations ============
    
    async def resolve_coordinator_identity(
        self, 
        whatsapp_number: str, 
        name: Optional[str] = None
    ) -> Dict:
        """Resolve coordinator identity from WhatsApp number."""
        return await self.call_capability("resolve-coordinator", {
            "whatsapp_number": whatsapp_number,
            "name": name
        })
    
    async def map_coordinator_to_school(
        self, 
        coordinator_id: str, 
        school_id: str
    ) -> Dict:
        """Map a coordinator to an existing school."""
        return await self.call_capability("map-coordinator-school", {
            "coordinator_id": coordinator_id,
            "school_id": school_id
        })
    
    # ============ School Operations ============
    
    async def resolve_school_context(
        self,
        coordinator_id: Optional[str] = None,
        school_hint: Optional[str] = None
    ) -> Dict:
        """Resolve school context."""
        return await self.call_capability("resolve-school", {
            "coordinator_id": coordinator_id,
            "school_hint": school_hint
        })
    
    async def create_basic_school_context(
        self,
        name: str,
        location: str,
        contact_number: Optional[str] = None
    ) -> Dict:
        """Create a new school context."""
        return await self.call_capability("create-school", {
            "name": name,
            "location": location,
            "contact_number": contact_number
        })
    
    async def fetch_previous_need_context(
        self,
        school_id: str
    ) -> Dict:
        """Fetch previous need context for a school."""
        return await self.call_capability("fetch-previous-needs", {
            "school_id": school_id
        })
    
    # ============ Need Operations ============
    
    async def create_or_update_need_draft(
        self,
        session_id: str,
        need_data: Dict[str, Any]
    ) -> Dict:
        """Create or update a need draft."""
        return await self.call_capability("save-need-draft", {
            "session_id": session_id,
            "need_data": need_data
        })
    
    async def get_missing_need_fields(self, session_id: str) -> Dict:
        """Get missing fields for a need draft."""
        return await self.call_capability("get-missing-fields", {
            "session_id": session_id
        })
    
    async def evaluate_need_readiness(self, session_id: str) -> Dict:
        """Evaluate if need is ready for submission."""
        return await self.call_capability("evaluate-readiness", {
            "session_id": session_id
        })
    
    async def submit_need_for_approval(self, need_id: str) -> Dict:
        """Submit need for approval."""
        return await self.call_capability("submit-for-approval", {
            "need_id": need_id
        })
    
    async def update_need_status(
        self, 
        need_id: str, 
        status: str,
        comments: Optional[str] = None
    ) -> Dict:
        """Update need status."""
        return await self.call_capability("update-status", {
            "need_id": need_id,
            "status": status,
            "comments": comments
        })
    
    # ============ Session Operations ============
    
    async def start_need_session(
        self,
        channel: str,
        whatsapp_number: Optional[str] = None,
        channel_metadata: Optional[Dict] = None
    ) -> Dict:
        """Start a new need session."""
        return await self.call_capability("start-session", {
            "channel": channel,
            "whatsapp_number": whatsapp_number,
            "channel_metadata": channel_metadata
        })
    
    async def resume_need_context(self, session_id: str) -> Dict:
        """Resume an existing need session."""
        return await self.call_capability("resume-context", {
            "session_id": session_id
        })
    
    async def advance_need_state(
        self,
        session_id: str,
        new_state: str,
        sub_state: Optional[str] = None
    ) -> Dict:
        """Advance need session state."""
        return await self.call_capability("advance-state", {
            "session_id": session_id,
            "new_state": new_state,
            "sub_state": sub_state
        })
    
    async def pause_need_session(
        self,
        session_id: str,
        reason: Optional[str] = None
    ) -> Dict:
        """Pause a need session."""
        return await self.call_capability("pause-session", {
            "session_id": session_id,
            "reason": reason
        })
    
    # ============ Handoff Operations ============
    
    async def prepare_fulfillment_handoff(self, need_id: str) -> Dict:
        """Prepare handoff payload for fulfillment."""
        return await self.call_capability("prepare-handoff", {
            "need_id": need_id
        })
    
    async def emit_handoff_event(
        self,
        session_id: str,
        from_agent: str,
        to_agent: str,
        payload: Dict[str, Any]
    ) -> Dict:
        """Emit handoff event."""
        return await self.call_capability("emit-handoff", {
            "session_id": session_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "payload": payload
        })
    
    # ============ Telemetry ============
    
    async def log_need_event(
        self,
        session_id: str,
        event_type: str,
        data: Optional[Dict] = None
    ) -> Dict:
        """Log a need lifecycle event."""
        return await self.call_capability("log-event", {
            "session_id": session_id,
            "event_type": event_type,
            "data": data or {}
        })
    
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: Optional[str] = None
    ) -> Dict:
        """Save a conversation message."""
        return await self.call_capability("save-message", {
            "session_id": session_id,
            "role": role,
            "content": content,
            "agent": agent
        })


# Singleton instance
domain_client = DomainClient()
