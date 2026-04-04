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

        # ── Terminal state guard ──────────────────────────────────────────────
        if stage in _TERMINAL_STATES:
            logger.info(f"Session {session_id} in terminal state '{stage}'")
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES.get(stage, "Shukriya!"),
                state=stage,
                sub_state=request.session_state.sub_state,
            )

        # ── Load sub_state ────────────────────────────────────────────────────
        sub_state = _load_sub_state(request.session_state.sub_state)
        handoff = sub_state.get("handoff") or {}

        if not handoff and request.session_state.volunteer_id:
            handoff = {
                "volunteer_id": request.session_state.volunteer_id,
                "volunteer_name": request.session_state.volunteer_name or "",
                "continuity": "same",
            }
            sub_state["handoff"] = handoff

        # ── Phase 1: find match (Python, no LLM) — only on first turn ────────
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

        # Build messages — skip synthetic handoff trigger
        messages = list(request.conversation_history[-20:])
        if request.user_message and request.user_message != "__handoff__":
            messages.append({"role": "user", "content": request.user_message})
        elif request.user_message == "__handoff__" and not messages:
            messages.append({"role": "user", "content": "Please find me a teaching opportunity."})

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
            )

        # ── Active turn ───────────────────────────────────────────────────────
        updated = _dump_sub_state(sub_state)
        await domain_client.save_message(session_id, "assistant", text)
        await domain_client.advance_state(session_id, FulfillmentWorkflowState.ACTIVE.value, updated)
        return self._build_response(
            message=text,
            state=FulfillmentWorkflowState.ACTIVE.value,
            sub_state=updated,
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
            elif outcome == "human_review":
                sub_state["human_review_reason"] = tool_input.get("reason", "unknown")
            return tool_input

        elif tool_name == "get_more_needs":
            hint = tool_input.get("hint", "")
            handoff = sub_state.get("handoff", {})
            # Re-run matcher with relaxed constraints using hint as preference override
            relaxed_handoff = {
                **handoff,
                "preference_notes": hint,
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
            return await domain_client.nominate_volunteer_for_need(
                need_id=tool_input["need_id"],
                volunteer_id=tool_input["volunteer_id"],
            )

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
    ) -> FulfillmentAgentTurnResponse:
        if outcome == "nominated":
            need_id = signal.get("need_id") or sub_state.get("nominated_need_id")
            sub_state["nominated_need_id"] = need_id
            await domain_client.log_event(session_id, "fulfillment_nominated", {
                "need_id": need_id,
                "volunteer_id": sub_state.get("handoff", {}).get("volunteer_id"),
            })
            new_state = FulfillmentWorkflowState.COMPLETE.value
            message = text or "Shukriya! Coordinator review karenge aur jald hi aapse contact karenge."

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

        return self._build_response(message=message, state=new_state, sub_state=updated)

    def _build_response(
        self,
        message: str,
        state: str,
        sub_state: Optional[str],
    ) -> FulfillmentAgentTurnResponse:
        return FulfillmentAgentTurnResponse(
            assistant_message=message,
            state=state,
            sub_state=sub_state,
        )


# Singleton
fulfillment_agent_service = FulfillmentAgentService()
