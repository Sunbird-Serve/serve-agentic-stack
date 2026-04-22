"""
SERVE Engagement Agent Service - Recommended Volunteer Handler

Parallel handler for recommended volunteer workflow.
Dispatched by the engagement agent's /api/turn endpoint based on workflow type.
Completely separate from EngagementAgentService — no imports from engagement_logic.py.
"""
import logging
import os
from typing import Any, Dict, Optional

from app.schemas.recommended_schemas import (
    RecommendedWorkflowState,
    RecommendedAgentTurnRequest,
    RecommendedAgentTurnResponse,
    _load_recommended_sub_state,
    _dump_recommended_sub_state,
)
from app.schemas.engagement_schemas import FulfillmentHandoffPayload
from app.clients.domain_client import domain_client
from app.service.recommended_llm_adapter import recommended_llm_adapter, VOLUNTEER_REGISTRATION_URL

logger = logging.getLogger(__name__)

_RECOMMENDED_TERMINAL_STATES = {
    RecommendedWorkflowState.HUMAN_REVIEW.value,
    RecommendedWorkflowState.PAUSED.value,
    RecommendedWorkflowState.NOT_REGISTERED.value,
}

_TERMINAL_FALLBACK_MESSAGES = {
    RecommendedWorkflowState.HUMAN_REVIEW.value: (
        "Thanks for sharing. A team member will follow up with you shortly."
    ),
    RecommendedWorkflowState.PAUSED.value: (
        "No problem! We'll be here when you're ready. Just message us whenever you'd like to start."
    ),
    RecommendedWorkflowState.NOT_REGISTERED.value: (
        f"It looks like you haven't registered yet. "
        f"Please sign up at {VOLUNTEER_REGISTRATION_URL} and come back after!"
    ),
}


