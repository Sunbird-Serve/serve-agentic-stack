"""
SERVE Engagement Agent Service - Core Logic

MVP engagement flow for recommended-but-not-utilised or returning volunteers:
1. Re-engage and confirm whether they want to continue
2. Capture continuity preferences (same school / same slot / alternatives)
3. Hand off ready volunteers to fulfillment
4. Pause or human-review the rest
"""
import logging
import re
from typing import Any, Dict, List, Optional

from app.schemas.engagement_schemas import (
    EngagementWorkflowState,
    EngagementAgentTurnRequest,
    EngagementAgentTurnResponse,
    FulfillmentHandoffPayload,
    _dump_sub_state,
    _load_sub_state,
)
from app.clients.domain_client import domain_client

logger = logging.getLogger(__name__)

_TERMINAL_MESSAGES = {
    EngagementWorkflowState.HUMAN_REVIEW.value: (
        "Thanks for sharing honestly. We'll update your preference and a team member can follow up if needed."
    ),
    EngagementWorkflowState.PAUSED.value: (
        "No problem. We'll reconnect later, and you can come back whenever you're ready."
    ),
}

_DEFER_PATTERNS = [
    r"\bnot now\b",
    r"\bnot available\b",
    r"\blater\b",
    r"\bmaybe later\b",
    r"\bnot sure\b",
    r"\bbusy\b",
    r"\bunavailable\b",
    r"\bcurrently unavailable\b",
    r"\bnext term\b",
    r"\bnext year\b",
    r"\babhi nahi\b",
    r"\bbaad mein\b",
]

_DECLINE_PATTERNS = [
    r"\bno\b",
    r"\bnope\b",
    r"\bnot interested\b",
    r"\bdon't contact\b",
    r"\bdo not contact\b",
    r"\bopt out\b",
    r"\bstop\b",
    r"\bcannot continue\b",
    r"\bcan't continue\b",
    r"\bnahi\b",
    r"\bnahin\b",
]

_CONTINUE_PATTERNS = [
    r"\byes\b",
    r"\bhaan\b",
    r"\bhan\b",
    r"\bcontinue\b",
    r"\bready\b",
    r"\binterested\b",
    r"\bavailable\b",
    r"\bstart\b",
    r"\bkeep going\b",
]

_SAME_SCHOOL_PATTERNS = [
    r"\bsame school\b",
    r"\bsame place\b",
    r"\bsame as before\b",
    r"\busi school\b",
]

_FLEX_SCHOOL_PATTERNS = [
    r"\bdifferent school\b",
    r"\bany school\b",
    r"\bflexible school\b",
    r"\bopen to another school\b",
    r"\bopen to a different school\b",
    r"\bkahi bhi\b",
]

_SAME_SLOT_PATTERNS = [
    r"\bsame slot\b",
    r"\bsame time\b",
    r"\bsame timing\b",
    r"\bsame schedule\b",
    r"\bsame days\b",
    r"\bussi timing\b",
]

_FLEX_SLOT_PATTERNS = [
    r"\bflexible slot\b",
    r"\bflexible timing\b",
    r"\bany time\b",
    r"\bdifferent time\b",
    r"\bchange time\b",
    r"\bopen timing\b",
    r"\bflexible on timing\b",
]

_ALTERNATIVE_PATTERNS = [
    r"\bopen to alternatives\b",
    r"\bopen to options\b",
    r"\bfully flexible\b",
    r"\bany option\b",
]


