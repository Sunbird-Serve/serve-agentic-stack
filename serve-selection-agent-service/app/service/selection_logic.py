"""
SERVE Selection Agent Service - Core Evaluation Logic

Selection is a lightweight post-onboarding evaluator.
It reads the onboarding handoff + MCP profile state, classifies the profile,
logs the outcome, and returns a concise next-step response.
"""
import logging
from typing import Any, Dict, List

from app.clients.domain_client import domain_client
from app.schemas.selection_schemas import (
    AgentTurnRequest,
    AgentTurnResponse,
    AgentType,
    EventType,
    SelectionEvaluateRequest,
    SelectionEvaluateResponse,
    SelectionOutcome,
    TelemetryEvent,
    VolunteerProfile,
    WorkflowType,
    extract_handoff_payload,
)

logger = logging.getLogger(__name__)


class SelectionAgentService:
    """Evaluate completed onboarding profiles and recommend the next internal action."""

    async def process_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        evaluation_request = await self._build_evaluation_request(request)
        evaluation = await self.evaluate(evaluation_request)

        await domain_client.log_event(
            str(request.session_id),
            "selection_evaluated",
            {
                "outcome": evaluation.outcome.value,
                "confidence": evaluation.confidence,
                "reason": evaluation.reason,
                "flags": evaluation.flags,
                "recommended_actions": evaluation.recommended_actions,
            },
        )

        telemetry_events = [
            TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.AGENT_RESPONSE,
                agent=AgentType.SELECTION,
                data={
                    "outcome": evaluation.outcome.value,
                    "confidence": evaluation.confidence,
                },
            )
        ]

        return AgentTurnResponse(
            assistant_message=self._build_assistant_message(request, evaluation),
            active_agent=AgentType.SELECTION,
            workflow=WorkflowType(request.session_state.workflow),
            state=request.session_state.stage,
            completion_status=self._completion_status(evaluation.outcome),
            confirmed_fields={
                "selection_outcome": evaluation.outcome.value,
                "selection_confidence": evaluation.confidence,
                "selection_reason": evaluation.reason,
            },
            missing_fields=evaluation.evaluation_details.get("missing_fields", []),
            telemetry_events=telemetry_events,
        )

    async def evaluate(self, request: SelectionEvaluateRequest) -> SelectionEvaluateResponse:
        """Rule-based profile evaluation using MCP readiness + onboarding context."""
        profile = request.profile
        metadata = request.metadata or {}
        missing_fields = list(metadata.get("missing_fields", []))
        readiness_recommendation = metadata.get("readiness_recommendation")
        readiness_reason = metadata.get("readiness_reason")
        ready_for_selection = bool(metadata.get("ready_for_selection"))

        flags: List[str] = []
        recommended_actions: List[str] = []

        if metadata.get("profile_load_error"):
            flags.append("profile_load_error")
        if metadata.get("memory_load_error"):
            flags.append("memory_load_error")
        if not (profile.email or profile.phone):
            flags.append("missing_primary_contact")
        if not profile.skills:
            flags.append("missing_skills")
        if not profile.availability:
            flags.append("missing_availability")
        if not profile.full_name:
            flags.append("missing_name")

        profile_strength = 0
        if profile.full_name:
            profile_strength += 1
        if profile.email or profile.phone:
            profile_strength += 1
        if profile.skills:
            profile_strength += 1
        if profile.availability:
            profile_strength += 1
        if profile.interests:
            profile_strength += 1
        if profile.languages:
            profile_strength += 1

        if ready_for_selection:
            outcome = SelectionOutcome.RECOMMEND
            confidence = min(0.7 + (profile_strength * 0.04), 0.95)
            reason = readiness_reason or "Volunteer profile is complete and ready for the next step."
            recommended_actions = ["queue_for_matching_review", "notify_ops_ready"]
        elif metadata.get("profile_load_error") or len(missing_fields) >= 3:
            outcome = SelectionOutcome.NOT_RECOMMEND
            confidence = 0.8
            reason = readiness_reason or "Profile is too incomplete to recommend automatically."
            recommended_actions = ["manual_review_profile", "request_profile_completion"]
        else:
            outcome = SelectionOutcome.HOLD
            confidence = 0.65
            reason = readiness_reason or "Profile needs a small amount of follow-up before recommending."
            recommended_actions = ["collect_missing_profile_fields", "re-run_selection"]

        evaluation_details = {
            "missing_fields": missing_fields,
            "readiness_recommendation": readiness_recommendation,
            "profile_strength": profile_strength,
            "onboarding_summary_available": bool(request.onboarding_summary),
            "key_facts_count": len(request.key_facts),
        }

        return SelectionEvaluateResponse(
            session_id=request.session_id,
            volunteer_id=request.volunteer_id,
            outcome=outcome,
            confidence=round(confidence, 2),
            reason=reason,
            flags=flags,
            recommended_actions=recommended_actions,
            evaluation_details=evaluation_details,
        )

    async def _build_evaluation_request(self, request: AgentTurnRequest) -> SelectionEvaluateRequest:
        session_id = str(request.session_id)
        handoff = extract_handoff_payload(request.session_state.sub_state)

        profile_result = await domain_client.get_volunteer_profile(session_id)
        readiness_result = await domain_client.evaluate_readiness(session_id)
        memory_result = await domain_client.get_memory_summary(session_id)

        profile_data = profile_result.get("profile", {}) if isinstance(profile_result, dict) else {}
        confirmed_fields = handoff.get("confirmed_fields", {})
        merged_profile = self._merge_profile(profile_data, confirmed_fields)

        memory_data = memory_result.get("data") if isinstance(memory_result, dict) else None
        onboarding_summary = handoff.get("memory_summary") or (memory_data or {}).get("summary_text")
        key_facts = handoff.get("key_facts") or (memory_data or {}).get("key_facts", [])

        metadata = {
            "ready_for_selection": readiness_result.get("ready_for_selection", False),
            "missing_fields": readiness_result.get("missing_fields", []),
            "readiness_recommendation": readiness_result.get("recommendation"),
            "readiness_reason": readiness_result.get("reason"),
            "profile_load_error": profile_result.get("status") == "error",
            "memory_load_error": memory_result.get("status") == "error",
            "handoff_present": bool(handoff),
        }

        volunteer_id = (
            str(request.session_state.volunteer_id)
            if request.session_state.volunteer_id
            else handoff.get("volunteer_id")
            or profile_data.get("volunteer_id")
        )

        return SelectionEvaluateRequest(
            session_id=request.session_id,
            volunteer_id=volunteer_id,
            profile=VolunteerProfile(**merged_profile),
            onboarding_summary=onboarding_summary,
            key_facts=key_facts,
            metadata=metadata,
        )

    def _merge_profile(self, profile_data: Dict[str, Any], confirmed_fields: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(profile_data or {})
        for key, value in (confirmed_fields or {}).items():
            if value is not None:
                merged[key] = value
        return {
            "volunteer_id": merged.get("volunteer_id"),
            "full_name": merged.get("full_name"),
            "first_name": merged.get("first_name"),
            "email": merged.get("email"),
            "phone": merged.get("phone"),
            "location": merged.get("location"),
            "skills": merged.get("skills") or [],
            "interests": merged.get("interests") or [],
            "availability": merged.get("availability"),
            "languages": merged.get("languages") or [],
            "motivation": merged.get("motivation"),
            "qualification": merged.get("qualification"),
            "years_of_experience": str(merged.get("years_of_experience")) if merged.get("years_of_experience") is not None else None,
            "employment_status": merged.get("employment_status"),
        }

    def _build_assistant_message(
        self,
        request: AgentTurnRequest,
        evaluation: SelectionEvaluateResponse,
    ) -> str:
        if request.user_message == "__handoff__":
            if evaluation.outcome == SelectionOutcome.RECOMMEND:
                return (
                    "Thanks, your profile looks complete. We're reviewing it for the next step and "
                    "will move you forward shortly."
                )
            if evaluation.outcome == SelectionOutcome.HOLD:
                return (
                    "Thanks, your profile is with us. We may need one small follow-up before moving you ahead."
                )
            return (
                "Thanks for completing your profile. Our team will review it and follow up on the best next step."
            )

        if evaluation.outcome == SelectionOutcome.RECOMMEND:
            return "Your profile looks strong for the next step. We’re moving it forward for matching review."
        if evaluation.outcome == SelectionOutcome.HOLD:
            return "Your profile is under review. We may come back with a small follow-up if needed."
        return "Your profile needs a manual review before we can move it ahead."

    def _completion_status(self, outcome: SelectionOutcome) -> str:
        if outcome == SelectionOutcome.RECOMMEND:
            return "recommended"
        if outcome == SelectionOutcome.HOLD:
            return "hold"
        return "not_recommended"


selection_agent_service = SelectionAgentService()
