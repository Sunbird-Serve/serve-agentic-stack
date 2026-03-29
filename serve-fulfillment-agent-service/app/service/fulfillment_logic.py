"""
SERVE Fulfillment Agent Service - Core Logic (L4)

Thin state machine that orchestrates the L4 tool-calling loop.
The LLM owns all branching logic. The state machine only enforces
terminal conditions (COMPLETE, HUMAN_REVIEW, PAUSED).

No per-stage handlers. No [ACTION:*] tag parsing.
"""
import json
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

logger = logging.getLogger(__name__)

_TERMINAL_STATES = {
    FulfillmentWorkflowState.COMPLETE.value,
    FulfillmentWorkflowState.HUMAN_REVIEW.value,
    FulfillmentWorkflowState.PAUSED.value,
}

_TERMINAL_FALLBACK_MESSAGES = {
    FulfillmentWorkflowState.COMPLETE.value: (
        "Aapki jagah confirm ho gayi hai. Coordinator jald hi aapse contact karenge."
    ),
    FulfillmentWorkflowState.HUMAN_REVIEW.value: (
        "Hamari team aapke liye sahi jagah dhundh rahi hai. Jald hi contact karenge."
    ),
    FulfillmentWorkflowState.PAUSED.value: (
        "Koi baat nahi! Aap jab chahein wapas aa sakte hain."
    ),
}


