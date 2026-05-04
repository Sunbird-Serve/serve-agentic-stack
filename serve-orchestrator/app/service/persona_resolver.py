"""
SERVE Orchestrator - Persona Resolver

Determines WHO the actor is before the orchestrator creates or resumes a session.
This is the first step in the "ORCHESTRATOR DISCOVERY" layer:

  Resolve Persona  ←  (this module)
  Resolve Session State
  Resolve Intent

Resolution priority (evaluated top-to-bottom, first match wins):

  1. Explicit override — channel sent persona in the request           (~0ms)
  2. New volunteer phrase detection (regex, no greetings)              (~0ms)
  3. Returning volunteer phrase detection (regex)                      (~0ms)
  4. Recommended volunteer phrase detection (regex)                    (~0ms)
  5. Need coordinator phrase detection (regex)                         (~0ms)
  6. System / scheduled trigger                                       (~0ms)
  7. Actor registry lookup — ask MCP for a volunteer/coordinator record (~async)
       a. coordinator record found          → NEED_COORDINATOR
       b. volunteer found, inactive >90d    → INACTIVE_VOLUNTEER
       c. volunteer found, active           → RETURNING_VOLUNTEER
  8. LLM classifier fallback — single cheap Claude call               (~async)
  9. Default                               → NEW_VOLUNTEER             (~0ms)

Design constraints:
  - resolve() never raises; failures produce NEW_VOLUNTEER with low confidence.
  - The MCP lookup is best-effort: if the tool is unavailable or returns an
    error, we fall through to the LLM classifier rather than blocking.
  - The LLM classifier is best-effort: if it fails or returns low confidence,
    we fall through to the default.
  - Resolution only runs for brand-new sessions (event.session_id is None);
    resumed sessions already carry their persona from persistent storage.
"""
import json
import os
import re
import logging
from typing import Optional

import httpx

from app.schemas import (
    NormalizedEvent,
    PersonaType,
    TriggerType,
    PersonaResolutionResult,
)

logger = logging.getLogger(__name__)

# Volunteers inactive for longer than this threshold are classified as
# INACTIVE_VOLUNTEER so the engagement agent can focus on re-activation.
_INACTIVE_THRESHOLD_DAYS = 90


# ── LLM classifier config ──────────────────────────────────────────────────────
_LLM_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
_LLM_MODEL = os.environ.get("PERSONA_LLM_MODEL", "claude-haiku-4-5-20251001")
_LLM_TIMEOUT = float(os.environ.get("PERSONA_LLM_TIMEOUT", "5"))
_LLM_API_URL = "https://api.anthropic.com/v1/messages"
_LLM_MIN_CONFIDENCE = 0.6  # Ignore LLM result below this threshold

_PERSONA_CLASSIFIER_PROMPT = """You are a routing classifier for eVidyaloka, a volunteer education platform.

Given a user's first message, classify them into exactly ONE of these personas:

1. **new_volunteer** — Someone who wants to sign up / register / start volunteering for the first time. They have no prior history. Generic greetings like "hi", "hello", "I want to help" also fall here.

2. **returning_volunteer** — Someone who has volunteered or taught before and is coming back. They reference past experience with eVidyaloka or teaching in general.

3. **recommended_volunteer** — Someone who was referred or recommended by another person. They mention a friend, colleague, or someone told them about this.

4. **need_coordinator** — A school coordinator or teacher who wants to register a teaching need, request a volunteer for their school, or manage school-related needs.

Respond with ONLY a JSON object, no other text:
{"persona": "<one of the four values above>", "confidence": <0.0 to 1.0>, "reason": "<one short sentence>"}

If the message is ambiguous or a generic greeting with no clear signal, return new_volunteer with confidence 0.7."""


# ── Regex patterns ──────────────────────────────────────────────────────────────

