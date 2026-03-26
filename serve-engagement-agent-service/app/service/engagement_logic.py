"""
SERVE Engagement Agent Service - Core Logic

State machine for returning volunteer re-engagement.
Same architectural pattern as need_logic.py.

Current stages (boilerplate — expand as needed):
  RE_ENGAGING     → greet returning volunteer, confirm identity
  PROFILE_REFRESH → check if skills/availability changed
  MATCHING_READY  → profile confirmed, ready for matching handoff
  PAUSED          → volunteer paused

TODO (contributor):
  - Implement _handle_re_engaging: fetch volunteer profile from MCP, greet by name
  - Implement _handle_profile_refresh: surface current profile, ask for updates
  - Implement _handle_matching_ready: trigger matching agent handoff
  - Add new stages as the engagement flow is designed
"""
import logging
from typing import Any, Dict, Optional

from app.schemas.engagement_schemas import (
    EngagementWorkflowState,
    EngagementAgentTurnRequest,
    EngagementAgentTurnResponse,
)
from app.clients.domain_client import domain_client
from app.service.llm_adapter import llm_adapter

logger = logging.getLogger(__name__)


class EngagementAgentService:
    """
    Engagement agent state machine.
    Each stage handler receives the request and returns a response.
    """

    async def process_turn(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        stage = request.session_state.stage

        dispatch = {
            EngagementWorkflowState.RE_ENGAGING.value:     self._handle_re_engaging,
            EngagementWorkflowState.PROFILE_REFRESH.value: self._handle_profile_refresh,
            EngagementWorkflowState.MATCHING_READY.value:  self._handle_matching_ready,
            EngagementWorkflowState.PAUSED.value:          self._handle_paused,
        }

        handler = dispatch.get(stage, self._handle_fallback)
        return await handler(request)

    # ── Stage handlers ────────────────────────────────────────────────────────

    async def _handle_re_engaging(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        """
        Welcome the volunteer back and confirm their identity.

        TODO (contributor):
          1. Call domain_client.get_volunteer_profile(session_id) to fetch profile
          2. Surface their last activity (school, subject, grade) in the greeting
          3. Detect if they want to continue or update their profile
          4. Transition to PROFILE_REFRESH or MATCHING_READY accordingly
        """
        volunteer_ctx = {
            "volunteer_name": request.session_state.volunteer_name,
            "last_active_at": request.session_state.last_active_at,
        }
        msg = await llm_adapter.generate_response(
            stage="re_engaging",
            messages=request.conversation_history,
            user_message=request.user_message,
            volunteer_context=volunteer_ctx,
        )
        return self._build_response(
            message=msg,
            next_state=EngagementWorkflowState.RE_ENGAGING.value,
            request=request,
        )

    async def _handle_profile_refresh(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        """
        Check if the volunteer's profile needs updating.

        TODO (contributor):
          1. Fetch current profile from domain_client.get_volunteer_profile()
          2. Show current skills/availability and ask for confirmation or changes
          3. Save any updates via domain_client.save_volunteer_fields()
          4. Transition to MATCHING_READY when profile is confirmed
        """
        msg = await llm_adapter.generate_response(
            stage="profile_refresh",
            messages=request.conversation_history,
            user_message=request.user_message,
        )
        return self._build_response(
            message=msg,
            next_state=EngagementWorkflowState.PROFILE_REFRESH.value,
            request=request,
        )

    async def _handle_matching_ready(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        """
        Profile is confirmed — ready for matching agent handoff.

        TODO (contributor):
          1. Emit handoff event via domain_client.log_event()
          2. Trigger matching agent (when available)
        """
        msg = await llm_adapter.generate_response(
            stage="matching_ready",
            messages=request.conversation_history,
            user_message=request.user_message,
        )
        return self._build_response(
            message=msg,
            next_state=EngagementWorkflowState.MATCHING_READY.value,
            request=request,
            completion_status="matching_ready",
        )

    async def _handle_paused(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        """Volunteer paused the session."""
        msg = await llm_adapter.generate_response(
            stage="paused",
            messages=request.conversation_history,
            user_message=request.user_message,
        )
        return self._build_response(
            message=msg,
            next_state=EngagementWorkflowState.PAUSED.value,
            request=request,
        )

    async def _handle_fallback(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        """Fallback for unknown stages."""
        logger.warning(f"Unknown stage: {request.session_state.stage} — falling back to re_engaging")
        return await self._handle_re_engaging(request)

    # ── Helper ────────────────────────────────────────────────────────────────

    def _build_response(
        self,
        message: str,
        next_state: str,
        request: EngagementAgentTurnRequest,
        completion_status: Optional[str] = None,
        confirmed_fields: Optional[Dict[str, Any]] = None,
    ) -> EngagementAgentTurnResponse:
        return EngagementAgentTurnResponse(
            assistant_message=message,
            state=next_state,
            completion_status=completion_status,
            confirmed_fields=confirmed_fields or {},
        )


# Singleton
engagement_agent_service = EngagementAgentService()
