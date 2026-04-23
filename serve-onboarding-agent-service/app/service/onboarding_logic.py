"""
SERVE Onboarding Agent Service - Onboarding Logic

New volunteer onboarding flow:
1. Welcome → Orientation (videos)
2. Eligibility screening (3 questions)
3. Contact + qualification capture (name, email, qualification)
4. Registration review → Register → Handoff to selection

Phone is auto-populated from WhatsApp channel_metadata, not asked.
All transition decisions are deterministic in Python; the LLM only generates
the natural-language response.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.clients import domain_client
from app.schemas import (
    AgentTurnRequest,
    AgentTurnResponse,
    AgentType,
    EventType,
    HandoffEvent,
    HandoffType,
    OnboardingState,
    TelemetryEvent,
    WorkflowType,
)
from app.service.llm_adapter import llm_adapter

logger = logging.getLogger(__name__)

# ── Required fields ─────────────────────────────────────────────────────────────
# These gate state transitions. The flow cannot advance until all are captured.
CONTACT_FIELDS = ["full_name", "email", "qualification"]
ELIGIBILITY_FIELDS = ["age_18_plus", "has_internet_and_device", "accepts_unpaid_role"]

DEFAULT_SUB_STATE: Dict[str, Any] = {
    "resume_stage": OnboardingState.ORIENTATION_VIDEO.value,
    "video_acknowledged": False,
    "welcome_shown": False,
    "welcome_response": None,
    "eligibility": {
        "age_18_plus": None,
        "has_internet_and_device": None,
        "accepts_unpaid_role": None,
    },
    "eligibility_pending_negative": {},
    "review_reason": None,
}

# ── Pattern tables ──────────────────────────────────────────────────────────────
YES_PATTERNS = [
    r"\byes\b", r"\byeah\b", r"\byep\b", r"\byup\b", r"\bok\b", r"\bokay\b",
    r"\bsure\b", r"\bi do\b", r"\bi have\b", r"\bcan do\b", r"\bagree\b",
    r"\bunderstand\b", r"\bcontinue\b", r"\bdone\b", r"\bwatched\b", r"\bready\b",
    r"\bhaan\b", r"\bhaan ji\b", r"\bji\b", r"\bof course\b",
]
NO_PATTERNS = [
    r"\bno\b", r"\bnope\b", r"\bnot really\b", r"\bdon't\b", r"\bdo not\b",
    r"\bcan't\b", r"\bcannot\b", r"\bunable\b", r"\bnahin\b", r"\bnahi\b",
]
PAUSE_PATTERNS = [r"\bpause\b", r"\blater\b", r"\bnot now\b", r"\bbusy\b", r"\bstop\b"]
RESUME_PATTERNS = [r"\bresume\b", r"\bcontinue\b", r"\bstart\b", r"\bready\b", r"\bback\b"]
CONFIRM_PATTERNS = [r"\byes\b", r"\bcorrect\b", r"\bconfirm\b", r"\blooks good\b", r"\bright\b", r"\bok\b", r"\bokay\b"]
EDIT_CONTACT_PATTERNS = [r"\bname\b", r"\bemail\b", r"\bcontact\b", r"\bqualification\b"]

# ── Qualification keywords ──────────────────────────────────────────────────────
QUALIFICATION_PATTERNS = [
    # Degree abbreviations
    r"\b(B\.?E\.?|B\.?Tech|B\.?Sc|B\.?A\.?|B\.?Com|B\.?C\.?A\.?|BBA|BDS|MBBS)\b",
    r"\b(M\.?E\.?|M\.?Tech|M\.?Sc|M\.?A\.?|M\.?Com|M\.?C\.?A\.?|MBA|MDS|MD)\b",
    r"\b(Ph\.?D|Doctorate|Post.?Graduate|Post.?Graduation)\b",
    # Common terms
    r"\b(graduate|graduation|under.?graduate|diploma|engineering|medical|law)\b",
    r"\b(12th|10th|12th pass|10th pass|intermediate|higher secondary|HSC|SSC)\b",
    r"\b(CA|CS|CMA|LLB|LLM|BAMS|BHMS)\b",
]


class ProfileExtractor:
    """Extract profile information from free-form volunteer messages."""

    NAME_SIGNALS = [
        r"(?:my name is|i'm|i am|call me|this is|naam hai|mera naam)\s+([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)*)",
        r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)(?:\s+here|,)",
        r"(?:name[:\s]+)([A-Za-z][a-z]+(?:\s+[A-Za-z][a-z]+)*)",
        r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})$",
    ]
    NAME_STOPWORDS = {
        "and", "or", "but", "hello", "hi", "hey", "want", "would", "like",
        "interested", "back", "ready", "looking", "excited", "happy", "new",
        "available", "sure", "yes", "yeah", "okay", "fine", "good", "great",
        "thanks", "thank", "please", "sorry", "not", "very", "really",
        "just", "also", "here", "there", "from", "with", "about", "that",
        "this", "have", "been", "done", "teaching", "volunteering", "joining",
        "starting", "continuing", "returning", "recommended",
    }
    EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    PHONE_PATTERNS = [
        r"\b(\+?\d{1,3}[-.\s]?\d{10})\b",
        r"\b(\d{10})\b",
        r"\b(\d{3}[-.\s]\d{3}[-.\s]\d{4})\b",
    ]

    def extract_all(self, message: str, existing_fields: Optional[Dict[str, Any]] = None, current_stage: Optional[str] = None) -> Dict[str, Any]:
        existing_fields = existing_fields or {}
        extracted: Dict[str, Any] = {}

        # Phone is always extracted (for auto-population from any message)
        if "phone" not in existing_fields:
            phone = self._extract_phone(message)
            if phone:
                extracted["phone"] = phone

        # Name, email, qualification are only extracted during contact_capture
        # to prevent premature field population from skipping stages
        if current_stage == "contact_capture":
            if "full_name" not in existing_fields:
                name = self._extract_name(message)
                if name:
                    extracted["full_name"] = name

            if "email" not in existing_fields:
                email = self._extract_email(message)
                if email:
                    extracted["email"] = email

            if "qualification" not in existing_fields:
                qual = self._extract_qualification(message)
                if qual:
                    extracted["qualification"] = qual
                else:
                    # Fallback: if we're asking for qualification and the message is short,
                    # treat it as the qualification answer
                    missing_contact = [f for f in ["full_name", "email", "qualification"] if not existing_fields.get(f)]
                    if missing_contact == ["qualification"]:
                        stripped = message.strip()
                        if 1 < len(stripped) < 50 and not re.search(self.EMAIL_PATTERN, stripped) and not re.search(r"\d{10}", stripped):
                            extracted["qualification"] = stripped

        return extracted

    def _extract_name(self, message: str) -> Optional[str]:
        candidates_to_try = [message, message.strip()]
        for text in candidates_to_try:
            for pattern in self.NAME_SIGNALS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()
                    words = []
                    for word in value.split():
                        lower = word.lower()
                        if lower in self.NAME_STOPWORDS:
                            break
                        words.append(word)
                    if words:
                        candidate = " ".join(words[:3]).title()
                        if len(candidate) >= 2 and not candidate.isdigit():
                            return candidate
        return None

    def _extract_email(self, message: str) -> Optional[str]:
        match = re.search(self.EMAIL_PATTERN, message)
        return match.group(0).lower() if match else None

    def _extract_phone(self, message: str) -> Optional[str]:
        for pattern in self.PHONE_PATTERNS:
            match = re.search(pattern, message)
            if match:
                return re.sub(r"[^\d+]", "", match.group(1))
        return None

    def _extract_qualification(self, message: str) -> Optional[str]:
        """Extract educational qualification from known patterns only."""
        for pattern in QUALIFICATION_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None


profile_extractor = ProfileExtractor()


# ── Sub-state helpers ───────────────────────────────────────────────────────────

def _load_sub_state(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return json.loads(json.dumps(DEFAULT_SUB_STATE))
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return json.loads(json.dumps(DEFAULT_SUB_STATE))
        merged = json.loads(json.dumps(DEFAULT_SUB_STATE))
        merged.update(data)
        merged_elig = dict(DEFAULT_SUB_STATE["eligibility"])
        merged_elig.update(data.get("eligibility") or {})
        merged["eligibility"] = merged_elig
        merged["eligibility_pending_negative"] = data.get("eligibility_pending_negative") or {}
        merged["welcome_response"] = data.get("welcome_response")
        merged["welcome_shown"] = data.get("welcome_shown", False)
        return merged
    except (json.JSONDecodeError, ValueError):
        return json.loads(json.dumps(DEFAULT_SUB_STATE))


def _dump_sub_state(sub_state: Dict[str, Any]) -> str:
    return json.dumps({
        "resume_stage": sub_state.get("resume_stage"),
        "video_acknowledged": sub_state.get("video_acknowledged", False),
        "welcome_shown": sub_state.get("welcome_shown", False),
        "welcome_response": sub_state.get("welcome_response"),
        "eligibility": sub_state.get("eligibility", {}),
        "eligibility_pending_negative": sub_state.get("eligibility_pending_negative", {}),
        "review_reason": sub_state.get("review_reason"),
    })


# ── Pattern matching helpers ────────────────────────────────────────────────────

def _matches_any(text: str, patterns: List[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _extract_binary_response(message: str) -> Optional[bool]:
    lower = message.lower()
    if _matches_any(lower, NO_PATTERNS):
        return False
    if _matches_any(lower, YES_PATTERNS):
        return True
    return None


def _extract_age_eligibility(message: str) -> Optional[bool]:
    lower = message.lower()
    explicit = _extract_binary_response(lower)
    if explicit is not None:
        return explicit
    match = re.search(r"\b(\d{2})\b", lower)
    if match:
        return int(match.group(1)) >= 18
    if "adult" in lower or "above 18" in lower or "over 18" in lower:
        return True
    if "under 18" in lower or "below 18" in lower:
        return False
    return None


def _extract_video_ack(message: str) -> bool:
    lower = message.lower()
    return _matches_any(lower, [
        r"\bdone\b", r"\bwatched\b", r"\bcontinue\b", r"\bready\b",
        r"\bok\b", r"\bokay\b", r"\byes\b",
    ])


# ── Eligibility logic ──────────────────────────────────────────────────────────

def _next_eligibility_question(sub_state: Dict[str, Any]) -> Optional[str]:
    eligibility = sub_state.get("eligibility", {})
    for field in ELIGIBILITY_FIELDS:
        if eligibility.get(field) is None:
            return field
    return None


def _apply_eligibility_answers(sub_state: Dict[str, Any], message: str) -> None:
    eligibility = dict(sub_state.get("eligibility") or {})
    pending_neg = dict(sub_state.get("eligibility_pending_negative") or {})
    current_question = _next_eligibility_question(sub_state)

    if current_question == "age_18_plus":
        answer = _extract_age_eligibility(message)
    elif current_question:
        answer = _extract_binary_response(message)
    else:
        answer = None

    if current_question and answer is not None:
        if answer is False and current_question not in pending_neg:
            pending_neg[current_question] = True
        elif answer is False and current_question in pending_neg:
            eligibility[current_question] = False
            pending_neg.pop(current_question, None)
        else:
            eligibility[current_question] = True
            pending_neg.pop(current_question, None)

    # Keyword-based detection for the merged internet+device field
    lower = message.lower()
    if any(t in lower for t in ["internet", "wifi", "data", "laptop", "tablet", "device", "computer"]):
        kw_answer = _extract_binary_response(message)
        if kw_answer is not None:
            field = "has_internet_and_device"
            if kw_answer is False and field not in pending_neg:
                pending_neg[field] = True
            elif kw_answer is False and field in pending_neg:
                eligibility[field] = False
                pending_neg.pop(field, None)
            else:
                eligibility[field] = kw_answer
                pending_neg.pop(field, None)

    if any(t in lower for t in ["unpaid", "paid", "volunteer role", "not paid", "without pay"]):
        kw_answer = _extract_binary_response(message)
        if kw_answer is not None:
            field = "accepts_unpaid_role"
            if kw_answer is False and field not in pending_neg:
                pending_neg[field] = True
            elif kw_answer is False and field in pending_neg:
                eligibility[field] = False
                pending_neg.pop(field, None)
            else:
                eligibility[field] = kw_answer
                pending_neg.pop(field, None)

    sub_state["eligibility"] = eligibility
    sub_state["eligibility_pending_negative"] = pending_neg


def _eligibility_failed(sub_state: Dict[str, Any]) -> Optional[str]:
    eligibility = sub_state.get("eligibility") or {}
    for field in ELIGIBILITY_FIELDS:
        if eligibility.get(field) is False:
            return field
    return None


def _all_eligibility_passed(sub_state: Dict[str, Any]) -> bool:
    eligibility = sub_state.get("eligibility") or {}
    return all(eligibility.get(field) is True for field in ELIGIBILITY_FIELDS)


# ── Stage transition logic ──────────────────────────────────────────────────────

def _stage_missing_fields(stage: str, confirmed_fields: Dict[str, Any], sub_state: Dict[str, Any]) -> List[str]:
    if stage == OnboardingState.ORIENTATION_VIDEO.value:
        return [] if sub_state.get("video_acknowledged") else ["video_acknowledgement"]

    if stage == OnboardingState.ELIGIBILITY_SCREENING.value:
        pending_neg = sub_state.get("eligibility_pending_negative", {})
        missing = []
        for field in ELIGIBILITY_FIELDS:
            if sub_state.get("eligibility", {}).get(field) is None:
                if field in pending_neg:
                    missing.append(f"{field}_clarification")
                else:
                    missing.append(field)
        return missing

    if stage == OnboardingState.CONTACT_CAPTURE.value:
        return [f for f in CONTACT_FIELDS if not confirmed_fields.get(f)]

    return []


def _evaluate_registration_readiness(confirmed_fields: Dict[str, Any], sub_state: Dict[str, Any]) -> Tuple[bool, List[str]]:
    missing: List[str] = []
    if not _all_eligibility_passed(sub_state):
        missing.extend([f for f in ELIGIBILITY_FIELDS if sub_state.get("eligibility", {}).get(f) is not True])
    for field in CONTACT_FIELDS:
        value = confirmed_fields.get(field)
        if not value or (isinstance(value, list) and len(value) == 0):
            missing.append(field)
    return len(missing) == 0, missing


def _determine_next_state(
    current_state: str,
    user_message: str,
    confirmed_fields: Dict[str, Any],
    sub_state: Dict[str, Any],
) -> Tuple[str, Optional[str]]:
    lower = (user_message or "").lower()

    if current_state == OnboardingState.PAUSED.value and _matches_any(lower, RESUME_PATTERNS):
        return sub_state.get("resume_stage") or OnboardingState.ORIENTATION_VIDEO.value, "Volunteer resumed"

    if current_state not in (
        OnboardingState.WELCOME.value,
        OnboardingState.ONBOARDING_COMPLETE.value,
        OnboardingState.HUMAN_REVIEW.value,
    ) and _matches_any(lower, PAUSE_PATTERNS):
        return OnboardingState.PAUSED.value, "Volunteer asked to pause"

    if current_state == OnboardingState.WELCOME.value:
        if not sub_state.get("welcome_shown"):
            # First turn — mark as shown, stay at welcome so the LLM generates the welcome message.
            sub_state["welcome_shown"] = True
            return current_state, "Showing welcome message"
        # Second turn — volunteer has responded to "what brings you here?"
        return OnboardingState.ORIENTATION_VIDEO.value, "Welcome response received — proceeding to orientation"

    if current_state == OnboardingState.ORIENTATION_VIDEO.value:
        if sub_state.get("video_acknowledged"):
            return OnboardingState.ELIGIBILITY_SCREENING.value, "Orientation acknowledged"
        return current_state, "Waiting for video acknowledgement"

    if current_state == OnboardingState.ELIGIBILITY_SCREENING.value:
        failed = _eligibility_failed(sub_state)
        if failed:
            sub_state["review_reason"] = failed
            return OnboardingState.HUMAN_REVIEW.value, f"Eligibility needs review: {failed}"
        if _all_eligibility_passed(sub_state):
            return OnboardingState.CONTACT_CAPTURE.value, "Eligibility passed"
        return current_state, "Collecting eligibility checks"

    if current_state == OnboardingState.CONTACT_CAPTURE.value:
        missing = _stage_missing_fields(current_state, confirmed_fields, sub_state)
        if not missing:
            return OnboardingState.REGISTRATION_REVIEW.value, "Contact details captured"
        return current_state, "Collecting contact details"

    if current_state == OnboardingState.TEACHING_PROFILE.value:
        return OnboardingState.REGISTRATION_REVIEW.value, "Legacy stage redirected"

    if current_state == OnboardingState.REGISTRATION_REVIEW.value:
        if _matches_any(lower, CONFIRM_PATTERNS):
            ready, _ = _evaluate_registration_readiness(confirmed_fields, sub_state)
            if ready:
                return OnboardingState.ONBOARDING_COMPLETE.value, "Volunteer confirmed registration"
        if any(t in lower for t in ["change", "update", "edit", "wrong", "fix"]):
            return OnboardingState.CONTACT_CAPTURE.value, "Volunteer wants to update details"
        return current_state, "Waiting for registration confirmation"

    return current_state, "No transition"


def _unwrap_missing_fields(result: Dict[str, Any]) -> Tuple[List[str], Dict[str, Any]]:
    data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
    return list(data.get("missing_fields", []) or []), dict(data.get("confirmed_fields", {}) or {})


def _build_prompt_fields(confirmed_fields: Dict[str, Any], sub_state: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(confirmed_fields)
    eligibility = sub_state.get("eligibility", {})
    for key in ELIGIBILITY_FIELDS:
        merged[key] = eligibility.get(key)
    merged["review_reason"] = sub_state.get("review_reason")
    merged["welcome_response"] = sub_state.get("welcome_response")
    return merged


# ── Main agent service ──────────────────────────────────────────────────────────

class OnboardingAgentService:
    def __init__(self) -> None:
        from app.service.memory_service import memory_service
        self.memory_service = memory_service

    async def process_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        session_state = request.session_state
        current_state = self._normalise_stage(session_state.stage)
        telemetry_events: List[TelemetryEvent] = []

        logger.info(f"[{request.session_id}] ── TURN START ── stage={current_state} user_msg={request.user_message[:80]!r}")

        sub_state = _load_sub_state(session_state.sub_state)
        logger.info(f"[{request.session_id}] sub_state loaded: welcome_shown={sub_state.get('welcome_shown')}, video_ack={sub_state.get('video_acknowledged')}, eligibility={sub_state.get('eligibility')}")

        if current_state not in (
            OnboardingState.PAUSED.value,
            OnboardingState.HUMAN_REVIEW.value,
            OnboardingState.ONBOARDING_COMPLETE.value,
        ):
            sub_state["resume_stage"] = current_state

        telemetry_events.append(
            TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.USER_MESSAGE,
                agent=AgentType.ONBOARDING,
                data={"message_length": len(request.user_message)},
            )
        )

        missing_result = await domain_client.get_missing_fields(request.session_id)
        _, confirmed_fields = _unwrap_missing_fields(missing_result)
        logger.info(f"[{request.session_id}] confirmed_fields from MCP: {list(confirmed_fields.keys())}")

        # Auto-populate phone from WhatsApp channel_metadata if not already set
        if "phone" not in confirmed_fields:
            ch_meta = (session_state.channel_metadata or {})
            # Also try request-level channel_metadata (if orchestrator sends it)
            if not ch_meta:
                ch_meta = getattr(request, "channel_metadata", None) or {}
            phone_from_channel = (
                ch_meta.get("volunteer_phone")
                or ch_meta.get("phone_number")
                or ch_meta.get("from")
                or ch_meta.get("wa_id")
            )
            if phone_from_channel:
                confirmed_fields["phone"] = phone_from_channel
                await domain_client.save_confirmed_fields(request.session_id, {"phone": phone_from_channel})

        memory_context = await self.memory_service.get_memory_context(
            session_id=str(request.session_id),
            confirmed_fields=confirmed_fields,
            domain_client=domain_client,
        )

        extracted_fields = profile_extractor.extract_all(
            request.user_message,
            existing_fields=confirmed_fields,
            current_stage=current_state,
        )
        logger.info(f"[{request.session_id}] extractor result (stage={current_state}): {extracted_fields}")
        new_fields = {k: v for k, v in extracted_fields.items() if confirmed_fields.get(k) != v}
        if new_fields:
            logger.info(f"[{request.session_id}] saving new fields: {list(new_fields.keys())}")
            await domain_client.save_confirmed_fields(request.session_id, new_fields)
            confirmed_fields.update(new_fields)
            telemetry_events.append(
                TelemetryEvent(
                    session_id=request.session_id,
                    event_type=EventType.MCP_CALL,
                    agent=AgentType.ONBOARDING,
                    data={"action": "save_fields", "fields": list(new_fields.keys())},
                )
            )

        self._update_stage_specific_sub_state(current_state, request.user_message, sub_state)

        next_state, transition_reason = _determine_next_state(
            current_state=current_state,
            user_message=request.user_message,
            confirmed_fields=confirmed_fields,
            sub_state=sub_state,
        )

        logger.info(f"[{request.session_id}] state decision: {current_state} → {next_state} ({transition_reason})")

        if next_state != current_state:
            logger.info("Onboarding transition: %s -> %s (%s)", current_state, next_state, transition_reason)
            telemetry_events.append(
                TelemetryEvent(
                    session_id=request.session_id,
                    event_type=EventType.STATE_TRANSITION,
                    agent=AgentType.ONBOARDING,
                    data={"from_state": current_state, "to_state": next_state, "reason": transition_reason},
                )
            )

        await self._persist_profile_side_effects(request, next_state, sub_state)

        next_missing_fields = _stage_missing_fields(next_state, confirmed_fields, sub_state)
        logger.info(f"[{request.session_id}] LLM prompt stage={next_state}, missing_fields={next_missing_fields}")
        assistant_message = await llm_adapter.generate_response(
            stage=next_state,
            messages=request.conversation_history,
            user_message=request.user_message,
            missing_fields=next_missing_fields,
            confirmed_fields=_build_prompt_fields(confirmed_fields, sub_state),
            memory_context=memory_context,
        )

        updated_sub_state = _dump_sub_state(sub_state)
        if next_state == current_state:
            await domain_client.advance_state(request.session_id, new_state=current_state, sub_state=updated_sub_state)

        conversation_with_new = request.conversation_history + [
            {"role": "user", "content": request.user_message},
            {"role": "assistant", "content": assistant_message},
        ]
        summary_result = await self.memory_service.process_conversation_update(
            session_id=str(request.session_id),
            conversation=conversation_with_new,
            domain_client=domain_client,
        )

        handoff_event = None
        completion_status = "in_progress"
        response_missing_fields = next_missing_fields

        logger.info(f"[{request.session_id}] ── TURN END ── final_state={next_state} has_handoff={next_state == OnboardingState.ONBOARDING_COMPLETE.value}")

        if next_state == OnboardingState.ONBOARDING_COMPLETE.value:
            completion_status = "complete"
            final_summary = await self.memory_service.process_conversation_update(
                session_id=str(request.session_id), conversation=conversation_with_new, domain_client=domain_client,
            )
            handoff_event = HandoffEvent(
                session_id=request.session_id,
                from_agent=AgentType.ONBOARDING,
                to_agent=AgentType.SELECTION,
                handoff_type=HandoffType.AGENT_TRANSITION,
                payload={
                    "confirmed_fields": confirmed_fields,
                    "memory_summary": final_summary.get("summary_text") if final_summary else None,
                    "key_facts": final_summary.get("key_facts", []) if final_summary else [],
                    "readiness": {"is_ready": True, "profile_complete": True, "eligibility_passed": True},
                    "target_sub_state": {
                        "handoff": {
                            "confirmed_fields": confirmed_fields,
                            "memory_summary": final_summary.get("summary_text") if final_summary else None,
                            "key_facts": final_summary.get("key_facts", []) if final_summary else [],
                            "readiness": {"is_ready": True, "profile_complete": True, "eligibility_passed": True},
                        },
                        "signals": {}, "notes": {}, "asked_questions": [], "outcome": None, "outcome_reason": None,
                    },
                },
                reason="Onboarding completed - eligible volunteer ready for selection",
            )
        elif next_state == OnboardingState.HUMAN_REVIEW.value:
            completion_status = "review_pending"
            response_missing_fields = []
            await self.memory_service.process_conversation_update(
                session_id=str(request.session_id), conversation=conversation_with_new, domain_client=domain_client,
            )
        elif next_state == OnboardingState.PAUSED.value:
            completion_status = "paused"

        telemetry_events.append(
            TelemetryEvent(
                session_id=request.session_id,
                event_type=EventType.AGENT_RESPONSE,
                agent=AgentType.ONBOARDING,
                data={"state": next_state, "response_length": len(assistant_message), "used_memory": bool(memory_context), "summary_updated": bool(summary_result)},
            )
        )

        return AgentTurnResponse(
            assistant_message=assistant_message,
            active_agent=AgentType.ONBOARDING,
            workflow=WorkflowType(session_state.workflow),
            state=next_state,
            sub_state=updated_sub_state,
            completion_status=completion_status,
            confirmed_fields=_build_prompt_fields(confirmed_fields, sub_state),
            missing_fields=response_missing_fields,
            handoff_event=handoff_event,
            telemetry_events=telemetry_events,
        )

    def _normalise_stage(self, stage: str) -> str:
        legacy_map = {
            "init": OnboardingState.WELCOME.value,
            "intent_discovery": OnboardingState.WELCOME.value,
            "purpose_orientation": OnboardingState.ORIENTATION_VIDEO.value,
            "eligibility_confirmation": OnboardingState.ELIGIBILITY_SCREENING.value,
            "capability_discovery": OnboardingState.REGISTRATION_REVIEW.value,
            "profile_confirmation": OnboardingState.REGISTRATION_REVIEW.value,
        }
        return legacy_map.get(stage, stage)

    def _update_stage_specific_sub_state(self, current_state: str, user_message: str, sub_state: Dict[str, Any]) -> None:
        if current_state == OnboardingState.WELCOME.value:
            # Capture the volunteer's response on the second turn (welcome_shown is already True)
            if sub_state.get("welcome_shown") and user_message and user_message not in ("__handoff__", "__auto_continue__"):
                sub_state["welcome_response"] = user_message.strip()[:500]
        if current_state == OnboardingState.ORIENTATION_VIDEO.value and _extract_video_ack(user_message):
            sub_state["video_acknowledged"] = True
        if current_state == OnboardingState.ELIGIBILITY_SCREENING.value:
            _apply_eligibility_answers(sub_state, user_message)

    async def _persist_profile_side_effects(self, request: AgentTurnRequest, next_state: str, sub_state: Dict[str, Any]) -> None:
        if next_state == OnboardingState.CONTACT_CAPTURE.value and _all_eligibility_passed(sub_state):
            await domain_client.save_confirmed_fields(request.session_id, {"eligibility_status": "eligible"})
            return
        if next_state == OnboardingState.HUMAN_REVIEW.value:
            review_reason = sub_state.get("review_reason") or "eligibility_review_required"
            await domain_client.save_confirmed_fields(request.session_id, {"eligibility_status": "review_pending"})
            await domain_client.log_event(request.session_id, "onboarding_review_pending", agent=AgentType.ONBOARDING.value, data={"reason": review_reason})


onboarding_agent_service = OnboardingAgentService()