# New volunteer — explicit intent to sign up / register / start volunteering.
# Excludes generic greetings (hi, hello, namaste) since those are ambiguous —
# a returning volunteer or coordinator could also start with "hi".
_NEW_VOLUNTEER_RE = re.compile(
    r"\b("
    # English — direct signup intent
    r"i want to (volunteer|teach|sign up|register|join|help teach|start volunteering)"
    r"|sign me up|how (do|can) i (join|volunteer|register|sign up|start)"
    r"|i('?d| would) like to (volunteer|teach|join|register|help)"
    r"|i('?m| am) (new|interested|looking to volunteer|looking to teach)"
    r"|new volunteer|first time volunteer"
    r"|i want to (become|be) a volunteer"
    r"|can i (volunteer|teach|join|register|sign up)"
    r"|tell me (about|more about) volunteer"
    r"|how to (volunteer|teach|join|register|sign up)"
    r"|interested in (volunteering|teaching)"
    # Hindi / Hinglish
    r"|volunteer karna (hai|chahta|chahti|chahte)"
    r"|padhana (chahta|chahti|chahte|hai)"
    r"|join karna (hai|chahta|chahti)"
    r"|register karna (hai|chahta|chahti)"
    r"|main volunteer (banana|banna) chahta"
    r"|mujhe volunteer karna hai"
    r"|volunteer (banna|banana) hai"
    r"|kaise (volunteer|join|register) (karu|karun|kare|karein)"
    r"|naya volunteer"
    r")\b",
    re.IGNORECASE,
)

# Returning volunteer — covers English, Hindi, Hinglish
_RETURNING_RE = re.compile(
    r"\b("
    # English — formal
    r"returning volunteer|i (am|'m) a returning"
    r"|i have (taught|volunteered) before"
    r"|i (taught|volunteered) (last year|before|previously|earlier)"
    # English — casual / natural
    r"|i used to (volunteer|teach)"
    r"|i'?ve volunteered (before|earlier|previously|with you)"
    r"|i was a volunteer"
    r"|i taught (here|with you|at evidyaloka|at e.?vidyaloka|for you|kids|children|students)"
    r"|i'?m (coming|back) (to volunteer|to teach|again)"
    r"|back to (volunteer|teach)"
    r"|i already (registered|signed up|have an account)"
    r"|i (signed up|registered) (before|earlier|previously|last year|already)"
    r"|i have an account"
    r"|i'?m an existing volunteer"
    r"|i volunteered (last|this) (year|semester|term|month)"
    r"|i taught (last|this) (year|semester|term|month)"
    # Hindi / Hinglish
    r"|wapas aaya|wapas aayi|wapas aaya hoon|wapas aayi hoon"
    r"|pehle padhaya|pehle volunteer"
    r"|phir se volunteer|dobara volunteer"
    r"|maine pehle (padhaya|volunteer kiya)"
    r"|main pehle volunteer (tha|thi)"
    r"|pehle se registered"
    r"|mera account hai"
    r"|main (pehle|pahle) (padha chuka|padha chuki|volunteer kar chuka|volunteer kar chuki)"
    r")\b",
    re.IGNORECASE,
)

# Recommended / referred volunteer — covers English, Hindi, Hinglish
_RECOMMENDED_RE = re.compile(
    r"\b("
    # English — formal
    r"i was recommended|someone recommended"
    r"|recommended volunteer"
    r"|referral|i got a referral|referred by"
    # English — casual / natural
    r"|my friend told me|a friend (suggested|told|recommended)"
    r"|someone told me (about|to join|to sign up)"
    r"|i heard about (this|you|evidyaloka|e.?vidyaloka) from"
    r"|i was told to (join|sign up|volunteer|register)"
    r"|got to know (from|through) (a friend|someone|my)"
    r"|i came through a referral"
    r"|referred to me"
    r"|a (friend|colleague|teacher|person) (asked|told|suggested) me"
    r"|my (friend|colleague|teacher) (sent|referred|recommended) me"
    # Hindi / Hinglish
    r"|mujhe recommend kiya|recommend kiya gaya"
    r"|kisi ne bataya|kisi ne bheja"
    r"|mere dost ne bataya|friend ne (suggest|recommend) kiya"
    r"|kisi ne bola|kisi ne kaha"
    r"|mere (friend|dost|colleague) ne (bataya|bheja|bola)"
    r"|referral se aaya|referral se aayi"
    r")\b",
    re.IGNORECASE,
)

