"""
SERVE Fulfillment Agent Service - Core Logic

Two-phase approach:
  Phase 1 — Python MatchFinder finds the best open need (no LLM)
  Phase 2 — LLM presents the match, handles yes/no, nominates

LLM is only called ONCE per turn (max 4 iterations total per session).
"""
import logging
from typing import Any, Dict, Optional

from app.schemas.fulfillment_schemas import (
    FulfillmentWorkflowState,
    FulfillmentAgentTurnRequest,
    FulfillmentAgentTurnResponse,
    _load_sub_state,
    _dump_sub_state,
)
from app.clients.domain_client import domain_client
from app.service.llm_adapter import llm_adapter
from app.service.matching_service import match_finder

logger = logging.getLogger(__name__)

_TERMINAL_STATES = {
    FulfillmentWorkflowState.COMPLETE.value,
    FulfillmentWorkflowState.PAUSED.value,
    # NOTE: human_review is NOT terminal for the volunteer conversation —
    # the LLM stays active in support mode so volunteers can still ask questions.
}

_TERMINAL_FALLBACK_MESSAGES = {
    FulfillmentWorkflowState.COMPLETE.value:     "Aapki jagah confirm ho gayi hai. Coordinator jald hi aapse contact karenge.",
    FulfillmentWorkflowState.HUMAN_REVIEW.value: "Hamari team aapke liye sahi jagah dhundh rahi hai. Jald hi contact karenge.",
    FulfillmentWorkflowState.PAUSED.value:       "Koi baat nahi! Aap jab chahein wapas aa sakte hain.",
}


