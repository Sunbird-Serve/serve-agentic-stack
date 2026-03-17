"""
SERVE MCP Server - Need Service
Business logic for need lifecycle management.
"""
import logging
from typing import Dict, Any, Optional, List
from uuid import uuid4
from datetime import datetime, date

logger = logging.getLogger(__name__)

# Mandatory fields for a complete need
MANDATORY_NEED_FIELDS = [
    "subjects",
    "grade_levels",
    "student_count",
    "time_slots",
    "start_date",
    "duration_weeks"
]


class NeedService:
    """Service for need lifecycle operations."""
    
    def __init__(self):
        # In-memory store for preview environment
        self._need_drafts: Dict[str, Dict] = {}  # session_id -> draft
        self._needs: Dict[str, Dict] = {}  # need_id -> need
        self._need_sessions: Dict[str, Dict] = {}  # session_id -> session_state
        self._need_messages: Dict[str, List] = {}  # session_id -> messages
        self._need_events: Dict[str, List] = {}  # session_id -> events
    
    # ============ Session Operations ============
    
    async def start_session(
        self,
        channel: str,
        whatsapp_number: Optional[str] = None,
        channel_metadata: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Start a new need session."""
        session_id = str(uuid4())
        now = datetime.utcnow().isoformat()
        
        session = {
            "id": session_id,
            "channel": channel,
            "workflow": "need_lifecycle",
            "active_agent": "need",
            "status": "active",
            "stage": "initiated",
            "sub_state": None,
            "coordinator_resolution": None,
            "school_resolution": None,
            "coordinator_id": None,
            "school_id": None,
            "need_draft_id": None,
            "whatsapp_number": whatsapp_number,
            "channel_metadata": channel_metadata or {},
            "created_at": now,
            "updated_at": now
        }
        
        self._need_sessions[session_id] = session
        self._need_messages[session_id] = []
        self._need_events[session_id] = []
        
        logger.info(f"Started need session: {session_id}")
        return {
            "session_id": session_id,
            "stage": "initiated",
            "status": "active"
        }
    
    async def resume_context(self, session_id: str) -> Dict[str, Any]:
        """Resume an existing need session with full context."""
        session = self._need_sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        
        # Get associated data
        draft = self._need_drafts.get(session_id)
        messages = self._need_messages.get(session_id, [])[-10:]
        
        # Get coordinator and school if linked
        coordinator = None
        school = None
        
        if session.get("coordinator_id"):
            from services.coordinator_service import coordinator_service
            coordinator = await coordinator_service.get_coordinator(session["coordinator_id"])
        
        if session.get("school_id"):
            from services.school_service import school_service
            school = await school_service.get_school(session["school_id"])
        
        return {
            "session": session,
            "need_draft": draft,
            "coordinator": coordinator,
            "school": school,
            "conversation_history": messages
        }
    
    async def advance_state(
        self,
        session_id: str,
        new_state: str,
        sub_state: Optional[str] = None
    ) -> Dict[str, Any]:
        """Advance need session state."""
        session = self._need_sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        
        old_state = session["stage"]
        session["stage"] = new_state
        session["sub_state"] = sub_state
        session["updated_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Need session {session_id}: {old_state} -> {new_state}")
        return {
            "session_id": session_id,
            "previous_state": old_state,
            "current_state": new_state
        }
    
    async def pause_session(
        self,
        session_id: str,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Pause a need session."""
        session = self._need_sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        
        session["status"] = "paused"
        session["stage"] = "paused"
        session["pause_reason"] = reason
        session["updated_at"] = datetime.utcnow().isoformat()
        
        return {"status": "paused", "session_id": session_id}
    
    # ============ Need Draft Operations ============
    
    async def save_need_draft(
        self,
        session_id: str,
        need_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create or update a need draft."""
        existing = self._need_drafts.get(session_id, {})
        
        # Merge with existing data
        merged = {**existing, **need_data}
        merged["session_id"] = session_id
        merged["updated_at"] = datetime.utcnow().isoformat()
        
        if "id" not in merged:
            merged["id"] = str(uuid4())
            merged["created_at"] = merged["updated_at"]
            merged["status"] = "draft"
        
        self._need_drafts[session_id] = merged
        
        # Link to session
        if session_id in self._need_sessions:
            self._need_sessions[session_id]["need_draft_id"] = merged["id"]
        
        logger.info(f"Saved need draft for session {session_id}")
        return {
            "need_id": merged["id"],
            "draft": merged
        }
    
    async def get_missing_fields(self, session_id: str) -> Dict[str, Any]:
        """Get missing mandatory fields for a need draft."""
        draft = self._need_drafts.get(session_id, {})
        
        missing = []
        confirmed = {}
        
        for field in MANDATORY_NEED_FIELDS:
            value = draft.get(field)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
            else:
                confirmed[field] = value
        
        total = len(MANDATORY_NEED_FIELDS)
        filled = total - len(missing)
        completion_pct = round((filled / total) * 100) if total > 0 else 0
        
        return {
            "missing_fields": missing,
            "confirmed_fields": confirmed,
            "completion_percentage": completion_pct
        }
    
    async def evaluate_readiness(self, session_id: str) -> Dict[str, Any]:
        """Evaluate if need is ready for submission."""
        missing_result = await self.get_missing_fields(session_id)
        missing = missing_result["missing_fields"]
        
        is_ready = len(missing) == 0
        
        warnings = []
        draft = self._need_drafts.get(session_id, {})
        
        # Add warnings for edge cases
        if draft.get("student_count", 0) > 100:
            warnings.append("Large student count - may need multiple volunteers")
        
        if draft.get("duration_weeks", 0) > 24:
            warnings.append("Long duration - consider breaking into phases")
        
        recommendation = "submit" if is_ready else "continue_drafting"
        
        return {
            "is_ready": is_ready,
            "missing_mandatory_fields": missing,
            "warnings": warnings,
            "completion_percentage": missing_result["completion_percentage"],
            "recommendation": recommendation
        }
    
    # ============ Status Operations ============
    
    async def update_status(
        self,
        need_id: str,
        status: str,
        comments: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update need status."""
        # Find need in drafts or needs
        for session_id, draft in self._need_drafts.items():
            if draft.get("id") == need_id:
                draft["status"] = status
                if comments:
                    draft["admin_comments"] = comments
                draft["updated_at"] = datetime.utcnow().isoformat()
                return {"success": True, "need_id": need_id, "status": status}
        
        return {"success": False, "error": "Need not found"}
    
    async def submit_for_approval(self, need_id: str) -> Dict[str, Any]:
        """Submit need for approval (placeholder for future approval workflow)."""
        for session_id, draft in self._need_drafts.items():
            if draft.get("id") == need_id:
                # For now, auto-approve since approval workflow is future work
                draft["status"] = "approved"
                draft["submitted_at"] = datetime.utcnow().isoformat()
                draft["approved_at"] = datetime.utcnow().isoformat()
                
                return {
                    "submission_id": str(uuid4()),
                    "need_id": need_id,
                    "status": "approved",
                    "message": "Need has been recorded (approval workflow pending implementation)"
                }
        
        return {"status": "error", "error": "Need not found"}
    
    # ============ Handoff Operations ============
    
    async def prepare_fulfillment_handoff(self, need_id: str) -> Dict[str, Any]:
        """Prepare handoff payload for fulfillment agent."""
        # Find the need
        need_draft = None
        session_id = None
        
        for sid, draft in self._need_drafts.items():
            if draft.get("id") == need_id:
                need_draft = draft
                session_id = sid
                break
        
        if not need_draft:
            return {"status": "error", "error": "Need not found"}
        
        session = self._need_sessions.get(session_id, {})
        
        # Get coordinator and school
        coordinator = None
        school = None
        
        if session.get("coordinator_id"):
            from services.coordinator_service import coordinator_service
            coordinator = await coordinator_service.get_coordinator(session["coordinator_id"])
        
        if session.get("school_id"):
            from services.school_service import school_service
            school = await school_service.get_school(session["school_id"])
            # Add this need to school's history
            await school_service.add_need_reference(session["school_id"], need_id)
        
        return {
            "need_id": need_id,
            "need_details": need_draft,
            "school": school,
            "coordinator": coordinator,
            "approval_status": need_draft.get("status", "draft"),
            "priority": "normal",
            "created_at": need_draft.get("created_at"),
            "ready_for_fulfillment": need_draft.get("status") == "approved"
        }
    
    # ============ Message & Event Operations ============
    
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """Save a conversation message."""
        if session_id not in self._need_messages:
            self._need_messages[session_id] = []
        
        message = {
            "id": str(uuid4()),
            "role": role,
            "content": content,
            "agent": agent,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self._need_messages[session_id].append(message)
        return {"message_id": message["id"]}
    
    async def log_event(
        self,
        session_id: str,
        event_type: str,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Log a need lifecycle event."""
        if session_id not in self._need_events:
            self._need_events[session_id] = []
        
        event = {
            "id": str(uuid4()),
            "event_type": event_type,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self._need_events[session_id].append(event)
        return {"event_id": event["id"]}
    
    async def emit_handoff_event(
        self,
        session_id: str,
        from_agent: str,
        to_agent: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Emit a handoff event."""
        event = {
            "id": str(uuid4()),
            "type": "handoff",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if session_id not in self._need_events:
            self._need_events[session_id] = []
        
        self._need_events[session_id].append(event)
        
        logger.info(f"Handoff event: {from_agent} -> {to_agent} for session {session_id}")
        return {"handoff_id": event["id"]}
    
    # ============ Session State Updates ============
    
    async def set_coordinator(self, session_id: str, coordinator_id: str) -> None:
        """Set coordinator for session."""
        if session_id in self._need_sessions:
            self._need_sessions[session_id]["coordinator_id"] = coordinator_id
            self._need_sessions[session_id]["coordinator_resolution"] = "verified"
    
    async def set_school(self, session_id: str, school_id: str, resolution: str) -> None:
        """Set school for session."""
        if session_id in self._need_sessions:
            self._need_sessions[session_id]["school_id"] = school_id
            self._need_sessions[session_id]["school_resolution"] = resolution


# Singleton instance
need_service = NeedService()