class RecommendedVolunteerHandler:
    """
    Parallel handler for recommended volunteer workflow.
    Dispatched by the engagement agent's /api/turn endpoint
    based on workflow type.
    """

    async def process_turn(
        self, request: RecommendedAgentTurnRequest
    ) -> RecommendedAgentTurnResponse:
        """Main entry point — state machine + LLM loop."""
        session_id = str(request.session_id)
        stage = request.session_state.stage

        # Terminal state guard
        if stage in _RECOMMENDED_TERMINAL_STATES:
            logger.info(f"Session {session_id} in terminal state '{stage}' — returning fallback")
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES.get(stage, "How can I help you?"),
                state=stage,
                sub_state=request.session_state.sub_state,
                workflow=request.session_state.workflow,
            )

        # Load sub_state
        sub_state = _load_recommended_sub_state(request.session_state.sub_state)

        # Inject registration URL from config
        if not sub_state.get("registration_url"):
            sub_state["registration_url"] = VOLUNTEER_REGISTRATION_URL

        # Build conversation history (bounded to last 20 messages)
        messages = list(request.conversation_history[-20:])
        if request.user_message and request.user_message not in ("__handoff__", "__auto_continue__"):
            messages.append({"role": "user", "content": request.user_message})

        # Build system prompt
        session_context = self._build_session_context(request, sub_state)
        system_prompt = recommended_llm_adapter.build_system_prompt(session_context)

        # Build tool executor
        volunteer_phone = request.session_state.volunteer_phone

        async def tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> Any:
            return await self._execute_tool(
                tool_name, tool_input, sub_state, session_id, volunteer_phone
            )

        # Run LLM tool-calling loop
        text, collected_tool_results = await recommended_llm_adapter.run_recommended_loop(
            system_prompt=system_prompt,
            messages=messages,
            tool_executor=tool_executor,
        )

        # Check for signal_outcome
        signal = collected_tool_results.get("signal_outcome")
        if signal:
            return await self._handle_signal(signal, text, sub_state, request, session_id)

        # Loop exhausted without signal → force human_review
        if not text:
            logger.warning(f"Session {session_id}: loop exhausted without signal — forcing human_review")
            sub_state["human_review_reason"] = "loop_exhausted"
            await domain_client.log_event(session_id, "recommended_human_review", {"reason": "loop_exhausted"})
            await domain_client.advance_state(
                session_id, RecommendedWorkflowState.HUMAN_REVIEW.value, _dump_recommended_sub_state(sub_state)
            )
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES[RecommendedWorkflowState.HUMAN_REVIEW.value],
                state=RecommendedWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_recommended_sub_state(sub_state),
                workflow=request.session_state.workflow,
            )

        # Determine current workflow stage based on sub_state
        current_stage = (
            RecommendedWorkflowState.GATHERING_PREFERENCES.value
            if sub_state.get("identity_verified")
            else RecommendedWorkflowState.VERIFYING_IDENTITY.value
        )

        # Persist and return
        updated_sub_state = _dump_recommended_sub_state(sub_state)
        await domain_client.save_message(session_id, "assistant", text)
        await domain_client.advance_state(session_id, current_stage, updated_sub_state)

        return self._build_response(
            message=text,
            state=current_stage,
            sub_state=updated_sub_state,
            workflow=request.session_state.workflow,
        )

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        sub_state: Dict[str, Any],
        session_id: str,
        volunteer_phone: Optional[str] = None,
    ) -> Any:
        """Route LLM tool calls to domain_client. Handle signal_outcome locally."""

        if tool_name == "signal_outcome":
            outcome = tool_input.get("outcome")
            if outcome == "ready":
                sub_state["preference_notes"] = tool_input.get("preference_notes")
                sub_state["available_from"] = tool_input.get("available_from", "immediately")
            elif outcome == "not_registered":
                sub_state["human_review_reason"] = "not_registered"
            elif outcome == "deferred":
                sub_state["deferred"] = True
                sub_state["deferred_reason"] = tool_input.get("reason")
            elif outcome == "declined":
                sub_state["human_review_reason"] = "declined"
            return tool_input

        elif tool_name == "get_engagement_context":
            phone = volunteer_phone or tool_input.get("phone")
            if not phone:
                return {"status": "error", "error": "phone required"}
            # Return cached result if already loaded
            if (
                sub_state.get("engagement_context")
                and sub_state["engagement_context"].get("status") == "success"
            ):
                logger.info(f"Session {session_id}: returning cached engagement_context")
                return sub_state["engagement_context"]
            result = await domain_client.get_engagement_context(phone)
            if result.get("status") == "success":
                sub_state["engagement_context"] = result
                sub_state["identity_verified"] = True
            return result

        elif tool_name == "get_engagement_context_by_email":
            email = tool_input.get("email", "")
            if not email:
                return {"status": "error", "error": "email required"}
            # Return cached result if already loaded
            if (
                sub_state.get("engagement_context")
                and sub_state["engagement_context"].get("status") == "success"
            ):
                logger.info(f"Session {session_id}: returning cached engagement_context (email fallback)")
                return sub_state["engagement_context"]
            result = await domain_client.get_engagement_context_by_email(email)
            if result.get("status") == "success":
                sub_state["engagement_context"] = result
                sub_state["identity_verified"] = True
            return result

        else:
            logger.warning(f"Unknown recommended tool: {tool_name}")
            return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    async def _handle_signal(
        self,
        signal: Dict[str, Any],
        text: str,
        sub_state: Dict[str, Any],
        request: RecommendedAgentTurnRequest,
        session_id: str,
    ) -> RecommendedAgentTurnResponse:
        """Handle terminal state transitions from signal_outcome."""
        outcome = signal.get("outcome")

        if outcome == "ready":
            return await self._handle_ready(signal, text, sub_state, request, session_id)

        elif outcome == "not_registered":
            return await self._handle_not_registered(signal, text, sub_state, request, session_id)

        elif outcome == "deferred":
            await domain_client.log_event(session_id, "recommended_deferred", {
                "reason": signal.get("reason", "not specified"),
            })
            await domain_client.advance_state(
                session_id, RecommendedWorkflowState.PAUSED.value, _dump_recommended_sub_state(sub_state)
            )
            message = text or _TERMINAL_FALLBACK_MESSAGES[RecommendedWorkflowState.PAUSED.value]
            return self._build_response(
                message=message,
                state=RecommendedWorkflowState.PAUSED.value,
                sub_state=_dump_recommended_sub_state(sub_state),
                workflow=request.session_state.workflow,
            )

        elif outcome == "declined":
            sub_state["human_review_reason"] = "volunteer_declined"
            await domain_client.log_event(session_id, "recommended_declined", {
                "volunteer_id": request.session_state.volunteer_id,
            })
            await domain_client.advance_state(
                session_id, RecommendedWorkflowState.HUMAN_REVIEW.value, _dump_recommended_sub_state(sub_state)
            )
            message = text or (
                "No worries at all. Feel free to reach out whenever you're ready to volunteer."
            )
            return self._build_response(
                message=message,
                state=RecommendedWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_recommended_sub_state(sub_state),
                workflow=request.session_state.workflow,
            )

        else:
            logger.warning(f"Unknown signal_outcome outcome: {outcome} — defaulting to human_review")
            await domain_client.advance_state(
                session_id, RecommendedWorkflowState.HUMAN_REVIEW.value, _dump_recommended_sub_state(sub_state)
            )
            return self._build_response(
                message=text or _TERMINAL_FALLBACK_MESSAGES[RecommendedWorkflowState.HUMAN_REVIEW.value],
                state=RecommendedWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_recommended_sub_state(sub_state),
                workflow=request.session_state.workflow,
            )

    async def _handle_ready(
        self,
        signal: Dict[str, Any],
        text: str,
        sub_state: Dict[str, Any],
        request: RecommendedAgentTurnRequest,
        session_id: str,
    ) -> RecommendedAgentTurnResponse:
        """Build FulfillmentHandoffPayload and emit handoff event."""
        payload = self._build_handoff_payload(request, sub_state)

        if not payload:
            sub_state["human_review_reason"] = "missing_handoff_context"
            await domain_client.log_event(session_id, "recommended_human_review", {
                "reason": "missing_handoff_context",
            })
            await domain_client.advance_state(
                session_id, RecommendedWorkflowState.HUMAN_REVIEW.value, _dump_recommended_sub_state(sub_state)
            )
            return self._build_response(
                message=(
                    "Thanks — I have your preferences, but I need a teammate to check the details before moving ahead."
                ),
                state=RecommendedWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_recommended_sub_state(sub_state),
                workflow=request.session_state.workflow,
            )

        sub_state["handoff"] = payload
        await domain_client.log_event(session_id, "recommended_ready", {
            "volunteer_id": payload.get("volunteer_id"),
            "preference_notes": payload.get("preference_notes"),
        })
        await domain_client.advance_state(
            session_id, "active", _dump_recommended_sub_state(sub_state)
        )

        message = text or (
            "Wonderful! I've noted your preferences and will now find the best teaching opportunity for you. 🔍"
        )

        return self._build_response(
            message=message,
            state="active",
            sub_state=_dump_recommended_sub_state(sub_state),
            handoff_event={
                "session_id": str(request.session_id),
                "from_agent": "engagement",
                "to_agent": "fulfillment",
                "handoff_type": "agent_transition",
                "payload": payload,
                "reason": "Recommended volunteer confirmed teaching preferences",
            },
            workflow=request.session_state.workflow,
        )

    async def _handle_not_registered(
        self,
        signal: Dict[str, Any],
        text: str,
        sub_state: Dict[str, Any],
        request: RecommendedAgentTurnRequest,
        session_id: str,
    ) -> RecommendedAgentTurnResponse:
        """Return registration URL message, advance to NOT_REGISTERED."""
        await domain_client.log_event(session_id, "recommended_not_registered", {
            "registration_url": VOLUNTEER_REGISTRATION_URL,
        })
        await domain_client.advance_state(
            session_id, RecommendedWorkflowState.NOT_REGISTERED.value, _dump_recommended_sub_state(sub_state)
        )

        message = text or (
            f"It looks like you haven't registered yet. "
            f"Please sign up at {VOLUNTEER_REGISTRATION_URL} and come back after!"
        )
        # Ensure the registration URL is in the message
        if VOLUNTEER_REGISTRATION_URL not in message:
            message += f"\n\nYou can register here: {VOLUNTEER_REGISTRATION_URL}"

        return self._build_response(
            message=message,
            state=RecommendedWorkflowState.NOT_REGISTERED.value,
            sub_state=_dump_recommended_sub_state(sub_state),
            workflow=request.session_state.workflow,
        )

    def _build_handoff_payload(
        self, request: RecommendedAgentTurnRequest, sub_state: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Build FulfillmentHandoffPayload — same shape as existing flow.
        Key difference: fulfillment_history is always empty, continuity is always 'different'."""
        context = sub_state.get("engagement_context") or {}
        volunteer_id = (
            context.get("volunteer_id")
            or request.session_state.volunteer_id
        )
        if not volunteer_id:
            return None

        name = (
            context.get("volunteer_name")
            or request.session_state.volunteer_name
            or (context.get("volunteer_profile") or {}).get("full_name")
            or "Volunteer"
        )

        payload = FulfillmentHandoffPayload(
            volunteer_id=str(volunteer_id),
            volunteer_name=name,
            continuity="different",
            preferred_need_id=None,
            preferred_school_id=None,
            preference_notes=sub_state.get("preference_notes"),
            fulfillment_history=[],
        )
        return payload.model_dump(mode="json")

    def _build_session_context(
        self,
        request: RecommendedAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assemble context dict for the system prompt."""
        ctx: Dict[str, Any] = {
            "entry_type": sub_state.get("entry_type", "recommended"),
            "volunteer_id": request.session_state.volunteer_id,
            "volunteer_name": request.session_state.volunteer_name,
            "volunteer_phone": request.session_state.volunteer_phone,
            "identity_verified": sub_state.get("identity_verified", False),
        }
        # Surface name from engagement context if session name is missing
        engagement_context = sub_state.get("engagement_context") or {}
        if not ctx["volunteer_name"] and engagement_context.get("volunteer_name"):
            ctx["volunteer_name"] = engagement_context["volunteer_name"]
        return ctx

    def _build_response(
        self,
        message: str,
        state: str,
        sub_state: Optional[str],
        handoff_event: Optional[Dict[str, Any]] = None,
        auto_continue: bool = False,
        workflow: str = "recommended_volunteer",
    ) -> RecommendedAgentTurnResponse:
        return RecommendedAgentTurnResponse(
            assistant_message=message,
            workflow=workflow,
            state=state,
            sub_state=sub_state,
            handoff_event=handoff_event,
            auto_continue=auto_continue,
        )


# Singleton
recommended_handler = RecommendedVolunteerHandler()
