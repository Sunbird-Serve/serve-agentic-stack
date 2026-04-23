"""
SERVE Selection Agent Service - Core Evaluation Logic

Selection is the conversational assessment step after onboarding.
It asks a small set of focused questions, extracts readiness signals,
decides the volunteer's immediate outcome, and hands suitable cases to
engagement for downstream preference capture.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.clients.domain_client import domain_client
from app.schemas.selection_schemas import (
    AgentTurnRequest,
    AgentTurnResponse,
    AgentType,
    EventType,
    SelectionEvaluateRequest,
    SelectionEvaluateResponse,
    SelectionOutcome,
    SelectionWorkflowState,
    TelemetryEvent,
    VolunteerProfile,
    WorkflowType,
    dump_selection_sub_state,
    extract_handoff_payload,
    load_selection_sub_state,
)
from app.service.llm_adapter import llm_adapter


QUESTION_ORDER = [
    "motivation_alignment",
    "continuity_intent",
    "language_comfort",
    "availability_realism",
    "readiness",
    "blockers",
]

QUESTION_PROMPTS = {
    "motivation_alignment": (
        "What is motivating you to volunteer with eVidyaloka at this point?"
    ),
    "continuity_intent": (
        "How do you see volunteering fitting into your routine over the next few months?"
    ),
    "language_comfort": (
        "How comfortable are you communicating in English and Hindi while teaching?"
    ),
    "availability_realism": (
        "What kind of time can you realistically commit each week right now?"
    ),
    "readiness": (
        "If a suitable opportunity opens soon, would you be ready to start, or would you need some more time?"
    ),
    "blockers": (
        "Is there anything that could make it hard for you to continue consistently right now?"
    ),
}

PAUSE_PATTERNS = [r"\blater\b", r"\bnot now\b", r"\bpause\b", r"\bbusy\b", r"\bcontinue later\b"]
POSITIVE_MOTIVATION = ["teach", "children", "students", "education", "give back", "impact", "volunteer"]
STRONG_COMMITMENT = ["regular", "consistent", "weekly", "commit", "committed", "long term", "few months"]
LOW_COMMITMENT = ["try", "maybe", "not sure", "depends", "occasionally", "if possible"]
LANGUAGE_COMFORT = ["comfortable", "fluent", "can manage", "good with", "okay with"]
LANGUAGE_LIMITED = ["not comfortable", "weak", "struggle", "can't speak", "cannot speak"]
READY_NOW = ["immediately", "right away", "soon", "can start", "ready now", "next week", "this week"]
READY_LATER = ["later", "next month", "after", "once", "in a few weeks", "after exams"]
HIGH_RISK = ["legal", "safety", "abuse", "harassment", "medical emergency"]
BLOCKER_TERMS = ["busy", "travel", "exam", "job change", "shift", "health", "unstable", "uncertain"]


def _matches_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _normalise_text(text: str) -> str:
    return (text or "").strip().lower()


def _score_communication_clarity(message: str) -> str:
    lowered = _normalise_text(message)
    words = [w for w in re.split(r"\s+", lowered) if w]
    if len(words) >= 8 and not any(term in lowered for term in ["maybe", "not sure", "depends"]):
        return "clear"
    if len(words) >= 4:
        return "mixed"
    return "unclear"


def _extract_languages(message: str) -> List[str]:
    lowered = _normalise_text(message)
    languages: List[str] = []
    if "english" in lowered:
        languages.append("english")
    if "hindi" in lowered or "hinglish" in lowered:
        languages.append("hindi")
    return languages


def _extract_selection_signals(sub_state: Dict[str, Any], message: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    lowered = _normalise_text(message)
    signals = dict(sub_state.get("signals") or {})
    notes = dict(sub_state.get("notes") or {})

    signals["communication_clarity"] = _score_communication_clarity(message)

    if signals.get("motivation_alignment") is None:
        if any(term in lowered for term in POSITIVE_MOTIVATION):
            signals["motivation_alignment"] = "strong"
            notes["motivation"] = message.strip()
        elif any(term in lowered for term in ["curious", "explore", "checking"]):
            signals["motivation_alignment"] = "moderate"
            notes["motivation"] = message.strip()

    if signals.get("continuity_intent") is None:
        if any(term in lowered for term in STRONG_COMMITMENT):
            signals["continuity_intent"] = "committed"
        elif any(term in lowered for term in LOW_COMMITMENT):
            signals["continuity_intent"] = "uncertain"

    if signals.get("language_comfort") is None and any(term in lowered for term in ["english", "hindi", "language", "communicat"]):
        if any(term in lowered for term in LANGUAGE_LIMITED):
            signals["language_comfort"] = "limited"
        elif any(term in lowered for term in LANGUAGE_COMFORT):
            signals["language_comfort"] = "comfortable"
        notes["language_notes"] = message.strip()

    if signals.get("availability_realism") is None:
        if re.search(r"\b\d+\s*(hours?|hrs?)\b", lowered) or any(
            token in lowered for token in ["weekly", "weekdays", "weekends", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
        ):
            signals["availability_realism"] = "realistic"
            notes["availability"] = message.strip()
        elif any(term in lowered for term in ["not sure", "depends", "whenever"]):
            signals["availability_realism"] = "unclear"
            notes["availability"] = message.strip()

    if signals.get("readiness") is None:
        if any(term in lowered for term in READY_NOW):
            signals["readiness"] = "ready_now"
        elif any(term in lowered for term in READY_LATER):
            signals["readiness"] = "future_ready"

    blockers_found = [term for term in BLOCKER_TERMS if term in lowered]
    if blockers_found:
        signals["blockers"] = sorted(set((signals.get("blockers") or []) + blockers_found))
        notes["blockers"] = message.strip()

    risk_found = [term for term in HIGH_RISK if term in lowered]
    if risk_found:
        signals["risk_signals"] = sorted(set((signals.get("risk_signals") or []) + risk_found))

    return signals, notes


def _merge_llm_signals(sub_state: Dict[str, Any], tool_input: Dict[str, Any]) -> None:
    current_signals = dict(sub_state.get("signals") or {})
    current_notes = dict(sub_state.get("notes") or {})
    incoming_signals = tool_input.get("signals") or {}
    incoming_notes = tool_input.get("notes") or {}

    for key, value in incoming_signals.items():
        if value in (None, "", "unknown"):
            continue
        if key in ("blockers", "risk_signals"):
            current = current_signals.get(key) or []
            additions = value if isinstance(value, list) else [value]
            current_signals[key] = sorted(set([*current, *[str(v) for v in additions if v]]))
        else:
            current_signals[key] = value

    for key, value in incoming_notes.items():
        if value not in (None, ""):
            current_notes[key] = value

    if tool_input.get("human_review_needed"):
        current_signals["risk_signals"] = sorted(
            set((current_signals.get("risk_signals") or []) + [tool_input.get("human_review_reason") or "human_review_needed"])
        )

    sub_state["signals"] = current_signals
    sub_state["notes"] = current_notes


def _next_question(sub_state: Dict[str, Any]) -> Optional[str]:
    signals = sub_state.get("signals") or {}
    for key in QUESTION_ORDER:
        if key == "blockers":
            if not signals.get("blockers") and "blockers" not in sub_state.get("asked_questions", []):
                return key
            continue
        if signals.get(key) is None:
            return key
    return None


def _selection_summary(signals: Dict[str, Any], notes: Dict[str, Any], outcome: str, reason: str) -> Tuple[str, List[str]]:
    facts: List[str] = []
    if notes.get("motivation"):
        facts.append(f"Motivation: {notes['motivation']}")
    if notes.get("availability"):
        facts.append(f"Availability: {notes['availability']}")
    if notes.get("language_notes"):
        facts.append(f"Language comfort: {notes['language_notes']}")
    if notes.get("blockers"):
        facts.append(f"Blockers: {notes['blockers']}")
    facts.append(f"Selection outcome: {outcome}")
    summary = reason
    return summary, facts[:6]


class SelectionAgentService:
    """Conversational post-onboarding evaluator."""

    async def process_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        session_id = str(request.session_id)
        sub_state = load_selection_sub_state(request.session_state.sub_state)
        handoff = extract_handoff_payload(request.session_state.sub_state)
        if handoff and not sub_state.get("handoff"):
            sub_state["handoff"] = handoff

        profile, onboarding_summary, key_facts = await self._load_profile_context(request)

        user_message = (request.user_message or "").strip()
        if user_message and user_message not in ("__handoff__", "__auto_continue__"):
            signals, notes = _extract_selection_signals(sub_state, user_message)
            sub_state["signals"] = signals
            sub_state["notes"] = notes
            await self._persist_profile_updates(session_id, profile, signals, notes, user_message)

        if _matches_any(_normalise_text(user_message), PAUSE_PATTERNS):
            summary, facts = _selection_summary(
                sub_state.get("signals") or {},
                sub_state.get("notes") or {},
                SelectionOutcome.PAUSED.value,
                "Volunteer asked to continue later during selection.",
            )
            await domain_client.save_memory_summary(session_id, summary, facts)
            updated_sub_state = dump_selection_sub_state(sub_state)
            await domain_client.advance_state(
                session_id,
                SelectionWorkflowState.PAUSED.value,
                updated_sub_state,
            )
            return self._build_response(
                request=request,
                message="Of course. We can continue this whenever you're ready.",
                state=SelectionWorkflowState.PAUSED.value,
                sub_state=updated_sub_state,
                completion_status=SelectionOutcome.PAUSED.value,
                confirmed_fields={"selection_outcome": SelectionOutcome.PAUSED.value},
            )

        next_question_key = _next_question(sub_state)
        if next_question_key and not (sub_state.get("signals") or {}).get("risk_signals"):
            fallback_question = QUESTION_PROMPTS[next_question_key]

            messages = list(request.conversation_history[-12:])
            if request.user_message and request.user_message not in ("__handoff__", "__auto_continue__"):
                messages.append({"role": "user", "content": request.user_message})

            async def tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
                if tool_name != "record_selection_turn":
                    return {"status": "error", "message": f"Unknown tool: {tool_name}"}
                _merge_llm_signals(sub_state, tool_input)
                return {"status": "success", "recorded": True}

            system_prompt = llm_adapter.build_system_prompt(
                profile=profile.model_dump(mode="json"),
                onboarding_summary=onboarding_summary,
                key_facts=key_facts,
                signals=sub_state.get("signals") or {},
            )
            assistant_message, collected = await llm_adapter.run_selection_loop(
                system_prompt=system_prompt,
                messages=messages,
                tool_executor=tool_executor,
                fallback_question=fallback_question,
            )

            llm_signal = collected.get("record_selection_turn") or {}
            requested_next = llm_signal.get("next_missing_signal")
            if requested_next and requested_next != "none":
                next_question_key = requested_next

            if llm_signal.get("pause_requested"):
                summary, facts = _selection_summary(
                    sub_state.get("signals") or {},
                    sub_state.get("notes") or {},
                    SelectionOutcome.PAUSED.value,
                    "Volunteer asked to continue later during selection.",
                )
                await domain_client.save_memory_summary(session_id, summary, facts)
                updated_sub_state = dump_selection_sub_state(sub_state)
                await domain_client.advance_state(
                    session_id,
                    SelectionWorkflowState.PAUSED.value,
                    updated_sub_state,
                )
                return self._build_response(
                    request=request,
                    message=assistant_message or "Of course. We can continue this whenever you're ready.",
                    state=SelectionWorkflowState.PAUSED.value,
                    sub_state=updated_sub_state,
                    completion_status=SelectionOutcome.PAUSED.value,
                    confirmed_fields={"selection_outcome": SelectionOutcome.PAUSED.value},
                )

            if next_question_key != "none" and next_question_key not in QUESTION_PROMPTS:
                next_question_key = _next_question(sub_state) or "none"

            if next_question_key != "none" and next_question_key not in sub_state["asked_questions"]:
                sub_state["asked_questions"].append(next_question_key)
            updated_sub_state = dump_selection_sub_state(sub_state)
            await domain_client.advance_state(
                session_id,
                SelectionWorkflowState.SELECTION_CONVERSATION.value,
                updated_sub_state,
            )
            telemetry = [
                TelemetryEvent(
                    session_id=request.session_id,
                    event_type=EventType.AGENT_RESPONSE,
                    agent=AgentType.SELECTION,
                    data={"question": next_question_key},
                )
            ]
            return self._build_response(
                request=request,
                message=assistant_message or fallback_question,
                state=SelectionWorkflowState.SELECTION_CONVERSATION.value,
                sub_state=updated_sub_state,
                completion_status="in_progress",
                confirmed_fields={"selection_stage": "questioning"},
                telemetry_events=telemetry,
            )

        evaluation_request = await self._build_evaluation_request(
            request=request,
            profile=profile,
            onboarding_summary=onboarding_summary,
            key_facts=key_facts,
            sub_state=sub_state,
        )
        evaluation = await self.evaluate(evaluation_request)

        await domain_client.log_event(
            session_id,
            "selection_progress",
            {
                "outcome": evaluation.outcome.value,
                "confidence": evaluation.confidence,
                "flags": evaluation.flags,
            },
        )

        summary, facts = _selection_summary(
            sub_state.get("signals") or {},
            sub_state.get("notes") or {},
            evaluation.outcome.value,
            evaluation.reason,
        )
        await domain_client.save_memory_summary(session_id, summary, facts)

        if evaluation.outcome == SelectionOutcome.HUMAN_REVIEW:
            updated_sub_state = dump_selection_sub_state(sub_state)
            await domain_client.advance_state(
                session_id,
                SelectionWorkflowState.HUMAN_REVIEW.value,
                updated_sub_state,
            )
            return self._build_response(
                request=request,
                message="Thank you for sharing that. Our team will review the details and get back to you shortly.",
                state=SelectionWorkflowState.HUMAN_REVIEW.value,
                sub_state=updated_sub_state,
                completion_status=SelectionOutcome.HUMAN_REVIEW.value,
                confirmed_fields={
                    "selection_outcome": SelectionOutcome.HUMAN_REVIEW.value,
                    "selection_reason": evaluation.reason,
                },
            )

        updated_sub_state = dump_selection_sub_state(sub_state)
        handoff_event = self._build_engagement_handoff(
            request=request,
            profile=profile,
            evaluation=evaluation,
            sub_state=sub_state,
            onboarding_summary=onboarding_summary,
            key_facts=key_facts,
        )
        return self._build_response(
            request=request,
            message=self._selection_closeout(evaluation.outcome),
            state=SelectionWorkflowState.GATHERING_PREFERENCES.value,
            sub_state=updated_sub_state,
            completion_status=evaluation.outcome.value,
            confirmed_fields={
                "selection_outcome": evaluation.outcome.value,
                "selection_confidence": evaluation.confidence,
                "selection_reason": evaluation.reason,
            },
            handoff_event=handoff_event,
        )

    async def evaluate(self, request: SelectionEvaluateRequest) -> SelectionEvaluateResponse:
        profile = request.profile
        signals = dict(request.selection_signals or {})

        flags: List[str] = []
        recommended_actions: List[str] = []

        if signals.get("risk_signals"):
            flags.extend(signals["risk_signals"])
        if signals.get("communication_clarity") == "unclear":
            flags.append("low_clarity")
        if not (profile.email or profile.phone):
            flags.append("missing_primary_contact")

        if signals.get("risk_signals"):
            outcome = SelectionOutcome.HUMAN_REVIEW
            confidence = 0.9
            reason = "The conversation includes signals that need a human follow-up."
            recommended_actions = ["human_review"]
        elif signals.get("language_comfort") == "limited":
            outcome = SelectionOutcome.NOT_MATCHED
            confidence = 0.78
            reason = "Current language comfort does not yet look strong enough for immediate teaching readiness."
            recommended_actions = ["nurture_for_later"]
        elif (
            signals.get("motivation_alignment") == "strong"
            and signals.get("continuity_intent") == "committed"
            and signals.get("communication_clarity") == "clear"
            and signals.get("language_comfort") == "comfortable"
            and signals.get("availability_realism") == "realistic"
            and signals.get("readiness") == "ready_now"
            and not signals.get("blockers")
        ):
            outcome = SelectionOutcome.RECOMMENDED
            confidence = 0.9
            reason = "The volunteer shows strong motivation, clarity, commitment, and near-term readiness."
            recommended_actions = ["handoff_to_engagement"]
        elif signals.get("motivation_alignment") in ("strong", "moderate"):
            outcome = SelectionOutcome.ENGAGEMENT_LATER
            confidence = 0.72
            reason = "The volunteer is positive, but current timing or readiness looks better suited for continued engagement."
            recommended_actions = ["nurture_in_engagement"]
        else:
            outcome = SelectionOutcome.NOT_MATCHED
            confidence = 0.7
            reason = "Current responses do not show enough readiness or fit for immediate matching."
            recommended_actions = ["engage_later_if_interest_remains"]

        return SelectionEvaluateResponse(
            session_id=request.session_id,
            volunteer_id=request.volunteer_id,
            outcome=outcome,
            confidence=round(confidence, 2),
            reason=reason,
            flags=flags,
            recommended_actions=recommended_actions,
            evaluation_details={
                "selection_signals": signals,
                "profile_present": bool(profile.full_name or profile.email or profile.phone),
                "key_facts_count": len(request.key_facts),
            },
        )

    async def _load_profile_context(
        self,
        request: AgentTurnRequest,
    ) -> Tuple[VolunteerProfile, Optional[str], List[str]]:
        session_id = str(request.session_id)
        handoff = extract_handoff_payload(request.session_state.sub_state)
        profile_result = await domain_client.get_volunteer_profile(session_id)
        memory_result = await domain_client.get_memory_summary(session_id)

        profile_data = profile_result.get("profile", {}) if isinstance(profile_result, dict) else {}
        confirmed_fields = handoff.get("confirmed_fields", {})
        merged_profile = dict(profile_data or {})
        for key, value in (confirmed_fields or {}).items():
            if value is not None:
                merged_profile[key] = value

        memory_data = memory_result.get("data") if isinstance(memory_result, dict) else {}
        onboarding_summary = handoff.get("memory_summary") or (memory_data or {}).get("summary_text")
        key_facts = handoff.get("key_facts") or (memory_data or {}).get("key_facts", [])

        return VolunteerProfile(
            volunteer_id=str(request.session_state.volunteer_id) if request.session_state.volunteer_id else merged_profile.get("volunteer_id"),
            full_name=merged_profile.get("full_name"),
            first_name=merged_profile.get("first_name"),
            email=merged_profile.get("email"),
            phone=merged_profile.get("phone") or request.session_state.volunteer_phone,
            location=merged_profile.get("location"),
            skills=merged_profile.get("skills") or [],
            interests=merged_profile.get("interests") or [],
            availability=merged_profile.get("availability"),
            languages=merged_profile.get("languages") or [],
            motivation=merged_profile.get("motivation"),
            qualification=merged_profile.get("qualification"),
            years_of_experience=str(merged_profile.get("years_of_experience")) if merged_profile.get("years_of_experience") is not None else None,
            employment_status=merged_profile.get("employment_status"),
        ), onboarding_summary, list(key_facts or [])

    async def _build_evaluation_request(
        self,
        request: AgentTurnRequest,
        profile: VolunteerProfile,
        onboarding_summary: Optional[str],
        key_facts: List[str],
        sub_state: Dict[str, Any],
    ) -> SelectionEvaluateRequest:
        return SelectionEvaluateRequest(
            session_id=request.session_id,
            volunteer_id=profile.volunteer_id,
            profile=profile,
            onboarding_summary=onboarding_summary,
            key_facts=key_facts,
            metadata={},
            selection_signals=sub_state.get("signals") or {},
        )

    async def _persist_profile_updates(
        self,
        session_id: str,
        profile: VolunteerProfile,
        signals: Dict[str, Any],
        notes: Dict[str, Any],
        raw_message: str,
    ) -> None:
        updates: Dict[str, Any] = {}
        if notes.get("motivation"):
            updates["motivation"] = notes["motivation"]
        if notes.get("availability"):
            updates["availability"] = notes["availability"]
        languages = sorted(set((profile.languages or []) + _extract_languages(raw_message)))
        if languages:
            updates["languages"] = languages
        if updates:
            await domain_client.save_confirmed_fields(session_id, updates)

    def _selection_closeout(self, outcome: SelectionOutcome) -> str:
        if outcome == SelectionOutcome.RECOMMENDED:
            return "Thank you. I have what I need, and I’m moving you to the next step."
        if outcome == SelectionOutcome.ENGAGEMENT_LATER:
            return "Thank you. I have what I need, and I’ll guide you to the next step from here."
        return "Thank you for sharing that. I’ll take you to the next step from here."

    def _build_engagement_handoff(
        self,
        request: AgentTurnRequest,
        profile: VolunteerProfile,
        evaluation: SelectionEvaluateResponse,
        sub_state: Dict[str, Any],
        onboarding_summary: Optional[str],
        key_facts: List[str],
    ) -> Dict[str, Any]:
        signals = sub_state.get("signals") or {}
        notes = sub_state.get("notes") or {}
        selection_payload = {
            "selection_outcome": evaluation.outcome.value,
            "selection_reason": evaluation.reason,
            "selection_confidence": evaluation.confidence,
            "selection_signals": signals,
            "selection_notes": notes,
            "onboarding_summary": onboarding_summary,
            "key_facts": key_facts,
        }

        target_sub_state = {
            "entry_type": "selected_new_volunteer",
            "engagement_context": {
                "status": "success",
                "volunteer_id": profile.volunteer_id,
                "volunteer_name": profile.full_name or request.session_state.volunteer_name,
                "volunteer_phone": profile.phone or request.session_state.volunteer_phone,
                "fulfillment_history": [],
            },
            "registration_url": None,
            "identity_verified": True,
            "preference_notes": None,
            "available_from": (
                "immediately"
                if signals.get("readiness") == "ready_now"
                else (notes.get("availability") or "later")
            ),
            "handoff": selection_payload,
            "human_review_reason": None,
            "deferred": evaluation.outcome == SelectionOutcome.ENGAGEMENT_LATER,
            "deferred_reason": evaluation.reason if evaluation.outcome == SelectionOutcome.ENGAGEMENT_LATER else None,
        }

        payload = {
            **selection_payload,
            "target_sub_state": target_sub_state,
        }

        return {
            "session_id": request.session_id,
            "from_agent": AgentType.SELECTION,
            "to_agent": AgentType.ENGAGEMENT,
            "handoff_type": "agent_transition",
            "payload": payload,
            "reason": "Selection completed - passing volunteer to engagement for downstream preference capture",
        }

    def _build_response(
        self,
        request: AgentTurnRequest,
        message: str,
        state: str,
        sub_state: str,
        completion_status: str,
        confirmed_fields: Dict[str, Any],
        missing_fields: Optional[List[str]] = None,
        handoff_event: Optional[Dict[str, Any]] = None,
        telemetry_events: Optional[List[TelemetryEvent]] = None,
    ) -> AgentTurnResponse:
        return AgentTurnResponse(
            assistant_message=message,
            active_agent=AgentType.SELECTION,
            workflow=WorkflowType(request.session_state.workflow),
            state=state,
            sub_state=sub_state,
            completion_status=completion_status,
            confirmed_fields=confirmed_fields,
            missing_fields=missing_fields or [],
            handoff_event=handoff_event,
            telemetry_events=telemetry_events or [],
        )


selection_agent_service = SelectionAgentService()
