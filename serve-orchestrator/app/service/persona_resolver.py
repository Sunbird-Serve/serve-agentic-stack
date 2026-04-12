"""
SERVE Orchestrator - Persona Resolver

Determines WHO the actor is before the orchestrator creates or resumes a session.
This is the first step in the "ORCHESTRATOR DISCOVERY" layer:

  Resolve Persona  ←  (this module)
  Resolve Session State
  Resolve Intent

Resolution priority (evaluated top-to-bottom, first match wins):

  1. Explicit override — channel sent persona in the request           (~0ms)
  2. Trigger type     — SCHEDULED / SYSTEM_TRIGGER → SYSTEM            (~0ms)
  3. Actor registry lookup — ask MCP for a volunteer/coordinator record (~async)
       a. coordinator record found          → NEED_COORDINATOR
       b. volunteer found, inactive >90d    → INACTIVE_VOLUNTEER
       c. volunteer found, active           → RETURNING_VOLUNTEER
  4. Default                               → NEW_VOLUNTEER             (~0ms)

Design constraints:
  - resolve() never raises; failures produce NEW_VOLUNTEER with low confidence.
  - The MCP lookup is best-effort: if the tool is unavailable or returns an
    error, we fall through to the default rather than blocking the pipeline.
  - Resolution only runs for brand-new sessions (event.session_id is None);
    resumed sessions already carry their persona from persistent storage.
"""
import re
import logging
from typing import Optional

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

        # ── 1b. Returning volunteer self-identification phrase ──────────────
        # Detect common phrases a returning volunteer might use to identify
        # themselves, and route directly to the engagement agent.
        _RETURNING_RE = re.compile(
            r"\b(returning volunteer|i (am|'m) a returning|i have (taught|volunteered) before|"
            r"i (taught|volunteered) (last year|before|previously|earlier)|"
            r"wapas aaya|wapas aayi|pehle padhaya|pehle volunteer|"
            r"phir se volunteer|dobara volunteer)\b",
            re.IGNORECASE,
        )
        if _RETURNING_RE.search(event.payload):
            logger.info(
                f"Returning volunteer self-identified via phrase for actor={event.actor_id!r}"
            )
            return PersonaResolutionResult(
                persona=PersonaType.RETURNING_VOLUNTEER,
                confidence=0.95,
                source="explicit",
                metadata={"from": "self_identification_phrase", "matched": event.payload[:80]},
            )

        # ── 1c. Recommended volunteer self-identification phrase ────────────
        # Detect common phrases a recommended/referred volunteer might use.
        # Positioned after returning volunteer check so returning takes priority.
        _RECOMMENDED_RE = re.compile(
            r"\b(i was recommended|someone recommended|recommended volunteer|"
            r"mujhe recommend kiya|recommend kiya gaya|"
            r"referral|i got a referral|referred by|"
            r"kisi ne bataya|kisi ne bheja)\b",
            re.IGNORECASE,
        )
        if _RECOMMENDED_RE.search(event.payload):
            logger.info(
                f"Recommended volunteer self-identified via phrase for actor={event.actor_id!r}"
            )
            return PersonaResolutionResult(
                persona=PersonaType.RECOMMENDED_VOLUNTEER,
                confidence=0.95,
                source="explicit",
                metadata={"from": "recommendation_phrase", "matched": event.payload[:80]},
            )

        # ── 2. System / scheduled trigger → SYSTEM persona ─────────────────
        if event.trigger_type in (TriggerType.SCHEDULED, TriggerType.SYSTEM_TRIGGER):
            return PersonaResolutionResult(
                persona=PersonaType.SYSTEM,
                confidence=1.0,
                source="trigger_type",
                metadata={"trigger_type": event.trigger_type.value},
            )

        # ── 3. Actor registry lookup via MCP ───────────────────────────────
        resolution = await self._lookup_actor(event.actor_id, event.channel.value)
        if resolution is not None:
            return resolution

        # ── 4. Default: no record found → brand-new volunteer ──────────────
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
        the tool is unavailable, so the caller falls through to the default.
        """
        # Import here to avoid circular imports; domain_client is a module-level
        # singleton so the import is O(1) after the first call.
        from app.clients.domain_client import domain_client

        result = await domain_client.lookup_actor(actor_id=actor_id, channel=channel)
        status = result.get("status")

        if status == "not_found":
            return None

        if status == "error":
            logger.warning(
                f"lookup_actor returned error for actor={actor_id!r}: "
                f"{result.get('error')}. Falling back to NEW_VOLUNTEER."
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
            f"for actor={actor_id!r}. Falling back to NEW_VOLUNTEER."
        )
        return None


# Singleton — import and use directly
persona_resolver = PersonaResolver()
