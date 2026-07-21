"""
SERVE Orchestrator — Action Resolver

Determines what the volunteer wants to do (desired_action) from:
1. Regex pattern matching on their message (fast, deterministic)
2. Contextual inference from their facts (no message needed)
3. LLM fallback (for ambiguous messages)

Returns one of:
  teach_english | teach_hindi | teach_mathematics | teach_science |
  find_opportunity | register | update_profile | mentoring | unknown
"""
import json
import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── LLM config ──────────────────────────────────────────────────────────────────
_PROVIDER_KEY_VARS = (
    "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
    "OPENAI_API_KEY", "GEMINI_API_KEY", "EMERGENT_LLM_KEY",
)
_LLM_API_KEY = next((os.environ[k] for k in _PROVIDER_KEY_VARS if os.environ.get(k)), "")
if os.environ.get("EMERGENT_LLM_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["EMERGENT_LLM_KEY"]
_LLM_MODEL = os.environ.get("ACTION_LLM_MODEL") or os.environ.get("PERSONA_LLM_MODEL", "claude-haiku-4-5-20251001")
_LLM_TIMEOUT = float(os.environ.get("ACTION_LLM_TIMEOUT", "5"))

# ── Regex patterns ──────────────────────────────────────────────────────────────

_ACTION_PATTERNS = [
    # English teaching
    (r"\b(teach|teaching)\b.*\b(english|eng)\b", "teach_english"),
    (r"\b(english)\b.*\b(class|teach|teaching|tutor)\b", "teach_english"),
    (r"\benglish (padhana|sikhana)\b", "teach_english"),

    # Hindi teaching
    (r"\b(teach|teaching)\b.*\b(hindi)\b", "teach_hindi"),
    (r"\b(hindi)\b.*\b(class|teach|teaching|padhana)\b", "teach_hindi"),
    (r"\bhindi (padhana|sikhana)\b", "teach_hindi"),

    # Mathematics
    (r"\b(teach|teaching)\b.*\b(math|maths|mathematics)\b", "teach_mathematics"),
    (r"\b(math|maths|mathematics)\b.*\b(class|teach)\b", "teach_mathematics"),

    # Science
    (r"\b(teach|teaching)\b.*\b(science|vigyan)\b", "teach_science"),

    # Find opportunity / another class
    (r"\b(another|more|new|next)\b.*\b(class|opportunity|assignment|need)\b", "find_opportunity"),
    (r"\b(find|get|show)\b.*\b(opportunity|class|assignment|match)\b", "find_opportunity"),
    (r"\b(ek aur|doosri|nayi)\b.*\b(class|opportunity)\b", "find_opportunity"),

    # Registration intent
    (r"\b(register|sign up|join|volunteer karna|banna)\b", "register"),

    # Update profile
    (r"\b(update|change|edit|modify)\b.*\b(profile|details|name|email|phone)\b", "update_profile"),

    # Mentoring
    (r"\b(mentor|mentoring|career guidance|counsel)\b", "mentoring"),
]


def _regex_resolve(message: str) -> Optional[str]:
    """Try regex patterns. Returns action or None."""
    lower = message.lower().strip()
    for pattern, action in _ACTION_PATTERNS:
        if re.search(pattern, lower):
            return action
    return None


def _contextual_resolve(facts: Dict[str, Any]) -> Optional[str]:
    """Infer action from volunteer's current state without analyzing the message."""
    # Not registered → they're here to register
    if not facts.get("registered"):
        return "register"

    # Has preferences + ready_now + no message signal → probably wants a match
    preferences = facts.get("preferences") or {}
    if preferences.get("willing_to_act") == "ready_now":
        commitments = facts.get("commitments") or []
        active = [c for c in commitments if c.get("status") in ("active", "nominated")]
        if not active:
            return "find_opportunity"

    return None


_ACTION_CLASSIFIER_PROMPT = """You are classifying a volunteer's intent for eVidyaloka, an education volunteer platform.

Given the volunteer's message and their current status, classify their intent into exactly ONE of these actions:

- teach_english — wants to teach English
- teach_hindi — wants to teach Hindi
- teach_mathematics — wants to teach math
- teach_science — wants to teach science
- find_opportunity — wants another/new teaching opportunity
- register — wants to sign up / register
- update_profile — wants to change their details
- mentoring — wants to do career mentoring
- unknown — can't determine (generic greeting, unclear intent)

Volunteer's current status: {status_summary}

Respond with ONLY a JSON object:
{"action": "<one of the values above>", "confidence": <0.0 to 1.0>}

If the message is a generic greeting ("hi", "hello") with no clear intent signal, return unknown with confidence 0.8."""


async def _llm_resolve(message: str, facts: Dict[str, Any]) -> Optional[str]:
    """LLM fallback for ambiguous messages."""
    if not _LLM_API_KEY:
        return None

    stripped = message.strip()
    if len(stripped) < 2:
        return None

    # Build status summary for context
    status_parts = []
    if facts.get("registered"):
        status_parts.append("registered")
    if facts.get("credentials"):
        cats = list(facts["credentials"].keys())
        status_parts.append(f"assessed for: {', '.join(cats)}")
    if facts.get("preferences", {}).get("subjects"):
        status_parts.append(f"prefers: {', '.join(facts['preferences']['subjects'])}")
    status_summary = "; ".join(status_parts) if status_parts else "new user, no history"

    try:
        import litellm
        litellm.drop_params = True

        response = await litellm.acompletion(
            model=_LLM_MODEL,
            messages=[
                {"role": "system", "content": _ACTION_CLASSIFIER_PROMPT.format(status_summary=status_summary)},
                {"role": "user", "content": stripped[:300]},
            ],
            max_tokens=100,
            timeout=_LLM_TIMEOUT,
        )
        text = response.choices[0].message.content.strip()
        parsed = json.loads(text)
        action = parsed.get("action", "unknown")
        confidence = float(parsed.get("confidence", 0.0))

        valid_actions = {
            "teach_english", "teach_hindi", "teach_mathematics", "teach_science",
            "find_opportunity", "register", "update_profile", "mentoring", "unknown",
        }
        if action in valid_actions and confidence >= 0.6:
            logger.info(f"Action LLM resolved: {action} (confidence={confidence:.2f})")
            return action

        return None

    except Exception as e:
        logger.warning(f"Action LLM classifier failed: {e}")
        return None


async def resolve_desired_action(
    message: str,
    facts: Dict[str, Any],
) -> str:
    """
    Determine what the volunteer wants to do.

    Resolution order:
    1. Regex patterns on the message
    2. Contextual inference from facts
    3. LLM fallback
    4. Default: "unknown"
    """
    # 1. Regex
    regex_result = _regex_resolve(message)
    if regex_result:
        logger.debug(f"Action resolved via regex: {regex_result}")
        return regex_result

    # 2. Context
    context_result = _contextual_resolve(facts)
    if context_result:
        logger.debug(f"Action resolved via context: {context_result}")
        return context_result

    # 3. LLM fallback
    llm_result = await _llm_resolve(message, facts)
    if llm_result:
        return llm_result

    # 4. Default
    return "unknown"
