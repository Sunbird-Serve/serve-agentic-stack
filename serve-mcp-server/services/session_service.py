"""
SERVE MCP Server - Session Service
Handles session lifecycle operations (create, resume, advance state)

Supports both PostgreSQL (production) and in-memory (development) storage.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4, UUID
import logging

logger = logging.getLogger(__name__)


# In-memory fallback storage
class InMemorySessionStore:
    """In-memory session storage for development/preview."""
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.messages: Dict[str, List[Dict]] = {}
        self.telemetry: Dict[str, List[Dict]] = {}

_memory_store = InMemorySessionStore()


class SessionService:
    """
    Service for managing volunteer onboarding sessions.
    Automatically uses Postgres if available, falls back to in-memory.
    """
    
    def __init__(self):
        self._use_postgres = False
    
    async def _check_postgres(self) -> bool:
        """Check if Postgres is available."""
        try:
            from .database import test_connection
            return await test_connection()
        except ImportError:
            return False
    
    async def create_session(
        self,
        channel: str = "web_ui",
        persona: str = "new_volunteer"
    ) -> Dict[str, Any]:
        """Create a new onboarding session."""
        session_id = str(uuid4())
        now = datetime.utcnow()
        
        # Try Postgres first
        if await self._check_postgres():
            try:
                from .database import get_db, Session, VolunteerProfile
                async with get_db() as db:
                    session = Session(
                        id=UUID(session_id),
                        channel=channel,
                        persona=persona,
                        workflow="new_volunteer_onboarding",
                        active_agent="onboarding",
                        status="active",
                        stage="init",
                        created_at=now,
                        updated_at=now
                    )
                    db.add(session)
                    
                    # Create empty profile
                    profile = VolunteerProfile(
                        session_id=UUID(session_id),
                        skills=[],
                        interests=[],
                        created_at=now,
                        updated_at=now
                    )
                    db.add(profile)
                    await db.flush()
                    
                logger.info(f"Session created in Postgres: {session_id}")
                return {
                    "status": "success",
                    "session_id": session_id,
                    "stage": "init",
                    "workflow": "new_volunteer_onboarding",
                    "storage": "postgres"
                }
            except Exception as e:
                logger.warning(f"Postgres create failed, using memory: {e}")
        
        # Fallback to in-memory
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
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        
        _memory_store.sessions[session_id] = session
        _memory_store.messages[session_id] = []
        _memory_store.telemetry[session_id] = []
        
        logger.info(f"Session created in memory: {session_id}")
        
        return {
            "status": "success",
            "session_id": session_id,
            "stage": "init",
            "workflow": "new_volunteer_onboarding",
            "storage": "memory"
        }
    
    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session state."""
        # Try Postgres
        if await self._check_postgres():
            try:
                from .database import get_db, Session
                from sqlalchemy import select
                async with get_db() as db:
                    result = await db.execute(
                        select(Session).where(Session.id == UUID(session_id))
                    )
                    session = result.scalar_one_or_none()
                    if session:
                        return {
                            "status": "success",
                            "session": {
                                "id": str(session.id),
                                "channel": session.channel,
                                "persona": session.persona,
                                "workflow": session.workflow,
                                "active_agent": session.active_agent,
                                "status": session.status,
                                "stage": session.stage,
                                "sub_state": session.sub_state,
                                "context_summary": session.context_summary,
                                "created_at": session.created_at.isoformat() if session.created_at else None,
                                "updated_at": session.updated_at.isoformat() if session.updated_at else None
                            }
                        }
            except Exception as e:
                logger.warning(f"Postgres get failed: {e}")
        
        # Fallback to memory
        session = _memory_store.sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        
        return {"status": "success", "session": session}
    
    async def resume_context(self, session_id: str) -> Dict[str, Any]:
        """Resume session with full context."""
        session_result = await self.get_session(session_id)
        if session_result.get("status") != "success":
            return session_result
        
        session = session_result.get("session", {})
        
        # Get profile
        from .profile_service import ProfileService
        profile_service = ProfileService()
        profile_result = await profile_service.get_profile(session_id)
        
        # Get messages
        messages = _memory_store.messages.get(session_id, [])[-10:]
        
        return {
            "status": "success",
            "session": session,
            "volunteer_profile": profile_result.get("profile", {}),
            "conversation_history": messages,
            "memory_summary": None
        }
    
    async def advance_state(
        self,
        session_id: str,
        new_state: str,
        sub_state: Optional[str] = None
    ) -> Dict[str, Any]:
        """Advance session to new state."""
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
        
        session_result = await self.get_session(session_id)
        if session_result.get("status") != "success":
            return session_result
        
        session = session_result.get("session", {})
        old_state = session.get("stage", "init")
        
        allowed = valid_transitions.get(old_state, [])
        is_valid = new_state in allowed or old_state == new_state
        
        if not is_valid:
            return {
                "status": "error",
                "error": f"Invalid transition from {old_state} to {new_state}",
                "valid_transitions": allowed
            }
        
        # Update in memory store
        if session_id in _memory_store.sessions:
            _memory_store.sessions[session_id]["stage"] = new_state
            _memory_store.sessions[session_id]["sub_state"] = sub_state
            _memory_store.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
            
            if new_state == "onboarding_complete":
                _memory_store.sessions[session_id]["status"] = "completed"
        
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
        if session_id not in _memory_store.messages:
            _memory_store.messages[session_id] = []
        
        message_id = str(uuid4())
        message = {
            "id": message_id,
            "role": role,
            "content": content,
            "agent": agent,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        _memory_store.messages[session_id].append(message)
        
        return {"status": "success", "message_id": message_id}
    
    async def get_conversation(
        self,
        session_id: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get conversation history."""
        messages = _memory_store.messages.get(session_id, [])
        return {"status": "success", "messages": messages[-limit:]}
    
    async def log_event(
        self,
        session_id: str,
        event_type: str,
        agent: Optional[str] = None,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Log a telemetry event."""
        if session_id not in _memory_store.telemetry:
            _memory_store.telemetry[session_id] = []
        
        event_id = str(uuid4())
        event = {
            "id": event_id,
            "event_type": event_type,
            "agent": agent,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        _memory_store.telemetry[session_id].append(event)
        
        return {"status": "success", "event_id": event_id}