class FulfillmentAgentService:
    """
    L4 fulfillment agent state machine.
    Routes all non-terminal turns to the L4 loop.
    Watches tool_results for signal_outcome to transition to terminal states.
    """

    async def process_turn(self, request: FulfillmentAgentTurnRequest) -> FulfillmentAgentTurnResponse:
        session_id = str(request.session_id)
        stage = request.session_state.stage

        # ── Terminal state: return fallback, do not call LLM ─────────────────
        if stage in _TERMINAL_STATES:
            logger.info(f"Session {session_id} is in terminal state '{stage}' — returning fallback")
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES.get(stage, "Shukriya!"),
                state=stage,
                sub_state=request.session_state.sub_state,
                request=request,
            )

        # ── Load sub_state ────────────────────────────────────────────────────
        sub_state = _load_sub_state(request.session_state.sub_state)

        # Extract handoff from sub_state (populated on first turn from session metadata)
        handoff = sub_state.get("handoff") or {}

        # If handoff is empty, try to build it from session_state fields
        if not handoff and request.session_state.volunteer_id:
            handoff = {
                "volunteer_id": request.session_state.volunteer_id,
                "volunteer_name": request.session_state.volunteer_name or "",
                "continuity": "same",
            }
            sub_state["handoff"] = handoff

        # ── Build conversation history (bounded to last 20 messages) ──────────
        messages = list(request.conversation_history[-20:])

        # Append current user message if non-empty
        if request.user_message:
            messages.append({"role": "user", "content": request.user_message})

        # ── Build system prompt ───────────────────────────────────────────────
        system_prompt = llm_adapter.build_system_prompt(handoff)

        # ── Build tool executor ───────────────────────────────────────────────
        async def tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> Any:
            return await self._execute_tool(tool_name, tool_input, sub_state, session_id)

        # ── Run L4 loop ───────────────────────────────────────────────────────
        text, collected_tool_results = await llm_adapter.run_l4_loop(
            system_prompt=system_prompt,
            messages=messages,
            tool_executor=tool_executor,
            max_tool_iterations=10,
        )

        # ── Check for signal_outcome ──────────────────────────────────────────
        signal = collected_tool_results.get("signal_outcome")
        if signal:
            outcome = signal.get("outcome")
            return await self._handle_terminal(
                outcome=outcome,
                signal=signal,
                text=text,
                sub_state=sub_state,
                request=request,
                session_id=session_id,
            )

        # ── Loop exhausted without signal_outcome → force HUMAN_REVIEW ────────
        if not text:
            logger.warning(f"Session {session_id}: loop exhausted without signal_outcome — forcing HUMAN_REVIEW")
            sub_state["human_review_reason"] = "loop_exhausted"
            await domain_client.log_event(session_id, "fulfillment_human_review", {
                "reason": "loop_exhausted",
            })
            await domain_client.advance_state(
                session_id,
                FulfillmentWorkflowState.HUMAN_REVIEW.value,
                _dump_sub_state(sub_state),
            )
            return self._build_response(
                message=_TERMINAL_FALLBACK_MESSAGES[FulfillmentWorkflowState.HUMAN_REVIEW.value],
                state=FulfillmentWorkflowState.HUMAN_REVIEW.value,
                sub_state=_dump_sub_state(sub_state),
                request=request,
            )

        # ── Active turn: persist sub_state and return LLM response ───────────
        updated_sub_state = _dump_sub_state(sub_state)
        await domain_client.save_message(session_id, "assistant", text)
        await domain_client.advance_state(
            session_id,
            FulfillmentWorkflowState.ACTIVE.value,
            updated_sub_state,
        )

        return self._build_response(
            message=text,
            state=FulfillmentWorkflowState.ACTIVE.value,
            sub_state=updated_sub_state,
            request=request,
        )

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        sub_state: Dict[str, Any],
        session_id: str,
    ) -> Any:
        """Route tool calls to domain_client. Handle signal_outcome locally."""
        if tool_name == "signal_outcome":
            # Handled locally — store in sub_state, do NOT call MCP
            outcome = tool_input.get("outcome")
            need_id = tool_input.get("need_id")
            reason = tool_input.get("reason")
            if outcome == "nominated" and need_id:
                sub_state["nominated_need_id"] = need_id
            elif outcome == "human_review":
                sub_state["human_review_reason"] = reason or "unknown"
            return tool_input  # Return the signal payload as the result

        elif tool_name == "get_engagement_context":
            return await domain_client.get_engagement_context(tool_input["volunteer_id"])

        elif tool_name == "get_needs_for_entity":
            return await domain_client.get_needs_for_entity(tool_input["entity_id"])

        elif tool_name == "get_need_details":
            return await domain_client.get_need_details(tool_input["need_id"])

        elif tool_name == "resolve_school_context":
            return await domain_client.resolve_school_context(
                coordinator_id=tool_input.get("coordinator_id"),
                school_hint=tool_input.get("school_hint"),
            )

        elif tool_name == "nominate_volunteer_for_need":
            return await domain_client.nominate_volunteer_for_need(
                need_id=tool_input["need_id"],
                volunteer_id=tool_input["volunteer_id"],
            )

        elif tool_name == "get_nominations_for_need":
            return await domain_client.get_nominations_for_need(
                need_id=tool_input["need_id"],
                status=tool_input.get("status"),
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
        request: FulfillmentAgentTurnRequest,
        session_id: str,
    ) -> FulfillmentAgentTurnResponse:
        """Handle terminal state transitions from signal_outcome."""

        if outcome == "nominated":
            need_id = signal.get("need_id") or sub_state.get("nominated_need_id")
            sub_state["nominated_need_id"] = need_id
            await domain_client.log_event(session_id, "fulfillment_nominated", {
                "need_id": need_id,
                "volunteer_id": sub_state.get("handoff", {}).get("volunteer_id"),
            })
            new_state = FulfillmentWorkflowState.COMPLETE.value
            message = text or (
                "Shukriya! Coordinator review karenge aur jald hi aapse contact karenge."
            )

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
            logger.warning(f"Unknown signal_outcome outcome: {outcome} — defaulting to HUMAN_REVIEW")
            new_state = FulfillmentWorkflowState.HUMAN_REVIEW.value
            message = text or _TERMINAL_FALLBACK_MESSAGES[new_state]

        updated_sub_state = _dump_sub_state(sub_state)
        await domain_client.advance_state(session_id, new_state, updated_sub_state)
        if message:
            await domain_client.save_message(session_id, "assistant", message)

        return self._build_response(
            message=message,
            state=new_state,
            sub_state=updated_sub_state,
            request=request,
        )

    def _build_response(
        self,
        message: str,
        state: str,
        sub_state: Optional[str],
        request: FulfillmentAgentTurnRequest,
    ) -> FulfillmentAgentTurnResponse:
        return FulfillmentAgentTurnResponse(
            assistant_message=message,
            state=state,
            sub_state=sub_state,
        )


# Singleton
fulfillment_agent_service = FulfillmentAgentService()
