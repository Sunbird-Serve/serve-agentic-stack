"""
SERVE Engagement Agent Service - Core Logic (L3.5)

Thin state machine that wraps the LLM tool-calling loop.
The LLM owns all branching logic. The state machine only enforces terminal conditions.

Focused on: active volunteers who fulfilled needs and are re-engaging (user-initiated).
"""
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.schemas.engagement_schemas import (
    EngagementWorkflowState,
    EngagementAgentTurnRequest,
    EngagementAgentTurnResponse,
    FulfillmentHandoffPayload,
    _load_sub_state,
    _dump_sub_state,
)
from app.clients.domain_client import domain_client
from app.service.llm_adapter import llm_adapter

logger = logging.getLogger(__name__)

# ── Configurable: max days a volunteer can delay before we defer instead of handoff
_MAX_START_DELAY_DAYS = int(os.environ.get("ENGAGEMENT_MAX_START_DELAY_DAYS", "10"))

_TERMINAL_STATES = {
    EngagementWorkflowState.HUMAN_REVIEW.value,
    EngagementWorkflowState.PAUSED.value,
}

_TERMINAL_FALLBACK_MESSAGES = {
    EngagementWorkflowState.HUMAN_REVIEW.value: (
        "Thanks for sharing. A team member will follow up with you shortly."
    ),
    EngagementWorkflowState.PAUSED.value: (
        "No problem. We'll reconnect when your timing is better. Just message us whenever you're ready."
    ),
}