# Need coordinator — covers English, Hindi, Hinglish
_COORDINATOR_RE = re.compile(
    r"\b("
    # English — formal
    r"register a need|create a need|post a need|raise a need|submit a need"
    r"|i'?m a coordinator|i am the coordinator|school coordinator"
    r"|need coordinator"
    # English — casual / natural
    r"|need for (my|our|the) school"
    r"|teacher needed|we need a (volunteer|teacher)"
    r"|looking for a (volunteer|teacher) for (my|our|the) school"
    r"|i want to (register|create|raise|post|submit) a (need|request)"
    r"|volunteer (needed|required) for (my|our|the) school"
    r"|i need a teacher|we need a teacher"
    r"|request a volunteer|request a teacher"
    r"|i (run|manage|coordinate) a school"
    r"|i'?m (from|at|with) a school"
    # Hindi / Hinglish
    r"|need register karna (hai|chahta|chahti)"
    r"|main coordinator hoon"
    r"|school ke liye (need|teacher|volunteer)"
    r"|hamari school (mein|me) teacher chahiye"
    r"|volunteer chahiye"
    r"|teacher chahiye (school|class) ke liye"
    r"|need (banana|banani|dalna|dalani) hai"
    r"|school ke liye request"
    r")\b",
    re.IGNORECASE,
)