class EngagementAgentService:
    """MVP engagement state machine for volunteer continuity."""

    async def process_turn(self, request: EngagementAgentTurnRequest) -> EngagementAgentTurnResponse:
        stage = request.session_state.stage
        sub_state = _load_sub_state(request.session_state.sub_state)

        await self._ensure_context_loaded(request, sub_state)

        if stage == EngagementWorkflowState.HUMAN_REVIEW.value:
            return self._build_response(
                message=_TERMINAL_MESSAGES[EngagementWorkflowState.HUMAN_REVIEW.value],
                next_state=EngagementWorkflowState.HUMAN_REVIEW.value,
                sub_state=sub_state,
            )

        #TODO: Consider moving this out of this function
        dispatch = {
            EngagementWorkflowState.RE_ENGAGING.value: self._handle_re_engaging,
            EngagementWorkflowState.PROFILE_REFRESH.value: self._handle_profile_refresh,
            EngagementWorkflowState.MATCHING_READY.value: self._handle_matching_ready,
            EngagementWorkflowState.PAUSED.value: self._handle_paused,
        }

        handler = dispatch.get(stage, self._handle_fallback)
        return await handler(request, sub_state)

    async def _handle_re_engaging(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        signals = self._extract_signals(request.user_message)
        self._merge_signals(sub_state, signals)
        await self._persist_signals(str(request.session_id), sub_state)

        decision = sub_state.get("continue_decision")
        if decision == "decline":
            return await self._handle_decline(request, sub_state)
        if decision == "defer":
            return await self._handle_defer(request, sub_state)
        if decision == "continue":
            missing = self._get_missing_preference_fields(sub_state)
            if missing:
                return self._build_response(
                    message=self._build_preference_question(sub_state),
                    next_state=EngagementWorkflowState.PROFILE_REFRESH.value,
                    sub_state=sub_state,
                    completion_status="collecting_preferences",
                    confirmed_fields=self._confirmed_fields(sub_state),
                )
            return await self._build_fulfillment_handoff_response(request, sub_state)

        return self._build_response(
            message=self._build_reengagement_prompt(request, sub_state),
            next_state=EngagementWorkflowState.RE_ENGAGING.value,
            sub_state=sub_state,
            completion_status="awaiting_interest",
            confirmed_fields=self._confirmed_fields(sub_state),
        )

    async def _handle_profile_refresh(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        signals = self._extract_signals(request.user_message)
        self._merge_signals(sub_state, signals)
        await self._persist_signals(str(request.session_id), sub_state)

        decision = sub_state.get("continue_decision")
        if decision == "decline":
            return await self._handle_decline(request, sub_state)
        if decision == "defer":
            return await self._handle_defer(request, sub_state)
        if decision != "continue":
            return self._build_response(
                message=self._build_reengagement_prompt(request, sub_state),
                next_state=EngagementWorkflowState.RE_ENGAGING.value,
                sub_state=sub_state,
                completion_status="awaiting_interest",
                confirmed_fields=self._confirmed_fields(sub_state),
            )

        missing = self._get_missing_preference_fields(sub_state)
        if missing:
            return self._build_response(
                message=self._build_preference_question(sub_state),
                next_state=EngagementWorkflowState.PROFILE_REFRESH.value,
                sub_state=sub_state,
                completion_status="collecting_preferences",
                confirmed_fields=self._confirmed_fields(sub_state),
            )

        return await self._build_fulfillment_handoff_response(request, sub_state)

    async def _handle_matching_ready(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        if sub_state.get("handoff"):
            return await self._build_fulfillment_handoff_response(request, sub_state)
        return await self._handle_profile_refresh(request, sub_state)

    async def _handle_paused(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        if request.user_message.strip():
            return await self._handle_re_engaging(request, sub_state)
        return self._build_response(
            message=_TERMINAL_MESSAGES[EngagementWorkflowState.PAUSED.value],
            next_state=EngagementWorkflowState.PAUSED.value,
            sub_state=sub_state,
            completion_status="paused",
            confirmed_fields=self._confirmed_fields(sub_state),
        )

    async def _handle_fallback(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        logger.warning("Unknown engagement stage '%s' — falling back to re_engaging", request.session_state.stage)
        return await self._handle_re_engaging(request, sub_state)

    async def _handle_decline(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        sub_state["human_review_reason"] = "volunteer_declined"
        await self._persist_signals(str(request.session_id), sub_state)
        await domain_client.engagement_update_volunteer_status(
            str(request.session_id),
            volunteer_status="opt_out",
            reason="volunteer_declined",
            signals=self._confirmed_fields(sub_state),
        )
        await self._write_summary(
            session_id=str(request.session_id),
            volunteer_id=request.session_state.volunteer_id,
            sub_state=sub_state,
            outcome="declined",
        )
        return self._build_response(
            message=(
                "Thank you for letting us know. We won't push any further right now. "
                "If you'd like to come back later, we'd be happy to reconnect."
            ),
            next_state=EngagementWorkflowState.HUMAN_REVIEW.value,
            sub_state=sub_state,
            completion_status="human_review",
            confirmed_fields=self._confirmed_fields(sub_state),
        )

    async def _handle_defer(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        await self._persist_signals(str(request.session_id), sub_state)
        await domain_client.engagement_update_volunteer_status(
            str(request.session_id),
            volunteer_status="pause_outreach",
            reason="volunteer_deferred",
            signals=self._confirmed_fields(sub_state),
        )
        await self._write_summary(
            session_id=str(request.session_id),
            volunteer_id=request.session_state.volunteer_id,
            sub_state=sub_state,
            outcome="deferred",
        )
        return self._build_response(
            message=(
                "Absolutely. We can reconnect later when your timing is better. "
                "Just message us whenever you're ready."
            ),
            next_state=EngagementWorkflowState.PAUSED.value,
            sub_state=sub_state,
            completion_status="paused",
            confirmed_fields=self._confirmed_fields(sub_state),
        )

    async def _build_fulfillment_handoff_response(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> EngagementAgentTurnResponse:
        await self._persist_signals(str(request.session_id), sub_state)
        handoff_result = await domain_client.engagement_prepare_fulfillment_handoff(
            str(request.session_id),
            signals=self._confirmed_fields(sub_state),
        )
        updated_sub_state = handoff_result.get("sub_state") if isinstance(handoff_result, dict) else None
        if isinstance(updated_sub_state, dict):
            sub_state.update(updated_sub_state)
        payload = (
            handoff_result.get("handoff_payload")
            or sub_state.get("handoff")
            or self._build_fulfillment_payload(request, sub_state)
        )
        if not payload:
            sub_state["human_review_reason"] = "missing_handoff_context"
            await self._persist_signals(str(request.session_id), sub_state)
            await domain_client.engagement_update_volunteer_status(
                str(request.session_id),
                volunteer_status="human_review",
                reason="missing_handoff_context",
                signals=self._confirmed_fields(sub_state),
            )
            await self._write_summary(
                session_id=str(request.session_id),
                volunteer_id=request.session_state.volunteer_id,
                sub_state=sub_state,
                outcome="human_review",
            )
            return self._build_response(
                message=(
                    "Thanks. I have your preference, but I need a teammate to check the details before moving ahead."
                ),
                next_state=EngagementWorkflowState.HUMAN_REVIEW.value,
                sub_state=sub_state,
                completion_status="human_review",
                confirmed_fields=self._confirmed_fields(sub_state),
            )

        sub_state["handoff"] = payload
        await self._persist_signals(str(request.session_id), sub_state)
        await domain_client.engagement_update_volunteer_status(
            str(request.session_id),
            volunteer_status="opportunity_readiness",
            reason="ready_for_fulfillment",
            signals=self._confirmed_fields(sub_state),
        )
        await self._write_summary(
            session_id=str(request.session_id),
            volunteer_id=request.session_state.volunteer_id,
            sub_state=sub_state,
            outcome="handoff_to_fulfillment",
        )

        return self._build_response(
            message=(
                "Perfect. I’ve noted your preference and I’ll now check for the best teaching continuation for you."
            ),
            next_state="active",
            sub_state=sub_state,
            completion_status="handoff_ready",
            confirmed_fields=self._confirmed_fields(sub_state),
            handoff_event={
                "session_id": request.session_id,
                "from_agent": "engagement",
                "to_agent": "fulfillment",
                "handoff_type": "agent_transition",
                "payload": payload,
                "reason": "Volunteer confirmed continuation preferences",
            },
        )

    async def _ensure_context_loaded(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> None:
        if sub_state.get("engagement_context"):
            return

        volunteer_id = request.session_state.volunteer_id
        if not volunteer_id:
            return

        context = await domain_client.get_engagement_context(str(volunteer_id))
        if context.get("status") == "success":
            sub_state["engagement_context"] = context
        else:
            logger.warning("Failed to load engagement context for volunteer %s: %s", volunteer_id, context)

    def _extract_signals(self, message: str) -> Dict[str, Any]:
        text = self._normalise(message)
        if not text:
            return {}

        decision = None
        if self._matches_any(text, _DEFER_PATTERNS):
            decision = "defer"
        elif self._matches_any(text, _DECLINE_PATTERNS):
            decision = "decline"
        elif self._matches_any(text, _CONTINUE_PATTERNS):
            decision = "continue"

        same_school = True if self._matches_any(text, _SAME_SCHOOL_PATTERNS) else None
        if same_school is None and self._matches_any(text, _FLEX_SCHOOL_PATTERNS):
            same_school = False

        same_slot = True if self._matches_any(text, _SAME_SLOT_PATTERNS) else None
        if same_slot is None and self._matches_any(text, _FLEX_SLOT_PATTERNS):
            same_slot = False

        open_to_alternatives = True if self._matches_any(text, _ALTERNATIVE_PATTERNS) else None
        if open_to_alternatives:
            if same_school is None:
                same_school = False
            if same_slot is None:
                same_slot = False

        if decision is None and any(v is not None for v in (same_school, same_slot, open_to_alternatives)):
            decision = "continue"

        return {
            "continue_decision": decision,
            "same_school": same_school,
            "same_slot": same_slot,
            "open_to_alternatives": open_to_alternatives,
        }

    def _merge_signals(self, sub_state: Dict[str, Any], signals: Dict[str, Any]) -> None:
        for key in ("continue_decision", "same_school", "same_slot", "open_to_alternatives"):
            value = signals.get(key)
            if value is not None:
                sub_state[key] = value

        if sub_state.get("same_school") is True:
            sub_state["continuity"] = "same"
        elif sub_state.get("same_school") is False or sub_state.get("open_to_alternatives") is True:
            sub_state["continuity"] = "different"

        sub_state["preference_notes"] = self._build_preference_notes(sub_state)

    def _build_preference_notes(self, sub_state: Dict[str, Any]) -> str:
        context = sub_state.get("engagement_context") or {}
        history = context.get("fulfillment_history") or []
        latest = history[0] if history else {}

        notes: List[str] = []
        school_name = latest.get("school_name")
        schedule = latest.get("schedule")
        subjects = latest.get("subjects") or []
        grades = latest.get("grade_levels") or []

        if sub_state.get("same_school") is True and school_name:
            notes.append(f"Prefer same school as before: {school_name}.")
        elif sub_state.get("same_school") is False:
            notes.append("Open to a different school if needed.")

        if sub_state.get("same_slot") is True and schedule:
            notes.append(f"Prefer same schedule as before: {schedule}.")
        elif sub_state.get("same_slot") is False:
            notes.append("Flexible on time slot.")

        if sub_state.get("open_to_alternatives") is True:
            notes.append("Open to alternatives if the previous match is unavailable.")

        if subjects:
            notes.append(f"Recent teaching subjects: {', '.join(subjects)}.")
        if grades:
            notes.append(f"Recent grade levels: {', '.join(str(g) for g in grades)}.")

        return " ".join(notes).strip()

    def _build_fulfillment_payload(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        volunteer_id = request.session_state.volunteer_id
        if not volunteer_id:
            return None

        context = sub_state.get("engagement_context") or {}
        history = context.get("fulfillment_history") or []
        latest = history[0] if history else {}

        payload = FulfillmentHandoffPayload(
            volunteer_id=str(volunteer_id),
            volunteer_name=self._resolve_volunteer_name(request, context),
            continuity=sub_state.get("continuity") or "different",
            preferred_need_id=latest.get("need_id") if sub_state.get("continuity") == "same" else None,
            preferred_school_id=None,
            preference_notes=sub_state.get("preference_notes") or None,
            fulfillment_history=history,
        )
        return payload.model_dump(mode="json")

    def _build_reengagement_prompt(
        self,
        request: EngagementAgentTurnRequest,
        sub_state: Dict[str, Any],
    ) -> str:
        context = sub_state.get("engagement_context") or {}
        history = context.get("fulfillment_history") or []
        latest = history[0] if history else {}
        name = self._resolve_volunteer_name(request, context)

        if latest.get("school_name"):
            return (
                f"Welcome back, {name}! Last time you supported {latest['school_name']}. "
                "Would you like to continue this year? We can try the same school and timing, or look at alternatives."
            )
        return (
            f"Welcome back, {name}! Would you like to continue volunteering this year? "
            "If yes, we can try the same school and timing as before or look at alternatives."
        )

    def _build_preference_question(self, sub_state: Dict[str, Any]) -> str:
        missing = self._get_missing_preference_fields(sub_state)
        if "school_preference" in missing and "slot_preference" in missing:
            return (
                "Would you prefer the same school and same time slot as before, "
                "or are you open to different options?"
            )
        if "school_preference" in missing:
            return "Would you like the same school as before, or are you open to a different school?"
        return "Should we try for the same time slot as before, or are you flexible on timing?"

    def _get_missing_preference_fields(self, sub_state: Dict[str, Any]) -> List[str]:
        missing: List[str] = []
        if sub_state.get("continue_decision") != "continue":
            return missing
        if sub_state.get("same_school") is None:
            missing.append("school_preference")
        if sub_state.get("same_slot") is None:
            missing.append("slot_preference")
        return missing

    def _confirmed_fields(self, sub_state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "continue_decision": sub_state.get("continue_decision"),
            "same_school": sub_state.get("same_school"),
            "same_slot": sub_state.get("same_slot"),
            "open_to_alternatives": sub_state.get("open_to_alternatives"),
            "continuity": sub_state.get("continuity"),
            "preference_notes": sub_state.get("preference_notes"),
        }

    async def _persist_signals(self, session_id: str, sub_state: Dict[str, Any]) -> None:
        result = await domain_client.engagement_save_confirmed_signals(
            session_id,
            self._confirmed_fields(sub_state),
        )
        updated = result.get("sub_state") if isinstance(result, dict) else None
        if isinstance(updated, dict):
            sub_state.update(updated)

    async def _write_summary(
        self,
        session_id: str,
        volunteer_id: Optional[str],
        sub_state: Dict[str, Any],
        outcome: str,
    ) -> None:
        summary_text = self._build_summary_text(sub_state, outcome)
        key_facts = [
            f"Outcome: {outcome}",
            f"Continue decision: {sub_state.get('continue_decision')}",
            f"Continuity: {sub_state.get('continuity')}",
            f"Same school: {sub_state.get('same_school')}",
            f"Same slot: {sub_state.get('same_slot')}",
        ]
        await domain_client.save_memory_summary(
            session_id=session_id,
            summary_text=summary_text,
            key_facts=[fact for fact in key_facts if not fact.endswith("None")],
            volunteer_id=volunteer_id,
        )

    def _build_summary_text(self, sub_state: Dict[str, Any], outcome: str) -> str:
        parts = [f"Engagement outcome: {outcome}."]
        if sub_state.get("continue_decision"):
            parts.append(f"Volunteer decision: {sub_state['continue_decision']}.")
        if sub_state.get("continuity"):
            parts.append(f"Continuity preference: {sub_state['continuity']}.")
        if sub_state.get("preference_notes"):
            parts.append(sub_state["preference_notes"])
        if sub_state.get("human_review_reason"):
            parts.append(f"Human review reason: {sub_state['human_review_reason']}.")
        return " ".join(parts)

    def _build_response(
        self,
        message: str,
        next_state: str,
        sub_state: Dict[str, Any],
        completion_status: Optional[str] = None,
        confirmed_fields: Optional[Dict[str, Any]] = None,
        handoff_event: Optional[Dict[str, Any]] = None,
    ) -> EngagementAgentTurnResponse:
        return EngagementAgentTurnResponse(
            assistant_message=message,
            state=next_state,
            sub_state=_dump_sub_state(sub_state),
            completion_status=completion_status,
            confirmed_fields=confirmed_fields or {},
            handoff_event=handoff_event,
        )

    def _resolve_volunteer_name(
        self,
        request: EngagementAgentTurnRequest,
        context: Dict[str, Any],
    ) -> str:
        if request.session_state.volunteer_name:
            return request.session_state.volunteer_name
        profile = context.get("volunteer_profile") or {}
        return profile.get("full_name") or profile.get("first_name") or "Volunteer"

    def _normalise(self, message: str) -> str:
        return re.sub(r"\s+", " ", (message or "").strip().lower())

    def _matches_any(self, text: str, patterns: List[str]) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)


# Singleton
engagement_agent_service = EngagementAgentService()