class EngagementAgentService:
    """
    L3.5 engagement agent.
    Routes all non-terminal turns to the LLM tool-calling loop.
    Watches tool_results for signal_outcome to transition to terminal states.
    """

    async def process_turn(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        session_id = str(request.session_id)
        stage = request.session_state.stage

        # ── Terminal state: return fallback, do not call LLM ─────────────────
        if stage in _TERMINAL_STATES:
            logger.info(f"Session {session_id} in terminal state '{stage}' — returning fallback")
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES.get(stage, "How can I help you?"),
                state=stage,
                sub_state=request.session_state.sub_state,
            )

        # ── Load sub_state ────────────────────────────────────────────────────
        sub_state = _load_sub_state(request.session_state.sub_state)

        # ── Pre-load engagement context if not already cached ─────────────────
        context_was_missing = not sub_state.get("engagement_context")
        if context_was_missing and request.session_state.volunteer_phone:
            try:
                ctx = await domain_client.get_engagement_context(request.session_state.volunteer_phone)
                if ctx.get("status") == "success":
                    sub_state["engagement_context"] = ctx
                    # Back-fill volunteer_id and name from registry if session lacks them
                    if not request.session_state.volunteer_id and ctx.get("volunteer_id"):
                        request.session_state.volunteer_id = ctx["volunteer_id"]
                    if not request.session_state.volunteer_name and ctx.get("volunteer_name"):
                        request.session_state.volunteer_name = ctx["volunteer_name"]
            except Exception as e:
                logger.warning(f"Session {session_id}: pre-load engagement context failed: {e}")

        # ── First-turn fast-ack: return immediately, let UI auto-continue ─────
        is_first_turn = len(request.conversation_history) == 0
        if is_first_turn and context_was_missing:
            ack_message = "One moment, let me pull up your details... 🔍"
            updated_sub_state = _dump_sub_state(sub_state)
            await domain_client.save_message(session_id, "assistant", ack_message)
            await domain_client.advance_state(
                session_id, EngagementWorkflowState.RE_ENGAGING.value, updated_sub_state
            )
            return self._build_response(
                message=ack_message,
                state=EngagementWorkflowState.RE_ENGAGING.value,
                sub_state=updated_sub_state,
                auto_continue=True,
            )

        # ── Build conversation history (bounded to last 20 messages) ──────────
        messages = list(request.conversation_history[-20:])
        if request.user_message and request.user_message != "__auto_continue__":
            messages.append({"role": "user", "content": request.user_message})
        # ── Build system prompt ───────────────────────────────────────────────
        session_context = self._build_session_context(request, sub_state)
        system_prompt = llm_adapter.build_system_prompt(session_context)

        # ── Build tool executor ───────────────────────────────────────────────
        volunteer_phone = request.session_state.volunteer_phone
        async def tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> Any:
            return await self._execute_tool(tool_name, tool_input, sub_state, session_id, volunteer_phone)

        # ── Run L3.5 loop ─────────────────────────────────────────────────────
        text, collected_tool_results = await llm_adapter.run_engagement_loop(
            system_prompt=system_prompt,
            messages=messages,
            tool_executor=tool_executor,
        )

        # ── Check for signal_outcome ──────────────────────────────────────────
        signal = collected_tool_results.get("signal_outcome")
        if signal:
            return await self._handle_signal(
                signal=signal,
                text=text,
                sub_state=sub_state,
                request=request,
                session_id=session_id,
            )

        # ── Loop exhausted without signal → force human_review ────────────────
        if not text:
            logger.warning(f"Session {session_id}: loop exhausted without signal — forcing human_review")
            sub_state["human_review_reason"] = "loop_exhausted"
            await domain_client.log_event(session_id, "engagement_human_review", {"reason": "loop_exhausted"})
            await domain_client.advance_state(
                session_id, EngagementWorkflowState.HUMAN_REVIEW.value, _dump_sub_state(sub_state)
            )
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES[EngagementWorkflowState.HUMAN_REVIEW.value],
                state=EngagementWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_sub_state(sub_state),
            )

        # ── Active turn: persist and return ──────────────────────────────────
        updated_sub_state = _dump_sub_state(sub_state)
        await domain_client.save_message(session_id, "assistant", text)
        await domain_client.advance_state(
            session_id, EngagementWorkflowState.RE_ENGAGING.value, updated_sub_state
        )

        return self._build_response(
            message=text,
            state=EngagementWorkflowState.RE_ENGAGING.value,
            sub_state=updated_sub_state,
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
            # Handled locally — store in sub_state, do NOT call MCP
            outcome = tool_input.get("outcome")
            if outcome == "ready":
                sub_state["preference_notes"] = tool_input.get("preference_notes")
                sub_state["continuity"] = tool_input.get("continuity", "same")
                sub_state["preferred_need_id"] = tool_input.get("preferred_need_id")
                sub_state["available_from"] = tool_input.get("available_from", "immediately")
            elif outcome in ("declined", "already_active"):
                sub_state["human_review_reason"] = outcome
            elif outcome == "deferred":
                sub_state["deferred"] = True
                sub_state["deferred_reason"] = tool_input.get("reason")
            return tool_input

        elif tool_name == "get_engagement_context":
            # Always use the session phone — never trust what the LLM passes in tool_input
            # to prevent hallucinated phone numbers hitting the API on subsequent turns.
            phone = volunteer_phone
            if not phone:
                return {"status": "error", "error": "phone required"}
            # Return cached result if already loaded — avoid redundant API calls
            if sub_state.get("engagement_context"):
                logger.info(f"Session {session_id}: returning cached engagement_context")
                return sub_state["engagement_context"]
            result = await domain_client.get_engagement_context(phone)
            if result.get("status") == "success":
                sub_state["engagement_context"] = result
            return result

        else:
            logger.warning(f"Unknown engagement tool: {tool_name}")
            return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    async def _handle_signal(
        self,
        signal: Dict[str, Any],
        text: str,
        sub_state: Dict[str, Any],
        request: EngagementAgentTurnRequest,
        session_id: str,
    ) -> EngagementAgentTurnResponse:
        """Handle terminal state transitions from signal_outcome."""
        outcome = signal.get("outcome")

        if outcome == "ready":
            return await self._handle_ready(signal, text, sub_state, request, session_id)

        # TEMPORARILY DISABLED: already_active check (nomination data not cycle-filtered yet)
        # elif outcome == "already_active":
        #     reason = signal.get("reason", "volunteer_already_nominated")
        #     await domain_client.log_event(session_id, "engagement_already_active", {"reason": reason})
        #     await domain_client.advance_state(
        #         session_id, EngagementWorkflowState.HUMAN_REVIEW.value, _dump_sub_state(sub_state)
        #     )
        #     message = text or (
        #         "It looks like you already have an active placement in progress. "
        #         "A team member will be in touch with you shortly."
        #     )
        #     return self._build_response(
        #         message=message,
        #         state=EngagementWorkflowState.HUMAN_REVIEW.value,
        #         sub_state=_dump_sub_state(sub_state),
        #     )

        elif outcome == "deferred":
            await domain_client.engagement_update_volunteer_status(
                session_id,
                volunteer_status="pause_outreach",
                reason="volunteer_deferred",
            )
            await domain_client.save_memory_summary(
                session_id=session_id,
                summary_text=f"Volunteer deferred re-engagement. Reason: {signal.get('reason', 'not specified')}.",
                key_facts=["Outcome: deferred"],
                volunteer_id=request.session_state.volunteer_id,
            )
            await domain_client.advance_state(
                session_id, EngagementWorkflowState.PAUSED.value, _dump_sub_state(sub_state)
            )
            message = text or _TERMINAL_FALLBACK_MESSAGES[EngagementWorkflowState.PAUSED.value]
            return self._build_response(
                message=message,
                state=EngagementWorkflowState.PAUSED.value,
                sub_state=_dump_sub_state(sub_state),
            )

        elif outcome == "declined":
            sub_state["human_review_reason"] = "volunteer_declined"
            await domain_client.log_event(session_id, "volunteer_consent", {
                "consent": "no",
                "year": datetime.utcnow().year,
                "volunteer_id": request.session_state.volunteer_id,
                "volunteer_phone": request.session_state.volunteer_phone,
            })
            await domain_client.engagement_update_volunteer_status(
                session_id,
                volunteer_status="opt_out",
                reason="volunteer_declined",
            )
            await domain_client.save_memory_summary(
                session_id=session_id,
                summary_text="Volunteer declined re-engagement.",
                key_facts=["Outcome: declined"],
                volunteer_id=request.session_state.volunteer_id,
            )
            await domain_client.advance_state(
                session_id, EngagementWorkflowState.HUMAN_REVIEW.value, _dump_sub_state(sub_state)
            )
            message = text or (
                "Thank you for letting us know. We won't push further — come back whenever you're ready."
            )
            return self._build_response(
                message=message,
                state=EngagementWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_sub_state(sub_state),
            )

        else:
            logger.warning(f"Unknown signal_outcome outcome: {outcome} — defaulting to human_review")
            await domain_client.advance_state(
                session_id, EngagementWorkflowState.HUMAN_REVIEW.value, _dump_sub_state(sub_state)
            )
            return self._build_response(
                message=text or _TERMINAL_FALLBACK_MESSAGES[EngagementWorkflowState.HUMAN_REVIEW.value],
                state=EngagementWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_sub_state(sub_state),
            )

    async def _handle_ready(
        self,
        signal: Dict[str, Any],
        text: str,
        sub_state: Dict[str, Any],
        request: EngagementAgentTurnRequest,
        session_id: str,
    ) -> EngagementAgentTurnResponse:
        """Volunteer confirmed — build handoff payload and emit to fulfillment."""
        # Record consent to continue for this cycle
        await domain_client.log_event(session_id, "volunteer_consent", {
            "consent": "yes",
            "year": datetime.utcnow().year,
            "volunteer_id": request.session_state.volunteer_id,
            "volunteer_phone": request.session_state.volunteer_phone,
        })

        # ── Check availability timeline — defer if too far out ────────────────
        available_from = sub_state.get("available_from", "immediately")
        delay_days = self._estimate_delay_days(available_from)
        logger.info(
            f"Session {session_id}: available_from={available_from!r}, "
            f"estimated_delay={delay_days}d, threshold={_MAX_START_DELAY_DAYS}d"
        )

        if delay_days is not None and delay_days > _MAX_START_DELAY_DAYS:
            # Too far out — defer instead of handing off to fulfillment
            sub_state["deferred"] = True
            sub_state["human_review_reason"] = "start_delay_too_long"
            await domain_client.engagement_update_volunteer_status(
                session_id,
                volunteer_status="pause_outreach",
                reason=f"volunteer_available_in_{delay_days}_days",
            )
            await domain_client.save_memory_summary(
                session_id=session_id,
                summary_text=(
                    f"Volunteer wants to continue but can't start for ~{delay_days} days "
                    f"(available_from: {available_from}). Deferred — will reconnect closer to their availability."
                ),
                key_facts=[
                    "Outcome: deferred_start_delay",
                    f"Available from: {available_from}",
                    f"Continuity: {sub_state.get('continuity', 'same')}",
                ],
                volunteer_id=request.session_state.volunteer_id,
            )
            await domain_client.advance_state(
                session_id, EngagementWorkflowState.PAUSED.value, _dump_sub_state(sub_state)
            )
            message = text or (
                "Thank you for confirming! Since you're available a bit later, "
                "we'll reach out closer to when you can start. Talk soon! 🙏"
            )
            return self._build_response(
                message=message,
                state=EngagementWorkflowState.PAUSED.value,
                sub_state=_dump_sub_state(sub_state),
            )

        # Try MCP-side handoff preparation first
        handoff_result = await domain_client.engagement_prepare_fulfillment_handoff(
            session_id,
            signals={
                "preference_notes": sub_state.get("preference_notes"),
                "continuity": sub_state.get("continuity", "same"),
                "preferred_need_id": sub_state.get("preferred_need_id"),
            },
        )

        payload = (
            handoff_result.get("handoff_payload")
            if isinstance(handoff_result, dict)
            else None
        )

        # Fall back to building payload locally from sub_state + cached context
        if not payload:
            payload = self._build_local_payload(request, sub_state)

        if not payload:
            sub_state["human_review_reason"] = "missing_handoff_context"
            await domain_client.engagement_update_volunteer_status(
                session_id, volunteer_status="human_review", reason="missing_handoff_context"
            )
            await domain_client.advance_state(
                session_id, EngagementWorkflowState.HUMAN_REVIEW.value, _dump_sub_state(sub_state)
            )
            return self._build_response(
                message=(
                    "Thanks — I have your preference, but I need a teammate to check the details before moving ahead."
                ),
                state=EngagementWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_sub_state(sub_state),
            )

        sub_state["handoff"] = payload
        await domain_client.engagement_update_volunteer_status(
            session_id, volunteer_status="opportunity_readiness", reason="ready_for_fulfillment"
        )
        await domain_client.save_memory_summary(
            session_id=session_id,
            summary_text=(
                f"Volunteer confirmed re-engagement. "
                f"Continuity: {sub_state.get('continuity', 'same')}. "
                f"Preferences: {sub_state.get('preference_notes', '')}. "
                f"Available from: {sub_state.get('available_from', 'immediately')}."
            ),
            key_facts=[
                f"Outcome: ready_for_fulfillment",
                f"Continuity: {sub_state.get('continuity', 'same')}",
                f"Available from: {sub_state.get('available_from', 'immediately')}",
            ],
            volunteer_id=request.session_state.volunteer_id,
        )
        await domain_client.advance_state(
            session_id, "active", _dump_sub_state(sub_state)
        )

        message = text or (
            "Perfect! Give me a moment while I find the best teaching opportunity for you... 🔍"
        )

        return self._build_response(
            message=message,
            state="active",
            sub_state=_dump_sub_state(sub_state),
            handoff_event={
                "session_id": str(request.session_id),
                "from_agent": "engagement",
                "to_agent": "fulfillment",
                "handoff_type": "agent_transition",
                "payload": payload,
                "reason": "Volunteer confirmed continuation preferences",
            },
        )

    @staticmethod
    def _estimate_delay_days(available_from: str) -> Optional[int]:
        """
        Estimate how many days from now until the volunteer can start.
        Returns None if unparseable (treat as immediate).
        """
        if not available_from:
            return 0

        lower = available_from.strip().lower()

        # Immediate signals
        if lower in ("immediately", "now", "today", "abhi", "kal se", "tomorrow", "right away", "haan abhi se"):
            return 0
        if lower == "tomorrow" or lower == "kal":
            return 1

        # Try ISO date parse (YYYY-MM-DD)
        try:
            target = datetime.strptime(available_from.strip()[:10], "%Y-%m-%d").date()
            delta = (target - datetime.utcnow().date()).days
            return max(delta, 0)
        except (ValueError, TypeError):
            pass

        # Try to extract "N weeks/days/month" patterns
        m = re.search(r"(\d+)\s*(day|week|month)", lower)
        if m:
            n = int(m.group(1))
            unit = m.group(2)
            if "day" in unit:
                return n
            if "week" in unit:
                return n * 7
            if "month" in unit:
                return n * 30

        # Common Hindi/English phrases
        if any(w in lower for w in ("next month", "agle mahine", "agle month")):
            return 30
        if any(w in lower for w in ("2 week", "do hafte", "two week")):
            return 14
        if any(w in lower for w in ("next week", "agle hafte")):
            return 7
        if any(w in lower for w in ("after exam", "exam ke baad")):
            return 21  # conservative estimate

        # Can't parse — treat as unknown, don't block
        return None

    def _build_local_payload(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Build FulfillmentHandoffPayload locally when MCP doesn't return one."""
        context = sub_state.get("engagement_context") or {}

        # Prefer volunteer_id from cached context (resolved via phone lookup)
        # over session_state which may not have been persisted back to DB
        volunteer_id = (
            context.get("volunteer_id")
            or request.session_state.volunteer_id
        )
        if not volunteer_id:
            return None

        history = context.get("fulfillment_history") or []
        latest = history[0] if history else {}

        continuity = sub_state.get("continuity") or "same"
        preferred_need_id = sub_state.get("preferred_need_id")
        if continuity == "same" and not preferred_need_id and latest.get("need_id"):
            preferred_need_id = latest.get("need_id")

        name = (
            context.get("volunteer_name")
            or request.session_state.volunteer_name
            or (context.get("volunteer_profile") or {}).get("full_name")
            or "Volunteer"
        )

        payload = FulfillmentHandoffPayload(
            volunteer_id=str(volunteer_id),
            volunteer_name=name,
            continuity=continuity,
            preferred_need_id=preferred_need_id if continuity == "same" else None,
            preferred_school_id=latest.get("entity_id") if continuity == "same" else None,
            preference_notes=sub_state.get("preference_notes"),
            fulfillment_history=history,
        )
        return payload.model_dump(mode="json")

    def _build_session_context(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assemble context dict for the system prompt."""
        ctx: Dict[str, Any] = {
            "volunteer_id":    request.session_state.volunteer_id,
            "volunteer_name":  request.session_state.volunteer_name,
            "volunteer_phone": request.session_state.volunteer_phone,
            "last_active_at":  request.session_state.last_active_at,
        }
        # Surface cached fulfillment history if already loaded
        engagement_context = sub_state.get("engagement_context") or {}
        if engagement_context.get("fulfillment_history"):
            ctx["fulfillment_history"] = engagement_context["fulfillment_history"]
        # Also surface name from registry if session name is missing
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
    ) -> EngagementAgentTurnResponse:
        return EngagementAgentTurnResponse(
            assistant_message=message,
            state=state,
            sub_state=sub_state,
            handoff_event=handoff_event,
            auto_continue=auto_continue,
        )


# Singleton
engagement_agent_service = EngagementAgentService()