class PersonaResolver:
    """
    Async persona classifier — determines the actor's role before session creation.

    Public API: ``await resolve(event) → PersonaResolutionResult``
    """

    async def resolve(self, event: NormalizedEvent) -> PersonaResolutionResult:
        """
        Classify the persona of the actor who sent this NormalizedEvent.

        This should be called only for new sessions (event.session_id is None).
        For resumed sessions the orchestrator restores persona from persistent
        storage instead of re-resolving it.

        Args:
            event: The normalised inbound event from the channel adapter.

        Returns:
            PersonaResolutionResult with persona, confidence, source, and
            diagnostic metadata.  Never raises.
        """
        try:
            return await self._classify(event)
        except Exception as exc:
            logger.warning(
                f"PersonaResolver.resolve failed unexpectedly: {exc}. "
                f"Defaulting to NEW_VOLUNTEER for actor={event.actor_id!r}."
            )
            return PersonaResolutionResult(
                persona=PersonaType.NEW_VOLUNTEER,
                confidence=0.5,
                source="error_fallback",
                metadata={"error": str(exc)},
            )

    async def _classify(self, event: NormalizedEvent) -> PersonaResolutionResult:
        # ── 1. Explicit persona override from the channel ──────────────────
        if event.persona:
            logger.debug(
                f"Persona explicit override: {event.persona.value!r} "
                f"for actor={event.actor_id!r}"
            )
            return PersonaResolutionResult(
                persona=event.persona,
                confidence=1.0,
                source="explicit",
                metadata={"from": "channel_request"},
            )

        # ── 2. New volunteer explicit intent phrase ───────────────────────
        if _NEW_VOLUNTEER_RE.search(event.payload):
            logger.info(
                f"New volunteer self-identified via phrase for actor={event.actor_id!r}"
            )
            return PersonaResolutionResult(
                persona=PersonaType.NEW_VOLUNTEER,
                confidence=0.90,
                source="regex",
                metadata={"from": "new_volunteer_phrase", "matched": event.payload[:80]},
            )

        # ── 3. Returning volunteer self-identification phrase ──────────────
        if _RETURNING_RE.search(event.payload):
            logger.info(
                f"Returning volunteer self-identified via phrase for actor={event.actor_id!r}"
            )
            return PersonaResolutionResult(
                persona=PersonaType.RETURNING_VOLUNTEER,
                confidence=0.95,
                source="regex",
                metadata={"from": "self_identification_phrase", "matched": event.payload[:80]},
            )

        # ── 4. Recommended volunteer self-identification phrase ────────────
        if _RECOMMENDED_RE.search(event.payload):
            logger.info(
                f"Recommended volunteer self-identified via phrase for actor={event.actor_id!r}"
            )
            return PersonaResolutionResult(
                persona=PersonaType.RECOMMENDED_VOLUNTEER,
                confidence=0.95,
                source="regex",
                metadata={"from": "recommendation_phrase", "matched": event.payload[:80]},
            )

        # ── 5. Need coordinator self-identification phrase ─────────────────
        if _COORDINATOR_RE.search(event.payload):
            logger.info(
                f"Need coordinator self-identified via phrase for actor={event.actor_id!r}"
            )
            return PersonaResolutionResult(
                persona=PersonaType.NEED_COORDINATOR,
                confidence=0.90,
                source="regex",
                metadata={"from": "coordinator_phrase", "matched": event.payload[:80]},
            )

        # ── 6. System / scheduled trigger → SYSTEM persona ─────────────────
        if event.trigger_type in (TriggerType.SCHEDULED, TriggerType.SYSTEM_TRIGGER):
            return PersonaResolutionResult(
                persona=PersonaType.SYSTEM,
                confidence=1.0,
                source="trigger_type",
                metadata={"trigger_type": event.trigger_type.value},
            )

        # ── 7. Actor registry lookup via MCP ───────────────────────────────
        resolution = await self._lookup_actor(event.actor_id, event.channel.value)
        if resolution is not None:
            return resolution

        # ── 8. LLM classifier fallback ─────────────────────────────────────
        llm_result = await self._llm_classify(event.payload)
        if llm_result is not None:
            logger.info(
                f"LLM classifier resolved persona={llm_result.persona.value!r} "
                f"confidence={llm_result.confidence:.2f} for actor={event.actor_id!r}"
            )
            return llm_result

        # ── 9. Default: no record found → brand-new volunteer ──────────────
        logger.debug(
            f"No actor record found for actor={event.actor_id!r} "
            f"channel={event.channel.value!r}. Defaulting to NEW_VOLUNTEER."
        )
        return PersonaResolutionResult(
            persona=PersonaType.NEW_VOLUNTEER,
            confidence=0.80,
            source="default",
            metadata={"reason": "no_actor_record_found"},
        )

    async def _lookup_actor(
        self,
        actor_id: str,
        channel: str,
    ) -> Optional[PersonaResolutionResult]:
        """
        Call the MCP actor lookup tool and translate the result to a
        PersonaResolutionResult.  Returns None when no record is found or
        the tool is unavailable, so the caller falls through to the LLM classifier.
        """
        from app.clients.domain_client import domain_client

        result = await domain_client.lookup_actor(actor_id=actor_id, channel=channel)
        status = result.get("status")

        if status == "not_found":
            return None

        if status == "error":
            logger.warning(
                f"lookup_actor returned error for actor={actor_id!r}: "
                f"{result.get('error')}. Falling through to LLM classifier."
            )
            return None

        if status != "success":
            return None

        data = result.get("data", {})
        actor_type = data.get("actor_type")

        # ── Coordinator record ──────────────────────────────────────────────
        if actor_type == "coordinator":
            return PersonaResolutionResult(
                persona=PersonaType.NEED_COORDINATOR,
                confidence=0.95,
                source="actor_lookup",
                metadata={
                    "actor_type": "coordinator",
                    "coordinator_id": data.get("coordinator_id"),
                    "school_id": data.get("school_id"),
                },
            )

        # ── Volunteer record ────────────────────────────────────────────────
        if actor_type == "volunteer":
            last_active_days: Optional[int] = data.get("last_active_days")

            if (
                last_active_days is not None
                and last_active_days > _INACTIVE_THRESHOLD_DAYS
            ):
                return PersonaResolutionResult(
                    persona=PersonaType.INACTIVE_VOLUNTEER,
                    confidence=0.90,
                    source="actor_lookup",
                    metadata={
                        "actor_type": "volunteer",
                        "volunteer_id": data.get("volunteer_id"),
                        "last_active_days": last_active_days,
                        "onboarding_complete": data.get("onboarding_complete"),
                    },
                )

            return PersonaResolutionResult(
                persona=PersonaType.RETURNING_VOLUNTEER,
                confidence=0.95,
                source="actor_lookup",
                metadata={
                    "actor_type": "volunteer",
                    "volunteer_id": data.get("volunteer_id"),
                    "last_active_days": last_active_days,
                    "onboarding_complete": data.get("onboarding_complete"),
                },
            )

        # Unknown actor_type in response — treat as unrecognised
        logger.warning(
            f"lookup_actor returned unrecognised actor_type={actor_type!r} "
            f"for actor={actor_id!r}. Falling through to LLM classifier."
        )
        return None

    async def _llm_classify(self, payload: str) -> Optional[PersonaResolutionResult]:
        """
        Use a lightweight Claude model to classify the user's first message
        into a persona type. Returns None on any failure or low confidence,
        so the caller falls through to the default.
        """
        if not _LLM_API_KEY:
            logger.debug("No ANTHROPIC_API_KEY set — skipping LLM persona classifier.")
            return None

        # Don't waste an LLM call on very short / empty messages
        stripped = payload.strip()
        if len(stripped) < 2:
            return None

        try:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
                response = await client.post(
                    _LLM_API_URL,
                    headers={
                        "x-api-key": _LLM_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": _LLM_MODEL,
                        "max_tokens": 150,
                        "system": _PERSONA_CLASSIFIER_PROMPT,
                        "messages": [
                            {"role": "user", "content": stripped[:500]},
                        ],
                    },
                )
                response.raise_for_status()

            body = response.json()
            text = body.get("content", [{}])[0].get("text", "").strip()

            # Parse the JSON response from the LLM
            parsed = json.loads(text)
            persona_str = parsed.get("persona", "").strip().lower()
            confidence = float(parsed.get("confidence", 0.0))
            reason = parsed.get("reason", "")

            # Map string to PersonaType
            persona_map = {
                "new_volunteer": PersonaType.NEW_VOLUNTEER,
                "returning_volunteer": PersonaType.RETURNING_VOLUNTEER,
                "recommended_volunteer": PersonaType.RECOMMENDED_VOLUNTEER,
                "need_coordinator": PersonaType.NEED_COORDINATOR,
            }

            persona = persona_map.get(persona_str)
            if persona is None:
                logger.warning(f"LLM classifier returned unknown persona: {persona_str!r}")
                return None

            if confidence < _LLM_MIN_CONFIDENCE:
                logger.debug(
                    f"LLM classifier confidence {confidence:.2f} below threshold "
                    f"{_LLM_MIN_CONFIDENCE} for persona={persona_str!r}. Ignoring."
                )
                return None

            return PersonaResolutionResult(
                persona=persona,
                confidence=min(confidence, 0.90),  # Cap at 0.90 — LLM is never as sure as explicit
                source="llm_classifier",
                metadata={
                    "llm_model": _LLM_MODEL,
                    "llm_persona": persona_str,
                    "llm_confidence": confidence,
                    "llm_reason": reason,
                },
            )

        except httpx.TimeoutException:
            logger.warning("LLM persona classifier timed out — falling through to default.")
            return None
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"LLM persona classifier parse error: {e} — falling through to default.")
            return None
        except Exception as e:
            logger.warning(f"LLM persona classifier failed: {e} — falling through to default.")
            return None


# Singleton — import and use directly
persona_resolver = PersonaResolver()
