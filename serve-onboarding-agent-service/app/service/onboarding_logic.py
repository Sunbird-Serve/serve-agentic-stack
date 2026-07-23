"""
SERVE Onboarding Agent Service - Onboarding Logic (v2)

Improved onboarding flow:
1. Welcome (1 turn) — warm intro + what brings you here
2. Orientation video (non-blocking — shows video + starts eligibility)
3. Quick eligibility (bundled — all 3 checks in one turn where possible)
4. Contact capture (name, email, phone, qualification)
5. Registration review → Complete → Handoff to selection

Key improvements over v1:
- Welcome collapsed from 3 turns to 1-2 turns
- Video is non-blocking (acknowledged implicitly on next reply)
- Eligibility asked as a bundle first, falls back to individual on ambiguity
- Email typo detection (gmal.com → gmail.com?)
- Hindi/Hinglish name extraction support
- Reluctance handling (why do you need my email/phone?)
- Transparent eligibility failure messaging
- Progress hints in prompts
- Motivation captured and used for personalization

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
CONTACT_FIELDS = ["full_name", "email", "phone"]
ELIGIBILITY_FIELDS = ["age_18_plus", "has_internet_and_device", "accepts_unpaid_role"]

DEFAULT_SUB_STATE: Dict[str, Any] = {
    "resume_stage": OnboardingState.ORIENTATION_VIDEO.value,
    "video_acknowledged": False,
    "welcome_shown": False,
    "consent_given": False,
    "welcome_response": None,
    "eligibility_bundled_asked": False,
    "eligibility": {
        "age_18_plus": None,
        "has_internet_and_device": None,
        "accepts_unpaid_role": None,
    },
    "eligibility_pending_negative": {},
    "review_reason": None,
    "email_typo_warned": False,
}

# ── Pattern tables ──────────────────────────────────────────────────────────────
YES_PATTERNS = [
    r"\byes\b", r"\byeah\b", r"\byep\b", r"\byup\b", r"\bok\b", r"\bokay\b",
    r"\bsure\b", r"\bi do\b", r"\bi have\b", r"\bcan do\b", r"\bagree\b",
    r"\bunderstand\b", r"\bcontinue\b", r"\bdone\b", r"\bwatched\b", r"\bready\b",
    r"\bhaan\b", r"\bhaan ji\b", r"\bji\b", r"\bof course\b",
    r"\ball good\b", r"\ball three\b", r"\bconfirm\b", r"\bthat's? right\b",
]
NO_PATTERNS = [
    r"\bno\b", r"\bnope\b", r"\bnot really\b", r"\bdon't\b", r"\bdo not\b",
    r"\bcan't\b", r"\bcannot\b", r"\bunable\b", r"\bnahin\b", r"\bnahi\b",
]
PAUSE_PATTERNS = [r"\bpause\b", r"\blater\b", r"\bnot now\b", r"\bbusy\b", r"\bstop\b"]
RESUME_PATTERNS = [r"\bresume\b", r"\bcontinue\b", r"\bstart\b", r"\bready\b", r"\bback\b"]
CONFIRM_PATTERNS = [
    r"\byes\b", r"\bcorrect\b", r"\bconfirm\b", r"\blooks good\b",
    r"\bright\b", r"\bok\b", r"\bokay\b", r"\ball good\b",
]
EDIT_CONTACT_PATTERNS = [r"\bname\b", r"\bemail\b", r"\bcontact\b", r"\bqualification\b"]

# Reluctance patterns — volunteer hesitates about sharing personal info
RELUCTANCE_PATTERNS = [
    r"\bwhy do you need\b", r"\bwhy is (this|that|it) needed\b",
    r"\bi('d| would) rather not\b", r"\bdon't want to share\b",
    r"\bis (this|it) (safe|secure|private)\b", r"\bprivacy\b",
    r"\bwho (will |can )?(see|access)\b", r"\bwill you share\b",
    r"\bspam\b", r"\bdata\b.*\b(safe|secure)\b",
]

# ── Qualification keywords ──────────────────────────────────────────────────────
QUALIFICATION_PATTERNS = [
    # Degree abbreviations
    r"\b(B\.?E\.?|B\.?Tech|B\.?Sc|B\.?A\.?|B\.?Com|B\.?C\.?A\.?|BBA|BDS|MBBS)\b",
    r"\b(M\.?E\.?|M\.?Tech|M\.?Sc|M\.?A\.?|M\.?Com|M\.?C\.?A\.?|MBA|MDS|MD)\b",
    r"\b(Ph\.?D|Doctorate|Post.?Graduate|Post.?Graduation)\b",
    # Common terms (English)
    r"\b(graduate|graduation|under.?graduate|diploma|engineering|medical|law)\b",
    r"\b(12th|10th|12th pass|10th pass|intermediate|higher secondary|HSC|SSC)\b",
    r"\b(CA|CS|CMA|LLB|LLM|BAMS|BHMS)\b",
    # Hindi/Hinglish terms
    r"\b(snatak|snaatak|dasvi|barahvi|dasvin|barahvin)\b",
    r"\b(graduation complete|degree complete|padhai puri)\b",
]

# ── Email typo detection ────────────────────────────────────────────────────────
COMMON_EMAIL_TYPOS = {
    "gmal.com": "gmail.com", "gmial.com": "gmail.com", "gmaill.com": "gmail.com",
    "gamil.com": "gmail.com", "gnail.com": "gmail.com", "gmail.co": "gmail.com",
    "gmail.con": "gmail.com", "gmail.cm": "gmail.com",
    "yaho.com": "yahoo.com", "yahho.com": "yahoo.com", "yahooo.com": "yahoo.com",
    "yahoo.co": "yahoo.com", "yahoo.con": "yahoo.com",
    "hotmal.com": "hotmail.com", "hotmial.com": "hotmail.com",
    "outloo.com": "outlook.com", "outlok.com": "outlook.com",
    "rediffmal.com": "rediffmail.com", "redifmail.com": "rediffmail.com",
}


def _check_email_typo(email: str) -> Optional[str]:
    """Check if email domain looks like a typo. Returns suggested correction or None."""
    if not email or "@" not in email:
        return None
    domain = email.split("@")[1].lower()
    suggestion = COMMON_EMAIL_TYPOS.get(domain)
    if suggestion:
        return email.split("@")[0] + "@" + suggestion
    return None


class ProfileExtractor:
    """Extract profile information from free-form volunteer messages."""

    NAME_SIGNALS = [
        # English signals
        r"(?:my name is|i'm|i am|call me|this is)\s+([A-Za-z][a-zA-Z'\-]*(?:\s+[A-Za-z][a-zA-Z'\-]*)*)",
        # Hindi/Hinglish signals
        r"(?:naam hai|mera naam|mera naam hai)\s+([A-Za-z][a-zA-Z'\-]*(?:\s+[A-Za-z][a-zA-Z'\-]*)*)",
        # "Name: X" format
        r"(?:name[:\s]+)([A-Za-z][a-zA-Z'\-]*(?:\s+[A-Za-z][a-zA-Z'\-]*)*)",
        # Starts with capital, has comma or "here"
        r"^([A-Z][a-zA-Z'\-]*(?:\s+[A-Z][a-zA-Z'\-]*)*)(?:\s+here|,)",
        # Bare capitalized words (last resort — only for short messages)
        r"^([A-Z][a-zA-Z'\-]*(?:\s+[A-Z][a-zA-Z'\-]*){0,4})$",
    ]
    NAME_STOPWORDS = {
        "and", "or", "but", "hello", "hi", "hey", "want", "would", "like",
        "interested", "back", "ready", "looking", "excited", "happy", "new",
        "available", "sure", "yes", "yeah", "yep", "yup", "ok", "okay", "fine",
        "good", "great", "no", "nope", "nah", "never", "none", "na",
        "cannot", "unable",
        "thanks", "thank", "please", "sorry", "not", "very", "really",
        "just", "also", "here", "there", "from", "with", "about", "that",
        "this", "have", "been", "done", "teaching", "volunteering", "joining",
        "starting", "continuing", "returning", "recommended",
        "main", "mera", "naam", "hai", "ji",
    }
    EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    PHONE_PATTERNS = [
        r"\b(\+?\d{1,3}[-.\s]?\d{10})\b",
        r"\b(\d{10})\b",
        r"\b(\d{3}[-.\s]\d{3}[-.\s]\d{4})\b",
    ]
    QUALIFICATION_FILLER_WORDS = {
        "yes", "no", "not", "maybe", "ok", "okay", "sure", "fine", "good",
        "great", "hi", "hello", "hey", "test", "idk", "dunno", "dont", "do",
        "know", "idea", "sorry", "nothing", "whatever", "please", "thanks",
        "thank", "skip", "later", "um", "uh", "hmm", "i", "im", "we", "you",
        "it", "am", "have", "none",
    }

    def extract_all(self, message: str, existing_fields: Optional[Dict[str, Any]] = None, current_stage: Optional[str] = None) -> Dict[str, Any]:
        existing_fields = existing_fields or {}
        extracted: Dict[str, Any] = {}

        # Phone is always extracted (for auto-population from any message)
        if "phone" not in existing_fields:
            phone = self._extract_phone(message)
            if phone:
                extracted["phone"] = phone

        # During contact_capture: extract ALL missing fields from any message
        # (supports batched responses like "I'm Sowmya, sowmya@gmail.com, 7760131253, B.Tech")
        if current_stage == "contact_capture":
            if "full_name" not in existing_fields:
                name = self._extract_name(message)
                if name:
                    extracted["full_name"] = name

            if "email" not in existing_fields:
                email = self._extract_email(message)
                if email:
                    extracted["email"] = email

            if "phone" not in existing_fields and "phone" not in extracted:
                phone = self._extract_phone(message)
                if phone:
                    extracted["phone"] = phone

            if "qualification" not in existing_fields:
                qual = self._extract_qualification(message)
                if qual:
                    extracted["qualification"] = qual
                else:
                    # Only try free-text fallback if qualification is the ONLY remaining field
                    missing_contact = [f for f in ["full_name", "email", "qualification"] if not existing_fields.get(f) and f not in extracted]
                    if missing_contact == ["qualification"]:
                        candidate = self._plausible_qualification_freetext(message)
                        if candidate:
                            extracted["qualification"] = candidate

        # During eligibility_screening: also extract name + email if offered
        # (user might volunteer info early)
        if current_stage == "eligibility_screening":
            if "full_name" not in existing_fields:
                name = self._extract_name(message)
                if name:
                    extracted["full_name"] = name
            if "email" not in existing_fields:
                email = self._extract_email(message)
                if email:
                    extracted["email"] = email

        return extracted

    NAME_WORD_PATTERN = re.compile(r"^[A-Za-z]+(?:['\-][A-Za-z]+)*$")
    NAME_TITLES = {"mr", "mrs", "ms", "miss", "dr", "shri", "smt", "er"}
    NAME_WORD_MIN_LEN = 2
    NAME_WORD_MAX_LEN = 20
    NAME_MAX_WORDS = 5

    def _extract_name(self, message: str) -> Optional[str]:
        text = message.strip()
        for pattern in self.NAME_SIGNALS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                words = []
                for word in value.split():
                    lower = word.lower()
                    if lower in self.NAME_STOPWORDS:
                        break
                    if lower in self.NAME_TITLES:
                        continue
                    words.append(word)
                if words:
                    candidate = " ".join(
                        self._normalize_name_word(w) for w in words[:self.NAME_MAX_WORDS]
                    )
                    if self._is_valid_name(candidate):
                        return candidate
        return None

    @staticmethod
    def _normalize_name_word(word: str) -> str:
        return word.title() if word.islower() or word.isupper() else word

    def _is_valid_name(self, candidate: str) -> bool:
        words = candidate.split()
        if len(words) < 2 or len(candidate) > 60:
            return False
        for word in words:
            if not (self.NAME_WORD_MIN_LEN <= len(word) <= self.NAME_WORD_MAX_LEN):
                return False
            if not self.NAME_WORD_PATTERN.match(word):
                return False
        return True

    def _extract_email(self, message: str) -> Optional[str]:
        match = re.search(self.EMAIL_PATTERN, message)
        return match.group(0).lower() if match else None

    def _extract_phone(self, message: str) -> Optional[str]:
        for pattern in self.PHONE_PATTERNS:
            match = re.search(pattern, message)
            if match:
                digits = re.sub(r"[^\d+]", "", match.group(1))
                if self._is_plausible_phone(digits):
                    return digits
        return None

    def _is_plausible_phone(self, digits: str) -> bool:
        core = digits[-10:]
        if len(core) < 10:
            return False
        if len(set(core)) == 1:
            return False
        ascending = all(int(core[i + 1]) == (int(core[i]) + 1) % 10 for i in range(len(core) - 1))
        descending = all(int(core[i + 1]) == (int(core[i]) - 1) % 10 for i in range(len(core) - 1))
        if ascending or descending:
            return False
        return True

    def _extract_qualification(self, message: str) -> Optional[str]:
        for pattern in QUALIFICATION_PATTERNS:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        return None

    def _plausible_qualification_freetext(self, message: str) -> Optional[str]:
        stripped = message.strip()
        if not (1 < len(stripped) < 60):
            return None
        if re.search(self.EMAIL_PATTERN, stripped) or re.search(r"\d{10}", stripped):
            return None
        normalized_words = [w for w in (re.sub(r"[^a-z]", "", w.lower()) for w in stripped.split()) if w]
        if not normalized_words:
            return None
        if all(w in self.QUALIFICATION_FILLER_WORDS for w in normalized_words):
            return None
        # Accept if multi-word or contains a digit
        if any(ch.isdigit() for ch in stripped) or len(normalized_words) >= 2:
            return stripped
        # v2: Also accept single recognized education words
        edu_words = {"graduate", "diploma", "degree", "engineering", "medical", "commerce", "arts", "science"}
        if any(w in edu_words for w in normalized_words):
            return stripped
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
        merged["consent_given"] = data.get("consent_given", False)
        merged["eligibility_bundled_asked"] = data.get("eligibility_bundled_asked", False)
        merged["email_typo_warned"] = data.get("email_typo_warned", False)
        return merged
    except (json.JSONDecodeError, ValueError):
        return json.loads(json.dumps(DEFAULT_SUB_STATE))


def _dump_sub_state(sub_state: Dict[str, Any]) -> str:
    return json.dumps({
        "resume_stage": sub_state.get("resume_stage"),
        "video_acknowledged": sub_state.get("video_acknowledged", False),
        "welcome_shown": sub_state.get("welcome_shown", False),
        "consent_given": sub_state.get("consent_given", False),
        "welcome_response": sub_state.get("welcome_response"),
        "eligibility_bundled_asked": sub_state.get("eligibility_bundled_asked", False),
        "eligibility": sub_state.get("eligibility", {}),
        "eligibility_pending_negative": sub_state.get("eligibility_pending_negative", {}),
        "review_reason": sub_state.get("review_reason"),
        "email_typo_warned": sub_state.get("email_typo_warned", False),
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
    """Accept any positive/engaged response as video acknowledgement."""
    lower = message.lower()
    return _matches_any(lower, [
        r"\bdone\b", r"\bwatched\b", r"\bcontinue\b", r"\bready\b",
        r"\bok\b", r"\bokay\b", r"\byes\b", r"\byeah\b", r"\byep\b",
        r"\bnice\b", r"\bwow\b", r"\bgreat\b", r"\bgood\b", r"\bcool\b",
        r"\bawesome\b", r"\bamazing\b", r"\binteresting\b", r"\bloved\b",
        r"\bthanks\b", r"\bthank\b", r"\bgot it\b", r"\bnoted\b",
        r"\bseen\b", r"\bsaw\b", r"\bsure\b", r"\bhaan\b", r"\bji\b",
        r"\baccha\b", r"\bbadhiya\b", r"\bsahi\b", r"\btheek\b",
        r"\bnext\b", r"\bgo ahead\b", r"\blet's go\b", r"\bchalo\b",
    ])


def _is_reluctant(message: str) -> bool:
    """Detect if volunteer is hesitant about sharing personal info."""
    lower = message.lower()
    return _matches_any(lower, RELUCTANCE_PATTERNS)


# ── Eligibility logic ──────────────────────────────────────────────────────────

def _next_eligibility_question(sub_state: Dict[str, Any]) -> Optional[str]:
    eligibility = sub_state.get("eligibility", {})
    for field in ELIGIBILITY_FIELDS:
        if eligibility.get(field) is None:
            return field
    return None


def _apply_eligibility_answers(sub_state: Dict[str, Any], message: str) -> None:
    """Parse eligibility answers — supports both bundled and individual responses."""
    eligibility = dict(sub_state.get("eligibility") or {})
    pending_neg = dict(sub_state.get("eligibility_pending_negative") or {})
    lower = message.lower()

    # If bundled question was asked: ANY response that isn't explicitly negative = all pass
    # This is intentionally permissive — the bundled question is a confirmation, not a test.
    if sub_state.get("eligibility_bundled_asked"):
        explicit_no = _extract_binary_response(message)
        if explicit_no is False:
            # They explicitly said "no" — need to ask individually
            sub_state["eligibility_bundled_asked"] = False
            # Fall through to individual handling below
        else:
            # Anything else (yes, sure, ok, or even just "yeah") = all pass
            # Even if _extract_binary_response returns None (ambiguous), treat as positive
            # because the bundled question was a confirmation ("all good?")
            for field in ELIGIBILITY_FIELDS:
                if eligibility.get(field) is None:
                    eligibility[field] = True
            sub_state["eligibility"] = eligibility
            sub_state["eligibility_pending_negative"] = pending_neg
            return

    # Individual question handling
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

    # Keyword-based detection for internet+device
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

    # Resume from paused
    if current_state == OnboardingState.PAUSED.value and _matches_any(lower, RESUME_PATTERNS):
        return sub_state.get("resume_stage") or OnboardingState.ORIENTATION_VIDEO.value, "Volunteer resumed"

    # Pause from any active state
    if current_state not in (
        OnboardingState.WELCOME.value,
        OnboardingState.ONBOARDING_COMPLETE.value,
        OnboardingState.HUMAN_REVIEW.value,
    ) and _matches_any(lower, PAUSE_PATTERNS):
        return OnboardingState.PAUSED.value, "Volunteer asked to pause"

    # WELCOME: v2 — collapsed to 1-2 turns
    if current_state == OnboardingState.WELCOME.value:
        if not sub_state.get("welcome_shown"):
            # Turn 1: show welcome + ask what brings them here (combined)
            sub_state["welcome_shown"] = True
            sub_state["consent_given"] = True  # implicit — they messaged us
            return current_state, "Showing welcome + asking intent"
        # Turn 2: they responded → capture intent, move to orientation
        return OnboardingState.ORIENTATION_VIDEO.value, "Welcome response received — proceeding to orientation"

    # ORIENTATION VIDEO: wait for user response, then move to eligibility
    if current_state == OnboardingState.ORIENTATION_VIDEO.value:
        if sub_state.get("video_acknowledged"):
            return OnboardingState.ELIGIBILITY_SCREENING.value, "Video acknowledged — proceeding to eligibility"
        return current_state, "Waiting for video acknowledgement"

    # ELIGIBILITY: v2 — bundled first, individual fallback
    if current_state == OnboardingState.ELIGIBILITY_SCREENING.value:
        failed = _eligibility_failed(sub_state)
        if failed:
            sub_state["review_reason"] = failed
            return OnboardingState.HUMAN_REVIEW.value, f"Eligibility not met: {failed}"
        if _all_eligibility_passed(sub_state):
            return OnboardingState.CONTACT_CAPTURE.value, "Eligibility passed"
        return current_state, "Collecting eligibility checks"

    # CONTACT CAPTURE
    if current_state == OnboardingState.CONTACT_CAPTURE.value:
        missing = _stage_missing_fields(current_state, confirmed_fields, sub_state)
        if not missing:
            return OnboardingState.REGISTRATION_REVIEW.value, "Contact details captured"
        return current_state, "Collecting contact details"

    # Legacy redirect
    if current_state == OnboardingState.TEACHING_PROFILE.value:
        return OnboardingState.REGISTRATION_REVIEW.value, "Legacy stage redirected"

    # REGISTRATION REVIEW
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
    merged["welcome_shown"] = sub_state.get("welcome_shown", False)
    merged["consent_given"] = sub_state.get("consent_given", False)
    merged["eligibility_bundled_asked"] = sub_state.get("eligibility_bundled_asked", False)
    merged["email_typo_warned"] = sub_state.get("email_typo_warned", False)
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
        logger.info(f"[{request.session_id}] sub_state: welcome_shown={sub_state.get('welcome_shown')}, video_ack={sub_state.get('video_acknowledged')}, elig={sub_state.get('eligibility')}")

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

        # Fetch confirmed fields from MCP
        missing_result = await domain_client.get_missing_fields(request.session_id)
        _, confirmed_fields = _unwrap_missing_fields(missing_result)
        logger.info(f"[{request.session_id}] confirmed_fields: {list(confirmed_fields.keys())}")

        # Auto-populate phone from WhatsApp channel_metadata
        if "phone" not in confirmed_fields:
            ch_meta = (session_state.channel_metadata or {})
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

        # Extract profile fields from user message
        extracted_fields = profile_extractor.extract_all(
            request.user_message,
            existing_fields=confirmed_fields,
            current_stage=current_state,
        )
        logger.info(f"[{request.session_id}] extracted (stage={current_state}): {extracted_fields}")

        # Email typo detection — check before saving
        email_typo_suggestion = None
        if "email" in extracted_fields and not sub_state.get("email_typo_warned"):
            suggestion = _check_email_typo(extracted_fields["email"])
            if suggestion:
                email_typo_suggestion = suggestion
                sub_state["email_typo_warned"] = True
                # Don't save the typo email yet — let the LLM ask for confirmation
                del extracted_fields["email"]

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

        # Update stage-specific sub_state
        self._update_stage_specific_sub_state(current_state, request.user_message, sub_state)

        # Persist motivation to profile if captured this turn
        if sub_state.get("_save_motivation"):
            motivation = sub_state.pop("_save_motivation")
            await domain_client.save_confirmed_fields(request.session_id, {"motivation": motivation})
            logger.info(f"[{request.session_id}] motivation saved to profile: {motivation[:50]}...")

        # Determine next state (deterministic)
        next_state, transition_reason = _determine_next_state(
            current_state=current_state,
            user_message=request.user_message,
            confirmed_fields=confirmed_fields,
            sub_state=sub_state,
        )
        logger.info(f"[{request.session_id}] state: {current_state} → {next_state} ({transition_reason})")

        if next_state != current_state:
            telemetry_events.append(
                TelemetryEvent(
                    session_id=request.session_id,
                    event_type=EventType.STATE_TRANSITION,
                    agent=AgentType.ONBOARDING,
                    data={"from_state": current_state, "to_state": next_state, "reason": transition_reason},
                )
            )

        await self._persist_profile_side_effects(request, next_state, sub_state)

        # Build prompt context — include extra signals for the LLM
        prompt_fields = _build_prompt_fields(confirmed_fields, sub_state)
        if email_typo_suggestion:
            prompt_fields["email_typo_suggestion"] = email_typo_suggestion
        if _is_reluctant(request.user_message):
            prompt_fields["volunteer_reluctant"] = True

        next_missing_fields = _stage_missing_fields(next_state, confirmed_fields, sub_state)
        logger.info(f"[{request.session_id}] LLM: stage={next_state}, missing={next_missing_fields}")

        assistant_message = await llm_adapter.generate_response(
            stage=next_state,
            messages=request.conversation_history,
            user_message=request.user_message,
            missing_fields=next_missing_fields,
            confirmed_fields=prompt_fields,
            memory_context=memory_context,
        )

        # Persist sub_state
        updated_sub_state = _dump_sub_state(sub_state)
        if next_state == current_state:
            await domain_client.advance_state(request.session_id, new_state=current_state, sub_state=updated_sub_state)

        # Memory update
        conversation_with_new = request.conversation_history + [
            {"role": "user", "content": request.user_message},
            {"role": "assistant", "content": assistant_message},
        ]
        summary_result = await self.memory_service.process_conversation_update(
            session_id=str(request.session_id),
            conversation=conversation_with_new,
            domain_client=domain_client,
        )

        # Build response
        handoff_event = None
        completion_status = "in_progress"
        response_missing_fields = next_missing_fields
        response_new_facts = {}  # Facts for v2 orchestrator to merge into volunteer record

        # ── Cross-domain signal extraction ────────────────────────────────────
        # Capture preference/intent signals from ANY user message, even during
        # onboarding. These get written to the volunteer fact-store so downstream
        # agents (selection, engagement, fulfillment) don't re-ask.
        cross_domain_facts = self._extract_cross_domain_signals(request.user_message)
        if cross_domain_facts:
            response_new_facts.update(cross_domain_facts)
            logger.info(f"[{request.session_id}] cross-domain signals: {list(cross_domain_facts.keys())}")

        logger.info(f"[{request.session_id}] ── TURN END ── state={next_state}")

        if next_state == OnboardingState.ONBOARDING_COMPLETE.value:
            completion_status = "complete"
            final_summary = await self.memory_service.process_conversation_update(
                session_id=str(request.session_id), conversation=conversation_with_new, domain_client=domain_client,
            )

            # ── Create volunteer record in the persistent fact-store ──────────
            onboarding_facts = {
                "identity_verified": True,
                "adult_eligibility": True,
                "internet_device": True,
                "unpaid_consent": True,
                "registered": True,
                "platform_status": "active",
            }

            volunteer_record = await domain_client.create_volunteer_record(
                full_name=confirmed_fields.get("full_name"),
                phone=confirmed_fields.get("phone"),
                email=confirmed_fields.get("email"),
                facts=onboarding_facts,
            )
            if volunteer_record.get("status") == "success":
                logger.info(f"[{request.session_id}] Volunteer record created: {volunteer_record.get('volunteer', {}).get('id', 'unknown')}")
            else:
                logger.warning(f"[{request.session_id}] Failed to create volunteer record: {volunteer_record}")

            # Keep handoff for backward compat (legacy path still uses it)
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

            # new_facts for v2 orchestrator (fact-based routing)
            response_new_facts = onboarding_facts
            # Include motivation so selection agent can pre-score it
            if sub_state.get("welcome_response"):
                response_new_facts["motivation"] = sub_state["welcome_response"]

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
            new_facts=response_new_facts,
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
            # Capture the volunteer's motivation/intent response and persist it
            if sub_state.get("welcome_shown") and user_message and user_message not in ("__handoff__", "__auto_continue__"):
                motivation_text = user_message.strip()[:500]
                sub_state["welcome_response"] = motivation_text
                # Persist motivation to volunteer profile so selection can pre-score it
                sub_state["_save_motivation"] = motivation_text
        if current_state == OnboardingState.ORIENTATION_VIDEO.value:
            # Any reply to the video message = acknowledged
            if user_message and user_message not in ("__handoff__", "__auto_continue__"):
                sub_state["video_acknowledged"] = True
        if current_state == OnboardingState.ELIGIBILITY_SCREENING.value:
            # Mark bundled as asked after first entry (so next turn processes the answer)
            if not sub_state.get("eligibility_bundled_asked"):
                eligibility = sub_state.get("eligibility") or {}
                all_unanswered = all(eligibility.get(f) is None for f in ELIGIBILITY_FIELDS)
                if all_unanswered:
                    # First time here — bundled prompt will be shown. Set the flag
                    # so the NEXT turn's _apply_eligibility_answers knows to accept a bundled "yes"
                    sub_state["eligibility_bundled_asked"] = True
                    return  # Don't try to parse the user message as an eligibility answer yet
            _apply_eligibility_answers(sub_state, user_message)

    async def _persist_profile_side_effects(self, request: AgentTurnRequest, next_state: str, sub_state: Dict[str, Any]) -> None:
        if next_state == OnboardingState.CONTACT_CAPTURE.value and _all_eligibility_passed(sub_state):
            await domain_client.save_confirmed_fields(request.session_id, {"eligibility_status": "eligible"})
            return
        if next_state == OnboardingState.HUMAN_REVIEW.value:
            review_reason = sub_state.get("review_reason") or "eligibility_review_required"
            await domain_client.save_confirmed_fields(request.session_id, {"eligibility_status": "review_pending"})
            await domain_client.log_event(request.session_id, "onboarding_review_pending", agent=AgentType.ONBOARDING.value, data={"reason": review_reason})

    def _extract_cross_domain_signals(self, message: str) -> Dict[str, Any]:
        """
        Extract preference/intent signals from any user message.
        These are NOT onboarding fields — they're facts for downstream agents.
        Captures: subject preferences, day preferences, time preferences, grade preferences.
        """
        if not message or message in ("__handoff__", "__auto_continue__"):
            return {}

        lower = message.lower()
        facts: Dict[str, Any] = {}
        preferences: Dict[str, Any] = {}

        # Subject preferences
        subjects = []
        if re.search(r"\benglish\b", lower):
            subjects.append("english")
        if re.search(r"\bhindi\b", lower):
            subjects.append("hindi")
        if re.search(r"\b(math|maths|mathematics)\b", lower):
            subjects.append("mathematics")
        if re.search(r"\bscience\b", lower):
            subjects.append("science")
        if subjects:
            preferences["subjects"] = subjects

        # Day preferences
        days = []
        if re.search(r"\b(weekend|weekends|saturday|sunday)\b", lower):
            if "saturday" in lower:
                days.append("saturday")
            if "sunday" in lower:
                days.append("sunday")
            if not days:  # "weekends" without specific day
                days = ["saturday", "sunday"]
        if re.search(r"\b(weekday|weekdays|monday|tuesday|wednesday|thursday|friday)\b", lower):
            for d in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
                if d in lower:
                    days.append(d)
            if not days:  # "weekdays" without specific day
                days = ["monday", "tuesday", "wednesday", "thursday", "friday"]
        if days:
            preferences["days"] = days

        # Time preferences
        time_match = re.search(r"\b(\d{1,2})\s*(?:am|pm)\s*(?:to|-)\s*(\d{1,2})\s*(?:am|pm)\b", lower)
        if time_match:
            preferences["time"] = time_match.group(0)
        elif re.search(r"\bmorning\b", lower):
            preferences["time"] = "morning"
        elif re.search(r"\bevening\b", lower):
            preferences["time"] = "evening"
        elif re.search(r"\bafternoon\b", lower):
            preferences["time"] = "afternoon"

        # Grade preferences
        grades = []
        for g in re.findall(r"\bgrade\s*(\d+)\b", lower):
            grades.append(g)
        for g in re.findall(r"\bclass\s*(\d+)\b", lower):
            grades.append(g)
        if grades:
            preferences["grades"] = grades

        if preferences:
            facts["preferences"] = preferences

        return facts


onboarding_agent_service = OnboardingAgentService()
