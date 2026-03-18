"""
SERVE MCP Server - Session Service
Handles session lifecycle operations (create, resume, advance state, messages, events)

All operations attempt PostgreSQL first, falling back to in-memory storage.
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
        persona: str = "new_volunteer",
        channel_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new session with persona-aware workflow and stage.

        channel_metadata is persisted to the sessions.channel_metadata JSON column
        so downstream services can access actor_id, trigger_type, and any other
        channel-specific context associated with this session.
        """
        session_id = str(uuid4())
        now = datetime.utcnow()
        meta = channel_metadata or {}

        # Derive workflow, agent, and initial stage from persona
        if persona == "need_coordinator":
            workflow = "need_coordination"
            active_agent = "need"
            stage = "initiated"
        else:
            workflow = "new_volunteer_onboarding"
            active_agent = "onboarding"
            stage = "init"

        # Try Postgres first
        if await self._check_postgres():
            try:
                from .database import get_db, Session, VolunteerProfile
                async with get_db() as db:
                    session = Session(
                        id=UUID(session_id),
                        channel=channel,
                        persona=persona,
                        workflow=workflow,
                        active_agent=active_agent,
                        status="active",
                        stage=stage,
                        channel_metadata=meta if meta else None,
                        created_at=now,
                        updated_at=now
                    )
                    db.add(session)

                    if persona != "need_coordinator":
                        profile = VolunteerProfile(
                            session_id=UUID(session_id),
                            skills=[],
                            interests=[],
                            preferred_causes=[],
                            created_at=now,
                            updated_at=now
                        )
                        db.add(profile)

                    await db.flush()

                logger.info(
                    f"Session created in Postgres: {session_id} "
                    f"(persona={persona}, actor_id={meta.get('actor_id', 'unknown')})"
                )
                return {
                    "status": "success",
                    "session_id": session_id,
                    "stage": stage,
                    "workflow": workflow,
                    "storage": "postgres"
                }
            except Exception as e:
                logger.warning(f"Postgres create failed, using memory: {e}")

        # Fallback to in-memory
        session = {
            "id": session_id,
            "channel": channel,
            "persona": persona,
            "workflow": workflow,
            "active_agent": active_agent,
            "status": "active",
            "stage": stage,
            "sub_state": None,
            "context_summary": None,
            "channel_metadata": meta,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        _memory_store.sessions[session_id] = session
        _memory_store.messages[session_id] = []
        _memory_store.telemetry[session_id] = []

        logger.info(
            f"Session created in memory: {session_id} "
            f"(actor_id={meta.get('actor_id', 'unknown')})"
        )
        return {
            "status": "success",
            "session_id": session_id,
            "stage": stage,
            "workflow": workflow,
            "storage": "memory"
        }

    async def get_session(self, session_id: str) -> Dict[str, Any]:
        """Get session state."""
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
                logger.warning(f"Postgres get_session failed: {e}")

        # Fallback to memory
        session = _memory_store.sessions.get(session_id)
        if not session:
            return {"status": "error", "error": "Session not found"}
        return {"status": "success", "session": session}

    async def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """List sessions, optionally filtered by status."""
        if await self._check_postgres():
            try:
                from .database import get_db, Session
                from sqlalchemy import select
                async with get_db() as db:
                    query = select(Session).order_by(Session.created_at.desc()).limit(limit)
                    if status:
                        query = query.where(Session.status == status)
                    result = await db.execute(query)
                    sessions = result.scalars().all()
                    return {
                        "status": "success",
                        "sessions": [
                            {
                                "id": str(s.id),
                                "channel": s.channel,
                                "persona": s.persona,
                                "workflow": s.workflow,
                                "active_agent": s.active_agent,
                                "status": s.status,
                                "stage": s.stage,
                                "created_at": s.created_at.isoformat() if s.created_at else None,
                            }
                            for s in sessions
                        ]
                    }
            except Exception as e:
                logger.warning(f"Postgres list_sessions failed: {e}")

        # Fallback to memory
        sessions = list(_memory_store.sessions.values())
        if status:
            sessions = [s for s in sessions if s.get("status") == status]
        return {"status": "success", "sessions": sessions[:limit]}

    async def resume_context(self, session_id: str) -> Dict[str, Any]:
        """Resume session with full context (session, profile, recent messages)."""
        session_result = await self.get_session(session_id)
        if session_result.get("status") != "success":
            return session_result

        session = session_result.get("session", {})

        # Get volunteer profile
        from .profile_service import ProfileService
        profile_service = ProfileService()
        profile_result = await profile_service.get_profile(session_id)

        # Get recent messages from PostgreSQL or memory
        messages = await self._get_recent_messages(session_id, limit=10)

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
        sub_state: Optional[str] = None,
        active_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Advance session to a new state, persisting to PostgreSQL if available.

        active_agent — when provided, the session's active_agent column is also
        updated.  This is critical after an agent handoff so the next turn routes
        to the correct agent rather than the one that just finished.
        """
        if await self._check_postgres():
            try:
                from .database import get_db, Session
                from sqlalchemy import select, update
                async with get_db() as db:
                    result = await db.execute(
                        select(Session).where(Session.id == UUID(session_id))
                    )
                    session_obj = result.scalar_one_or_none()
                    if session_obj:
                        old_state = session_obj.stage
                        new_status = session_obj.status
                        if new_state in ("onboarding_complete", "need_submitted", "fulfillment_handoff_ready", "approved"):
                            new_status = "completed"

                        update_values: Dict[str, Any] = {
                            "stage": new_state,
                            "sub_state": sub_state,
                            "status": new_status,
                            "updated_at": datetime.utcnow(),
                        }
                        if active_agent is not None:
                            update_values["active_agent"] = active_agent

                        await db.execute(
                            update(Session)
                            .where(Session.id == UUID(session_id))
                            .values(**update_values)
                        )
                        logger.info(
                            f"State advanced in Postgres: {session_id} "
                            f"{old_state} -> {new_state}"
                            + (f" (agent -> {active_agent})" if active_agent else "")
                        )
                        return {
                            "status": "success",
                            "previous_state": old_state,
                            "current_state": new_state,
                            "active_agent": active_agent or session_obj.active_agent,
                            "is_valid": True,
                        }
            except Exception as e:
                logger.warning(f"Postgres advance_state failed, using memory: {e}")

        # Fallback to in-memory
        if session_id in _memory_store.sessions:
            old_state = _memory_store.sessions[session_id].get("stage", "init")
            _memory_store.sessions[session_id]["stage"] = new_state
            _memory_store.sessions[session_id]["sub_state"] = sub_state
            _memory_store.sessions[session_id]["updated_at"] = datetime.utcnow().isoformat()
            if new_state in ("onboarding_complete", "need_submitted", "fulfillment_handoff_ready", "approved"):
                _memory_store.sessions[session_id]["status"] = "completed"
            if active_agent is not None:
                _memory_store.sessions[session_id]["active_agent"] = active_agent
            return {
                "status": "success",
                "previous_state": old_state,
                "current_state": new_state,
                "active_agent": active_agent,
                "is_valid": True,
            }

        return {"status": "error", "error": f"Session {session_id} not found"}

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """Save a conversation message, persisting to PostgreSQL if available."""
        message_id = str(uuid4())

        if await self._check_postgres():
            try:
                from .database import get_db, ConversationMessage
                async with get_db() as db:
                    message = ConversationMessage(
                        id=UUID(message_id),
                        session_id=UUID(session_id),
                        role=role,
                        content=content,
                        agent=agent,
                        created_at=datetime.utcnow()
                    )
                    db.add(message)
                    await db.flush()
                return {"status": "success", "message_id": message_id}
            except Exception as e:
                logger.warning(f"Postgres save_message failed, using memory: {e}")

        # Fallback to in-memory
        if session_id not in _memory_store.messages:
            _memory_store.messages[session_id] = []
        _memory_store.messages[session_id].append({
            "id": message_id,
            "role": role,
            "content": content,
            "agent": agent,
            "timestamp": datetime.utcnow().isoformat()
        })
        return {"status": "success", "message_id": message_id}

    async def get_conversation(
        self,
        session_id: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get conversation history from PostgreSQL or memory."""
        messages = await self._get_recent_messages(session_id, limit=limit)
        return {"status": "success", "messages": messages}

    async def log_event(
        self,
        session_id: str,
        event_type: str,
        agent: Optional[str] = None,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Log a telemetry event, persisting to PostgreSQL if available."""
        event_id = str(uuid4())

        if await self._check_postgres():
            try:
                from .database import get_db, TelemetryEvent
                async with get_db() as db:
                    event = TelemetryEvent(
                        id=UUID(event_id),
                        session_id=UUID(session_id),
                        event_type=event_type,
                        agent=agent,
                        data=data or {},
                        timestamp=datetime.utcnow()
                    )
                    db.add(event)
                    await db.flush()
                return {"status": "success", "event_id": event_id}
            except Exception as e:
                logger.warning(f"Postgres log_event failed, using memory: {e}")

        # Fallback to in-memory
        if session_id not in _memory_store.telemetry:
            _memory_store.telemetry[session_id] = []
        event = {
            "id": event_id,
            "event_type": event_type,
            "agent": agent,
            "data": data or {},
            "timestamp": datetime.utcnow().isoformat()
        }
        _memory_store.telemetry[session_id].append(event)
        return {"status": "success", "event_id": event_id}

    async def emit_handoff_event(
        self,
        session_id: str,
        from_agent: str,
        to_agent: str,
        handoff_type: str,
        payload: Optional[Dict] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record an agent handoff as a telemetry event."""
        event_data = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "handoff_type": handoff_type,
            "payload": payload or {},
        }
        if reason:
            event_data["reason"] = reason

        return await self.log_event(
            session_id=session_id,
            event_type="handoff",
            agent=from_agent,
            data=event_data
        )

    async def _get_recent_messages(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Helper to fetch recent messages from Postgres or memory."""
        if await self._check_postgres():
            try:
                from .database import get_db, ConversationMessage
                from sqlalchemy import select
                async with get_db() as db:
                    result = await db.execute(
                        select(ConversationMessage)
                        .where(ConversationMessage.session_id == UUID(session_id))
                        .order_by(ConversationMessage.created_at.desc())
                        .limit(limit)
                    )
                    msgs = result.scalars().all()
                    return [
                        {
                            "id": str(m.id),
                            "role": m.role,
                            "content": m.content,
                            "agent": m.agent,
                            "timestamp": m.created_at.isoformat() if m.created_at else None
                        }
                        for m in reversed(msgs)
                    ]
            except Exception as e:
                logger.warning(f"Postgres get_messages failed: {e}")

        return _memory_store.messages.get(session_id, [])[-limit:]
