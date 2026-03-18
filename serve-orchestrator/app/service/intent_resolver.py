"""
SERVE Orchestrator - Intent Resolver

Determines WHY the user is interacting before deciding HOW to respond.
This is the architectural bridge between the Channel Adapter layer (normalised
input) and the Agent Routing layer (which agent handles it).

Resolution priority (evaluated top-to-bottom, first match wins):

  1. Structural — trigger type, session status   (deterministic, ~0ms)
  2. Keyword match on the payload text           (regex, ~0ms)
  3. Default: CONTINUE_WORKFLOW

Design constraints:
  - Pure function — no I/O, no side effects, fully synchronous.
  - resolve() never raises; bad inputs produce CONTINUE_WORKFLOW with low
    confidence rather than crashing the pipeline.
  - Future: replace or supplement keyword matching with a lightweight
    Claude-based classifier once intent patterns are well understood.
"""
import re
import logging
from typing import Optional

from app.schemas import (
    NormalizedEvent,
    TriggerType,
    SessionStatus,
    IntentType,
    IntentResult,
)
from app.schemas.contracts import SessionContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyword tables
# Each pattern is evaluated against the full (lowercased) message text.
# Escalation is checked before SEEK_HELP so "talk to a person" resolves
# to ESCALATE rather than SEEK_HELP.
# ---------------------------------------------------------------------------

_ESCALATE_RE = re.compile(
    r"\b(human|real person|talk to someone|speak to|speak with|connect me|"
    r"supervisor|manager|support team|escalate|helpline)\b",
    re.IGNORECASE,
)

_RESTART_RE = re.compile(
    r"\b(restart|start over|start again|begin again|reset|from scratch|"
    r"new session|start fresh)\b",
    re.IGNORECASE,
)

_PAUSE_RE = re.compile(
    r"\b(pause|stop|bye|goodbye|exit|quit|not now|later|come back later|"
    r"take a break|brb|ttyl|talk later|gotta go)\b",
    re.IGNORECASE,
)

_HELP_RE = re.compile(
    r"\b(help|stuck|confused|don['\u2019]?t understand|not sure|what do i|"
    r"how do i|what should|lost|unclear|explain|can you explain|"
    r"i don['\u2019]?t get|what does)\b",
    re.IGNORECASE,
)

_RESUME_RE = re.compile(
    r"\b(resume|continue|pick up|where was i|carry on|i['\u2019]?m back|"
    r"back again|let['\u2019]?s continue)\b",
    re.IGNORECASE,
)


def _first_match(pattern: re.Pattern, text: str) -> str:
    """Return the first matching token (for diagnostic logging)."""
    m = pattern.search(text)
    return m.group(0) if m else ""


class IntentResolver:
    """
    Stateless, rule-based intent classifier.

    Public API: ``resolve(event, session_context) → IntentResult``
    """

    def resolve(
        self,
        event: NormalizedEvent,
        session_context: Optional[SessionContext],
    ) -> IntentResult:
        """
        Classify the intent of a NormalizedEvent given the current session state.

        Args:
            event:           The normalised inbound event from the channel adapter.
            session_context: The resolved/created session, or None on first contact.

        Returns:
            IntentResult containing intent, confidence, an optional pre-canned
            suggested_response for terminal intents, and diagnostic metadata.
        """
        try:
            return self._classify(event, session_context)
        except Exception as exc:
            logger.warning(f"IntentResolver.resolve failed unexpectedly: {exc}. Defaulting.")
            return IntentResult(
                intent=IntentType.CONTINUE_WORKFLOW,
                confidence=0.5,
                metadata={"signal": "error_fallback", "error": str(exc)},
            )

    def _classify(
        self,
        event: NormalizedEvent,
        session_context: Optional[SessionContext],
    ) -> IntentResult:
        payload = event.payload.strip()

        # ── 1. No session → brand-new contact
        if session_context is None:
            return IntentResult(
                intent=IntentType.START_WORKFLOW,
                confidence=1.0,
                metadata={"signal": "no_session"},
            )

        # ── 2. Scheduled / system trigger → always continue workflow
        if event.trigger_type in (TriggerType.SCHEDULED, TriggerType.SYSTEM_TRIGGER):
            return IntentResult(
                intent=IntentType.CONTINUE_WORKFLOW,
                confidence=0.95,
                metadata={"signal": "system_trigger", "trigger_type": event.trigger_type.value},
            )

        # ── 3. Paused session → user is resuming
        if session_context.status == SessionStatus.PAUSED.value:
            return IntentResult(
                intent=IntentType.RESUME_SESSION,
                confidence=0.95,
                metadata={"signal": "paused_session"},
                suggested_response=(
                    "Welcome back! Let's pick up where we left off. "
                    "You were in the middle of your volunteer onboarding — ready to continue?"
                ),
            )

        # ── 4. Escalation (check before HELP — "talk to a person" should win)
        if _ESCALATE_RE.search(payload):
            return IntentResult(
                intent=IntentType.ESCALATE,
                confidence=0.88,
                metadata={
                    "signal": "escalation_keywords",
                    "matched": _first_match(_ESCALATE_RE, payload),
                },
                suggested_response=(
                    "I understand you'd like to speak with a person. "
                    "I've flagged your session for our support team and someone will be "
                    "in touch shortly. Your progress has been saved."
                ),
            )

        # ── 5. Restart / start-over
        if _RESTART_RE.search(payload):
            return IntentResult(
                intent=IntentType.RESTART,
                confidence=0.88,
                metadata={
                    "signal": "restart_keywords",
                    "matched": _first_match(_RESTART_RE, payload),
                },
                suggested_response=(
                    "Of course! Let's start fresh. "
                    "Welcome — I'm here to help you join eVidyaloka as a volunteer. "
                    "What would you like to do?"
                ),
            )

        # ── 6. Pause / goodbye
        if _PAUSE_RE.search(payload):
            return IntentResult(
                intent=IntentType.PAUSE_SESSION,
                confidence=0.83,
                metadata={
                    "signal": "pause_keywords",
                    "matched": _first_match(_PAUSE_RE, payload),
                },
                suggested_response=(
                    "No problem! I've saved your progress. "
                    "Come back anytime and we'll pick up right where you left off. 👋"
                ),
            )

        # ── 7. Help / confusion
        if _HELP_RE.search(payload):
            return IntentResult(
                intent=IntentType.SEEK_HELP,
                confidence=0.80,
                metadata={
                    "signal": "help_keywords",
                    "matched": _first_match(_HELP_RE, payload),
                },
            )

        # ── 8. Explicit resume language while session is already active
        if _RESUME_RE.search(payload):
            return IntentResult(
                intent=IntentType.RESUME_SESSION,
                confidence=0.75,
                metadata={
                    "signal": "resume_keywords",
                    "matched": _first_match(_RESUME_RE, payload),
                },
            )

        # ── 9. Default: continue the active workflow
        return IntentResult(
            intent=IntentType.CONTINUE_WORKFLOW,
            confidence=0.90,
            metadata={"signal": "default"},
        )


# Singleton — import and use directly
intent_resolver = IntentResolver()