class FulfillmentAgentService:

    async def process_turn(self, request: FulfillmentAgentTurnRequest) -> FulfillmentAgentTurnResponse:
        session_id = str(request.session_id)
        stage = request.session_state.stage
        workflow = request.session_state.workflow

        # ── Terminal state guard ──────────────────────────────────────────────
        if stage in _TERMINAL_STATES:
            logger.info(f"Session {session_id} in terminal state '{stage}'")
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES.get(stage, "Shukriya!"),
                state=stage,
                sub_state=request.session_state.sub_state,
                workflow=workflow,
            )

        # ── Load sub_state ────────────────────────────────────────────────────
        sub_state = _load_sub_state(request.session_state.sub_state)
        handoff = sub_state.get("handoff") or {}
        logger.info(f"Session {session_id}: stage={stage}, handoff keys={list(handoff.keys())}, handoff volunteer_id={handoff.get('volunteer_id')}, preference_notes={handoff.get('preference_notes')}")

        if not handoff and request.session_state.volunteer_id:
            handoff = {
                "volunteer_id": request.session_state.volunteer_id,
                "volunteer_name": request.session_state.volunteer_name or "",
                "continuity": "same",
            }
            sub_state["handoff"] = handoff

        # ── Phase 1: find match (Python, no LLM) — only on first turn ────────
        # On handoff turn, return an ack immediately and let the UI auto-continue.
        # Context fetch + matching will run on the follow-up request (match_result cached).
        is_handoff_turn = (
            request.user_message == "__handoff__"
            and not sub_state.get("match_result")
        )

        if is_handoff_turn and handoff:
            ack_message = "Searching for available opportunities... 🔍"
            # Run match finder now so it's cached for the auto-continue turn
            logger.info(f"Session {session_id}: running MatchFinder")
            match_result = await match_finder.find(handoff)
            sub_state["match_result"] = {
                "status": match_result.status,
                "candidates": match_result.candidates,
                "reason": match_result.reason,
            }
            logger.info(
                f"Session {session_id}: match status={match_result.status}, "
                f"candidates={len(match_result.candidates)}"
            )
            updated = _dump_sub_state(sub_state)
            await domain_client.save_message(session_id, "assistant", ack_message)
            await domain_client.advance_state(session_id, FulfillmentWorkflowState.ACTIVE.value, updated)
            return self._build_response(
                message=ack_message,
                state=FulfillmentWorkflowState.ACTIVE.value,
                sub_state=updated,
                auto_continue=True,
                workflow=workflow,
            )

        # Cache match result in sub_state so subsequent turns skip re-searching
        match_result = None
        if not sub_state.get("match_result") and handoff:
            logger.info(f"Session {session_id}: running MatchFinder")
            match_result = await match_finder.find(handoff)
            sub_state["match_result"] = {
                "status": match_result.status,
                "candidates": match_result.candidates,
                "reason": match_result.reason,
            }
            logger.info(
                f"Session {session_id}: match status={match_result.status}, "
                f"candidates={len(match_result.candidates)}"
            )
        else:
            # Reconstruct from cache
            from app.service.matching_service import MatchResult
            cached = sub_state.get("match_result", {})
            match_result = MatchResult(
                status=cached.get("status", "not_found"),
                candidates=cached.get("candidates", []),
                reason=cached.get("reason"),
            )

        # ── Phase 2: LLM conversation ─────────────────────────────────────────
        match_context = llm_adapter.format_match_context(match_result)
        # In human_review stage, switch to support mode prompt
        if stage == FulfillmentWorkflowState.HUMAN_REVIEW.value:
            system_prompt = llm_adapter.build_support_prompt(handoff)
        else:
            system_prompt = llm_adapter.build_system_prompt(handoff, match_context)

        # Build messages — skip synthetic triggers
        messages = list(request.conversation_history[-20:])
        if request.user_message and request.user_message not in ("__handoff__", "__auto_continue__"):
            messages.append({"role": "user", "content": request.user_message})
        elif request.user_message == "__auto_continue__":
            # Auto-continue after ack — inject ack as prior turn so LLM continues from it
            ack = "Searching for available opportunities... 🔍"
            if not messages:
                messages = [
                    {"role": "assistant", "content": ack},
                    {"role": "user", "content": "Show me what you found."},
                ]
        elif request.user_message == "__handoff__" and not messages:
            messages.append({"role": "user", "content": "Find me a teaching opportunity."})

        async def tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> Any:
            return await self._execute_tool(tool_name, tool_input, sub_state, session_id)

        text, collected = await llm_adapter.run_conversation_loop(
            system_prompt=system_prompt,
            messages=messages,
            tool_executor=tool_executor,
            max_iterations=8,
        )

        # ── Handle signal_outcome ─────────────────────────────────────────────
        signal = collected.get("signal_outcome")
        if signal:
            return await self._handle_terminal(
                outcome=signal.get("outcome"),
                signal=signal,
                text=text,
                sub_state=sub_state,
                session_id=session_id,
                workflow=workflow,
            )

        # ── Loop exhausted ────────────────────────────────────────────────────
        if not text:
            logger.warning(f"Session {session_id}: loop exhausted — forcing HUMAN_REVIEW")
            sub_state["human_review_reason"] = "loop_exhausted"
            await domain_client.log_event(session_id, "fulfillment_human_review", {"reason": "loop_exhausted"})
            await domain_client.advance_state(
                session_id, FulfillmentWorkflowState.HUMAN_REVIEW.value, _dump_sub_state(sub_state)
            )
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES[FulfillmentWorkflowState.HUMAN_REVIEW.value],
                state=FulfillmentWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_sub_state(sub_state),
                workflow=workflow,
            )

        # ── Active turn ───────────────────────────────────────────────────────
        updated = _dump_sub_state(sub_state)
        await domain_client.save_message(session_id, "assistant", text)
        await domain_client.advance_state(session_id, FulfillmentWorkflowState.ACTIVE.value, updated)
        return self._build_response(
            message=text,
            state=FulfillmentWorkflowState.ACTIVE.value,
            sub_state=updated,
            workflow=workflow,
        )

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        sub_state: Dict[str, Any],
        session_id: str,
    ) -> Any:
        if tool_name == "signal_outcome":
            outcome = tool_input.get("outcome")
            need_id = tool_input.get("need_id")
            if outcome == "nominated" and need_id:
                sub_state["nominated_need_id"] = need_id
                sub_state["teaching_consent"] = "confirmed"
                sub_state["teaching_consent_at"] = __import__("datetime").datetime.utcnow().isoformat()
            elif outcome == "human_review":
                sub_state["human_review_reason"] = tool_input.get("reason", "unknown")
                sub_state["teaching_consent"] = "pending"
            elif outcome == "declined":
                sub_state["teaching_consent"] = "declined"
            elif outcome == "deferred":
                sub_state["teaching_consent"] = "pending"
            return tool_input

        elif tool_name == "get_more_needs":
            hint = tool_input.get("hint", "")
            handoff = sub_state.get("handoff", {})
            # Merge hint with original preferences instead of overwriting
            original_notes = handoff.get("preference_notes") or ""
            merged_notes = f"{original_notes}; {hint}".strip("; ") if original_notes else hint
            relaxed_handoff = {
                **handoff,
                "preference_notes": merged_notes,
                "preferred_school_id": None,   # broaden to all schools
                "preferred_need_id": None,
            }
            new_match = await match_finder.find(relaxed_handoff)
            # Update cached match result
            sub_state["match_result"] = {
                "status": new_match.status,
                "candidates": new_match.candidates,
                "reason": new_match.reason,
            }
            return llm_adapter.format_match_context(new_match)

        elif tool_name == "nominate_volunteer_for_need":
            # Guard: prevent duplicate nominations in the same session
            if sub_state.get("nominated_need_id"):
                existing = sub_state["nominated_need_id"]
                logger.warning(
                    f"Session {session_id}: blocked duplicate nomination — "
                    f"already nominated for {existing}"
                )
                return {
                    "status": "error",
                    "reason": "already_nominated",
                    "existing_need_id": existing,
                    "message": "Volunteer already nominated for a need in this session.",
                }
            result = await domain_client.nominate_volunteer_for_need(
                need_id=tool_input["need_id"],
                volunteer_id=tool_input["volunteer_id"],
            )
            # Track successful nomination + teaching consent
            if isinstance(result, dict) and result.get("status") != "error":
                sub_state["nominated_need_id"] = tool_input["need_id"]
                nomination = result.get("nomination") or {}
                sub_state["nomination_id"] = nomination.get("id") or nomination.get("osid")
                sub_state["teaching_consent"] = "confirmed"
                sub_state["teaching_consent_at"] = __import__("datetime").datetime.utcnow().isoformat()
            return result

        else:
            logger.warning(f"Unknown tool: {tool_name}")
            return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    async def _handle_terminal(
        self,
        outcome: str,
        signal: Dict[str, Any],
        text: str,
        sub_state: Dict[str, Any],
        session_id: str,
        workflow: str = "returning_volunteer",
    ) -> FulfillmentAgentTurnResponse:
        handoff_event = None
        if outcome == "nominated":
            need_id = signal.get("need_id") or sub_state.get("nominated_need_id")
            sub_state["nominated_need_id"] = need_id
            volunteer_id = sub_state.get("handoff", {}).get("volunteer_id")
            await domain_client.log_event(session_id, "fulfillment_nominated", {
                "need_id": need_id,
                "volunteer_id": volunteer_id,
            })
            new_state = FulfillmentWorkflowState.COMPLETE.value
            message = text or "Shukriya! Coordinator review karenge aur jald hi aapse contact karenge."

            # Hand off to the delivery assistant so activation actually starts —
            # a nomination alone never used to trigger anything downstream.
            # Pull whatever the matched candidate already told us (entity_id,
            # programme) rather than making another Serve Registry call; a
            # coordinator_id isn't present in this flattened need shape, so
            # notify_linked_stakeholder falls back to its documented
            # first-contact capture for that (see delivery_service.py).
            candidates = (sub_state.get("match_result") or {}).get("candidates") or []
            matched = next((c for c in candidates if c.get("id") == need_id), {})
            handoff_event = {
                "session_id": session_id,
                "from_agent": "fulfillment",
                "to_agent": "delivery_assistant",
                "handoff_type": "agent_transition",
                "payload": {
                    "volunteer_id": volunteer_id,
                    "volunteer_name": sub_state.get("handoff", {}).get("volunteer_name"),
                    "need_id": need_id,
                    "nomination_id": sub_state.get("nomination_id"),
                    "entity_id": matched.get("entity_id"),
                    "programme": matched.get("name") or ", ".join(matched.get("subjects") or []) or None,
                },
                "reason": "Volunteer nominated for a teaching need",
            }
            new_state = "activation_started"

        elif outcome == "human_review":
            reason = signal.get("reason") or sub_state.get("human_review_reason", "unknown")
            sub_state["human_review_reason"] = reason
            await domain_client.log_event(session_id, "fulfillment_human_review", {
                "reason": reason,
                "volunteer_id": sub_state.get("handoff", {}).get("volunteer_id"),
            })
            new_state = FulfillmentWorkflowState.HUMAN_REVIEW.value
            message = text or _TERMINAL_FALLBACK_MESSAGES[new_state]

        elif outcome == "paused":
            new_state = FulfillmentWorkflowState.PAUSED.value
            message = text or _TERMINAL_FALLBACK_MESSAGES[new_state]

        else:
            logger.warning(f"Unknown outcome: {outcome} — defaulting to HUMAN_REVIEW")
            new_state = FulfillmentWorkflowState.HUMAN_REVIEW.value
            message = text or _TERMINAL_FALLBACK_MESSAGES[new_state]

        updated = _dump_sub_state(sub_state)
        await domain_client.advance_state(session_id, new_state, updated)
        if message:
            await domain_client.save_message(session_id, "assistant", message)

        # Build new_facts for the volunteer fact-store
        response_new_facts = {}
        if outcome == "nominated":
            import datetime as _dt
            response_new_facts = {
                "teaching_consent": "confirmed",
                "teaching_consent_at": _dt.datetime.utcnow().isoformat(),
                "commitments": [{
                    "need_id": sub_state.get("nominated_need_id"),
                    "status": "nominated",
                    "nominated_at": _dt.datetime.utcnow().isoformat(),
                }],
            }
        elif outcome in ("human_review", "deferred"):
            response_new_facts = {"teaching_consent": "pending"}
        elif outcome == "declined":
            response_new_facts = {"teaching_consent": "declined"}

        return self._build_response(message=message, state=new_state, sub_state=updated,
                                     workflow=workflow, handoff_event=handoff_event,
                                     new_facts=response_new_facts)

    def _build_response(
        self,
        message: str,
        state: str,
        sub_state: Optional[str],
        auto_continue: bool = False,
        workflow: str = "returning_volunteer",
        handoff_event: Optional[Dict[str, Any]] = None,
        new_facts: Optional[Dict[str, Any]] = None,
    ) -> FulfillmentAgentTurnResponse:
        return FulfillmentAgentTurnResponse(
            assistant_message=message,
            auto_continue=auto_continue,
            handoff_event=handoff_event,
            workflow=workflow,
            state=state,
            sub_state=sub_state,
            new_facts=new_facts or {},
        )


# Singleton
fulfillment_agent_service = FulfillmentAgentService()
