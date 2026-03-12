"""
SERVE Agentic MCP Service - Onboarding Capabilities Service
Business logic for onboarding domain capabilities
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
import logging

from app.models import (
    Session, SessionEvent, VolunteerProfile, ConversationMessage,
    MemorySummary, HandoffEvent, TelemetryEvent
)
from app.schemas import (
    MCPResponse, StartSessionRequest, AdvanceStateRequest,
    SaveConfirmedFieldsRequest, EmitHandoffRequest, LogEventRequest,
    SaveMessageRequest, SessionStatus, OnboardingState, AgentType
)

logger = logging.getLogger(__name__)


class OnboardingCapabilityService:
    """Service implementing onboarding domain capabilities"""

    async def start_session(
        self, 
        db: AsyncSession, 
        request: StartSessionRequest
    ) -> MCPResponse:
        """Start a new onboarding session"""
        try:
            # Create session
            session = Session(
                channel=request.channel.value,
                persona=request.persona.value,
                workflow="new_volunteer_onboarding",
                active_agent="onboarding",
                status="active",
                stage=OnboardingState.INIT.value,
                channel_metadata=request.channel_metadata
            )
            db.add(session)
            await db.flush()

            # Create volunteer profile linked to session
            profile = VolunteerProfile(session_id=session.id)
            db.add(profile)

            # Log session start event
            event = TelemetryEvent(
                session_id=session.id,
                event_type="session_start",
                agent="onboarding",
                data={"channel": request.channel.value, "persona": request.persona.value}
            )
            db.add(event)

            await db.commit()
            await db.refresh(session)

            return MCPResponse(
                status="success",
                data={
                    "session_id": str(session.id),
                    "stage": session.stage,
                    "status": session.status,
                }
            )
        except Exception as e:
            logger.error(f"Error starting session: {e}")
            return MCPResponse(status="error", error=str(e))

    async def resume_context(
        self, 
        db: AsyncSession, 
        session_id: UUID
    ) -> MCPResponse:
        """Resume context for an existing session"""
        try:
            result = await db.execute(
                select(Session)
                .options(selectinload(Session.profile))
                .where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                return MCPResponse(status="error", error="Session not found")

            # Get conversation history
            messages_result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.session_id == session_id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(10)
            )
            messages = messages_result.scalars().all()

            # Get memory summary
            memory_result = await db.execute(
                select(MemorySummary)
                .where(MemorySummary.session_id == session_id)
                .order_by(MemorySummary.created_at.desc())
                .limit(1)
            )
            memory = memory_result.scalar_one_or_none()

            return MCPResponse(
                status="success",
                data={
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
                        "created_at": session.created_at.isoformat(),
                        "updated_at": session.updated_at.isoformat(),
                    },
                    "volunteer_profile": {
                        "id": str(session.profile.id) if session.profile else None,
                        "full_name": session.profile.full_name if session.profile else None,
                        "email": session.profile.email if session.profile else None,
                        "phone": session.profile.phone if session.profile else None,
                        "location": session.profile.location if session.profile else None,
                        "skills": session.profile.skills if session.profile else [],
                        "interests": session.profile.interests if session.profile else [],
                        "availability": session.profile.availability if session.profile else None,
                    } if session.profile else None,
                    "conversation_history": [
                        {"role": m.role, "content": m.content} for m in reversed(list(messages))
                    ],
                    "memory_summary": memory.summary_text if memory else None,
                }
            )
        except Exception as e:
            logger.error(f"Error resuming context: {e}")
            return MCPResponse(status="error", error=str(e))

    async def advance_state(
        self, 
        db: AsyncSession, 
        request: AdvanceStateRequest
    ) -> MCPResponse:
        """Advance session to a new state"""
        try:
            result = await db.execute(
                select(Session).where(Session.id == request.session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                return MCPResponse(status="error", error="Session not found")

            old_state = session.stage

            # Create state transition event
            event = SessionEvent(
                session_id=session.id,
                event_type="state_transition",
                from_state=old_state,
                to_state=request.new_state,
                agent=session.active_agent
            )
            db.add(event)

            # Update session
            session.stage = request.new_state
            session.sub_state = request.sub_state
            session.updated_at = datetime.utcnow()

            # Check for completion
            if request.new_state == OnboardingState.ONBOARDING_COMPLETE.value:
                session.status = "completed"

            await db.commit()

            return MCPResponse(
                status="success",
                data={
                    "session_id": str(session.id),
                    "previous_state": old_state,
                    "current_state": request.new_state,
                    "sub_state": request.sub_state,
                }
            )
        except Exception as e:
            logger.error(f"Error advancing state: {e}")
            return MCPResponse(status="error", error=str(e))

    async def get_missing_fields(
        self, 
        db: AsyncSession, 
        session_id: UUID
    ) -> MCPResponse:
        """Get list of missing required fields for the volunteer profile"""
        try:
            result = await db.execute(
                select(VolunteerProfile).where(VolunteerProfile.session_id == session_id)
            )
            profile = result.scalar_one_or_none()

            required_fields = ["full_name", "email", "location", "skills", "availability"]
            missing = []
            confirmed = {}

            if profile:
                for field in required_fields:
                    value = getattr(profile, field, None)
                    if not value or (isinstance(value, list) and len(value) == 0):
                        missing.append(field)
                    else:
                        confirmed[field] = value
            else:
                missing = required_fields

            return MCPResponse(
                status="success",
                data={
                    "missing_fields": missing,
                    "confirmed_fields": confirmed,
                    "completion_percentage": round((len(confirmed) / len(required_fields)) * 100)
                }
            )
        except Exception as e:
            logger.error(f"Error getting missing fields: {e}")
            return MCPResponse(status="error", error=str(e))

    async def save_confirmed_fields(
        self, 
        db: AsyncSession, 
        request: SaveConfirmedFieldsRequest
    ) -> MCPResponse:
        """Save confirmed profile fields"""
        try:
            result = await db.execute(
                select(VolunteerProfile).where(VolunteerProfile.session_id == request.session_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                return MCPResponse(status="error", error="Profile not found")

            # Update profile fields
            for field, value in request.fields.items():
                if hasattr(profile, field):
                    setattr(profile, field, value)

            profile.updated_at = datetime.utcnow()
            await db.commit()

            return MCPResponse(
                status="success",
                data={
                    "saved_fields": list(request.fields.keys()),
                }
            )
        except Exception as e:
            logger.error(f"Error saving fields: {e}")
            return MCPResponse(status="error", error=str(e))

    async def pause_session(
        self, 
        db: AsyncSession, 
        session_id: UUID,
        reason: Optional[str] = None
    ) -> MCPResponse:
        """Pause an active session"""
        try:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                return MCPResponse(status="error", error="Session not found")

            old_stage = session.stage
            session.status = "paused"
            session.stage = OnboardingState.PAUSED.value
            session.updated_at = datetime.utcnow()

            # Log pause event
            event = SessionEvent(
                session_id=session.id,
                event_type="session_paused",
                from_state=old_stage,
                to_state=OnboardingState.PAUSED.value,
                data={"reason": reason}
            )
            db.add(event)

            await db.commit()

            return MCPResponse(
                status="success",
                data={
                    "session_id": str(session.id),
                    "status": "paused",
                    "reason": reason
                }
            )
        except Exception as e:
            logger.error(f"Error pausing session: {e}")
            return MCPResponse(status="error", error=str(e))

    async def emit_handoff_event(
        self, 
        db: AsyncSession, 
        request: EmitHandoffRequest
    ) -> MCPResponse:
        """Record a handoff event"""
        try:
            handoff = HandoffEvent(
                session_id=request.session_id,
                from_agent=request.from_agent.value,
                to_agent=request.to_agent.value,
                handoff_type=request.handoff_type.value,
                payload=request.payload,
                reason=request.reason
            )
            db.add(handoff)

            # Update session's active agent
            await db.execute(
                update(Session)
                .where(Session.id == request.session_id)
                .values(active_agent=request.to_agent.value, updated_at=datetime.utcnow())
            )

            await db.commit()

            return MCPResponse(
                status="success",
                data={
                    "handoff_id": str(handoff.id),
                    "from_agent": request.from_agent.value,
                    "to_agent": request.to_agent.value,
                }
            )
        except Exception as e:
            logger.error(f"Error emitting handoff: {e}")
            return MCPResponse(status="error", error=str(e))

    async def log_event(
        self, 
        db: AsyncSession, 
        request: LogEventRequest
    ) -> MCPResponse:
        """Log a telemetry event"""
        try:
            event = TelemetryEvent(
                session_id=request.session_id,
                event_type=request.event_type.value,
                agent=request.agent.value if request.agent else None,
                data=request.data
            )
            db.add(event)
            await db.commit()

            return MCPResponse(
                status="success",
                data={
                    "event_id": str(event.id),
                    "event_type": request.event_type.value,
                }
            )
        except Exception as e:
            logger.error(f"Error logging event: {e}")
            return MCPResponse(status="error", error=str(e))

    async def save_message(
        self, 
        db: AsyncSession, 
        request: SaveMessageRequest
    ) -> MCPResponse:
        """Save a conversation message"""
        try:
            message = ConversationMessage(
                session_id=request.session_id,
                role=request.role,
                content=request.content,
                agent=request.agent.value if request.agent else None
            )
            db.add(message)
            await db.commit()

            return MCPResponse(
                status="success",
                data={
                    "message_id": str(message.id),
                }
            )
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return MCPResponse(status="error", error=str(e))

    async def get_conversation(
        self, 
        db: AsyncSession, 
        session_id: UUID,
        limit: int = 50
    ) -> MCPResponse:
        """Get conversation history for a session"""
        try:
            result = await db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.session_id == session_id)
                .order_by(ConversationMessage.created_at)
                .limit(limit)
            )
            messages = result.scalars().all()

            return MCPResponse(
                status="success",
                data={
                    "messages": [
                        {
                            "id": str(m.id),
                            "role": m.role,
                            "content": m.content,
                            "agent": m.agent,
                            "timestamp": m.created_at.isoformat(),
                        }
                        for m in messages
                    ]
                }
            )
        except Exception as e:
            logger.error(f"Error getting conversation: {e}")
            return MCPResponse(status="error", error=str(e))

    async def get_session(
        self, 
        db: AsyncSession, 
        session_id: UUID
    ) -> MCPResponse:
        """Get full session state"""
        try:
            result = await db.execute(
                select(Session)
                .options(selectinload(Session.profile))
                .where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                return MCPResponse(status="error", error="Session not found")

            return MCPResponse(
                status="success",
                data={
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
                        "created_at": session.created_at.isoformat(),
                        "updated_at": session.updated_at.isoformat(),
                    },
                    "volunteer_profile": {
                        "id": str(session.profile.id) if session.profile else None,
                        "full_name": session.profile.full_name if session.profile else None,
                        "email": session.profile.email if session.profile else None,
                        "phone": session.profile.phone if session.profile else None,
                        "location": session.profile.location if session.profile else None,
                        "skills": session.profile.skills if session.profile else [],
                        "interests": session.profile.interests if session.profile else [],
                        "availability": session.profile.availability if session.profile else None,
                        "onboarding_completed": session.profile.onboarding_completed if session.profile else False,
                    } if session.profile else None
                }
            )
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return MCPResponse(status="error", error=str(e))

    async def list_sessions(
        self, 
        db: AsyncSession, 
        status: Optional[str] = None,
        limit: int = 50
    ) -> MCPResponse:
        """List all sessions with optional status filter"""
        try:
            query = select(Session).options(selectinload(Session.profile))

            if status:
                query = query.where(Session.status == status)

            query = query.order_by(Session.created_at.desc()).limit(limit)

            result = await db.execute(query)
            sessions = result.scalars().all()

            return MCPResponse(
                status="success",
                data={
                    "sessions": [
                        {
                            "id": str(s.id),
                            "status": s.status,
                            "stage": s.stage,
                            "active_agent": s.active_agent,
                            "volunteer_name": s.profile.full_name if s.profile else None,
                            "created_at": s.created_at.isoformat(),
                            "updated_at": s.updated_at.isoformat(),
                        }
                        for s in sessions
                    ]
                }
            )
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return MCPResponse(status="error", error=str(e))

    async def get_telemetry(
        self, 
        db: AsyncSession, 
        session_id: UUID,
        limit: int = 100
    ) -> MCPResponse:
        """Get telemetry events for a session"""
        try:
            result = await db.execute(
                select(TelemetryEvent)
                .where(TelemetryEvent.session_id == session_id)
                .order_by(TelemetryEvent.created_at.desc())
                .limit(limit)
            )
            events = result.scalars().all()

            return MCPResponse(
                status="success",
                data={
                    "events": [
                        {
                            "id": str(e.id),
                            "event_type": e.event_type,
                            "agent": e.agent,
                            "data": e.data,
                            "timestamp": e.created_at.isoformat(),
                        }
                        for e in events
                    ]
                }
            )
        except Exception as e:
            logger.error(f"Error getting telemetry: {e}")
            return MCPResponse(status="error", error=str(e))

    async def evaluate_prerequisites(
        self, 
        db: AsyncSession, 
        session_id: UUID
    ) -> MCPResponse:
        """Evaluate if prerequisites for onboarding are met"""
        try:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                return MCPResponse(status="error", error="Session not found")

            prerequisites_met = session.status == "active"
            issues = []
            if not prerequisites_met:
                issues.append("Session is not active")

            return MCPResponse(
                status="success",
                data={
                    "prerequisites_met": prerequisites_met,
                    "issues": issues,
                }
            )
        except Exception as e:
            logger.error(f"Error evaluating prerequisites: {e}")
            return MCPResponse(status="error", error=str(e))

    async def evaluate_readiness(
        self, 
        db: AsyncSession, 
        session_id: UUID
    ) -> MCPResponse:
        """Evaluate if volunteer is ready to proceed to selection"""
        try:
            result = await db.execute(
                select(VolunteerProfile).where(VolunteerProfile.session_id == session_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                return MCPResponse(status="error", error="Profile not found")

            required_fields = ["full_name", "email", "skills", "availability"]
            missing = []

            for field in required_fields:
                value = getattr(profile, field, None)
                if not value or (isinstance(value, list) and len(value) == 0):
                    missing.append(field)

            ready = len(missing) == 0

            return MCPResponse(
                status="success",
                data={
                    "ready_for_selection": ready,
                    "missing_fields": missing,
                    "recommendation": "proceed" if ready else "gather_more_info"
                }
            )
        except Exception as e:
            logger.error(f"Error evaluating readiness: {e}")
            return MCPResponse(status="error", error=str(e))

    async def prepare_selection_handoff(
        self, 
        db: AsyncSession, 
        session_id: UUID,
        target_agent: str
    ) -> MCPResponse:
        """Prepare handoff payload for selection agent"""
        try:
            result = await db.execute(
                select(Session)
                .options(selectinload(Session.profile))
                .where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()

            if not session:
                return MCPResponse(status="error", error="Session not found")

            profile = session.profile

            handoff_payload = {
                "session_id": str(session.id),
                "volunteer_profile": {
                    "full_name": profile.full_name if profile else None,
                    "email": profile.email if profile else None,
                    "skills": profile.skills if profile else [],
                    "interests": profile.interests if profile else [],
                    "availability": profile.availability if profile else None,
                    "experience_level": profile.experience_level if profile else None,
                },
                "onboarding_summary": session.context_summary,
                "workflow": session.workflow,
            }

            return MCPResponse(
                status="success",
                data={
                    "handoff_payload": handoff_payload,
                    "target_agent": target_agent,
                }
            )
        except Exception as e:
            logger.error(f"Error preparing handoff: {e}")
            return MCPResponse(status="error", error=str(e))

    # ============ Memory Summary Capabilities ============
    
    async def save_memory_summary(
        self,
        session_id: UUID,
        summary_text: str,
        key_facts: List[str] = None,
        volunteer_id: UUID = None,
        db: AsyncSession = None
    ) -> MCPResponse:
        """
        Save a conversation memory summary.
        
        This capability stores summarized conversation context for
        long-term memory, enabling personalized interactions when
        volunteers return.
        """
        try:
            from app.models import MemorySummary
            
            async with get_db() as db:
                # Check if summary exists for this session
                result = await db.execute(
                    select(MemorySummary).where(MemorySummary.session_id == session_id)
                )
                existing = result.scalar_one_or_none()
                
                if existing:
                    # Update existing summary
                    existing.summary_text = summary_text
                    existing.key_facts = key_facts or []
                    existing.created_at = datetime.utcnow()
                    await db.flush()
                    summary_id = existing.id
                else:
                    # Create new summary
                    summary = MemorySummary(
                        session_id=session_id,
                        volunteer_id=volunteer_id,
                        summary_text=summary_text,
                        key_facts=key_facts or [],
                        created_at=datetime.utcnow()
                    )
                    db.add(summary)
                    await db.flush()
                    summary_id = summary.id
                
                await db.commit()
            
            logger.info(f"Saved memory summary for session {session_id}")
            return MCPResponse(
                status="success",
                data={
                    "summary_id": str(summary_id),
                    "session_id": str(session_id),
                    "key_facts_count": len(key_facts) if key_facts else 0
                }
            )
        except Exception as e:
            logger.error(f"Error saving memory summary: {e}")
            return MCPResponse(status="error", error=str(e))
    
    async def get_memory_summary(
        self,
        session_id: UUID,
        db: AsyncSession = None
    ) -> MCPResponse:
        """
        Retrieve memory summary for a session.
        
        Returns the most recent summary and key facts for context.
        """
        try:
            from app.models import MemorySummary
            
            async with get_db() as db:
                result = await db.execute(
                    select(MemorySummary)
                    .where(MemorySummary.session_id == session_id)
                    .order_by(MemorySummary.created_at.desc())
                )
                summary = result.scalar_one_or_none()
                
                if not summary:
                    return MCPResponse(
                        status="success",
                        data=None
                    )
                
                return MCPResponse(
                    status="success",
                    data={
                        "summary_id": str(summary.id),
                        "session_id": str(session_id),
                        "summary_text": summary.summary_text,
                        "key_facts": summary.key_facts or [],
                        "created_at": summary.created_at.isoformat() if summary.created_at else None
                    }
                )
        except Exception as e:
            logger.error(f"Error getting memory summary: {e}")
            return MCPResponse(status="error", error=str(e))
    
    async def get_volunteer_memory(
        self,
        volunteer_id: UUID,
        db: AsyncSession = None
    ) -> MCPResponse:
        """
        Retrieve all memory summaries for a volunteer across sessions.
        
        Useful for returning volunteers who may have had multiple
        conversation sessions.
        """
        try:
            from app.models import MemorySummary
            
            async with get_db() as db:
                result = await db.execute(
                    select(MemorySummary)
                    .where(MemorySummary.volunteer_id == volunteer_id)
                    .order_by(MemorySummary.created_at.desc())
                    .limit(5)
                )
                summaries = result.scalars().all()
                
                if not summaries:
                    return MCPResponse(status="success", data={"summaries": []})
                
                summaries_data = [
                    {
                        "summary_id": str(s.id),
                        "session_id": str(s.session_id) if s.session_id else None,
                        "summary_text": s.summary_text,
                        "key_facts": s.key_facts or [],
                        "created_at": s.created_at.isoformat() if s.created_at else None
                    }
                    for s in summaries
                ]
                
                # Combine key facts from all summaries
                all_facts = []
                for s in summaries_data:
                    all_facts.extend(s.get("key_facts", []))
                unique_facts = list(dict.fromkeys(all_facts))[:10]
                
                return MCPResponse(
                    status="success",
                    data={
                        "summaries": summaries_data,
                        "combined_key_facts": unique_facts
                    }
                )
        except Exception as e:
            logger.error(f"Error getting volunteer memory: {e}")
            return MCPResponse(status="error", error=str(e))



# Singleton instance
onboarding_capability_service = OnboardingCapabilityService()
