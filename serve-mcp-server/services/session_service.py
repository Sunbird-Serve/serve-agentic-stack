"""
SERVE MCP Server - Session Service
Handles session lifecycle operations (create, resume, advance state)
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


class InMemorySessionStore:
    """
    In-memory session storage for development/preview.
    In production, this would be replaced with actual database calls.
    """
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.messages: Dict[str, List[Dict]] = {}
        self.telemetry: Dict[str, List[Dict]] = {}


# Global store instance
_store = InMemorySessionStore()


class SessionService:
    """
    Service for managing volunteer onboarding sessions.
    """
    
    async def create_session(
        self,
        channel: str = "web_ui",
        persona: str = "new_volunteer"
    ) -> Dict[str, Any]:
        """Create a new onboarding session."""
        session_id = str(uuid4())
        now = datetime.utcnow().isoformat()
        
        session = {
            "id": session_id,
            "channel": channel,
            "persona": persona,
            "workflow": "new_volunteer_onboarding",
            "active_agent": "onboarding",
            "status": "active",
            "stage": "init",
            "sub_state": None,
            "context_summary": None,
            "created_at": now,
            "updated_at": now,
        }
        
        _store.sessions[session_id] = session
        _store.messages[session_id] = []
        _store.telemetry[session_id] = []
        
        logger.info(f"Session created: {session_id}")
        
        return {
            "status": "success",
            "session_id": session_id,
            "stage": "init",
            "workflow": "new_volunteer_onboarding"
        }
    
    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session state."""
        session = _store.sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        
        return {
            "status": "success",
            "session": session
        }
    
    async def resume_context(self, session_id: str) -> Dict[str, Any]:
        """Resume session with full context."""
        session = _store.sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        
        # Import profile service to get profile
        from .profile_service import ProfileService
        profile_service = ProfileService()
        profile_result = await profile_service.get_profile(session_id)
        
        messages = _store.messages.get(session_id, [])[-10:]
        
        return {
            "status": "success",
            "session": session,
            "volunteer_profile": profile_result.get("profile", {}),
            "conversation_history": messages,
            "memory_summary": None  # Would come from memory service
        }
    
    async def advance_state(
        self,
        session_id: str,
        new_state: str,
        sub_state: Optional[str] = None
    ) -> Dict[str, Any]:
        """Advance session to new state."""
        session = _store.sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        
        old_state = session["stage"]
        
        # Validate transition
        valid_transitions = {
            'init': ['intent_discovery'],
            'intent_discovery': ['purpose_orientation', 'paused'],
            'purpose_orientation': ['eligibility_confirmation', 'paused'],
            'eligibility_confirmation': ['capability_discovery', 'paused'],
            'capability_discovery': ['profile_confirmation', 'paused'],
            'profile_confirmation': ['onboarding_complete', 'capability_discovery', 'paused'],
            'onboarding_complete': [],
            'paused': ['init', 'intent_discovery', 'purpose_orientation', 
                      'eligibility_confirmation', 'capability_discovery', 'profile_confirmation'],
        }
        
        allowed = valid_transitions.get(old_state, [])
        is_valid = new_state in allowed or old_state == new_state
        
        if not is_valid:
            return {
                "status": "error",
                "error": f"Invalid transition from {old_state} to {new_state}",
                "valid_transitions": allowed
            }
        
        session["stage"] = new_state
        session["sub_state"] = sub_state
        session["updated_at"] = datetime.utcnow().isoformat()
        
        if new_state == "onboarding_complete":
            session["status"] = "completed"
        
        return {
            "status": "success",
            "previous_state": old_state,
            "current_state": new_state,
            "is_valid": True
        }
    
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """Save a conversation message."""
        if session_id not in _store.messages:
            _store.messages[session_id] = []
        
        message_id = str(uuid4())
        message = {
            "id": message_id,
            "role": role,
            "content": content,
            "agent": agent,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        _store.messages[session_id].append(message)
        
        return {
            "status": "success",
            "message_id": message_id
        }
    
    async def get_conversation(
        self,
        session_id: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get conversation history."""
        messages = _store.messages.get(session_id, [])
        return {
            "status": "success",
            "messages": messages[-limit:]
        }
    
    async def log_event(
        self,
        session_id: str,
        event_type: str,
        agent: Optional[str] = None,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Log a telemetry event."""
        if session_id not in _store.telemetry:
            _store.telemetry[session_id] = []
        
        event_id = str(uuid4())
        event = {
            "id": event_id,
            "event_type": event_type,
            "agent": agent,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        _store.telemetry[session_id].append(event)
        
        return {
            "status": "success",
            "event_id": event_id
        }
