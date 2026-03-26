"""
SERVE Engagement Agent Service - LLM Adapter

Plain text generation for each engagement stage.
Same pattern as the need agent's llm_adapter.

TODO (contributor):
  - Refine stage prompts to match the actual engagement flow
  - Add tool-calling loop if any stage needs autonomous resolution
  - Add extract_* helpers if structured field extraction is needed
"""
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Project Serve context ─────────────────────────────────────────────────────

_SERVE_CONTEXT = """
You are the Project Serve Volunteer Engagement Assistant.
Project Serve connects volunteer teachers with rural schools across India.
You are talking to a returning volunteer who has previously registered with Project Serve.

Communication guidelines:
- Warm, friendly, and appreciative — they've volunteered before
- Keep messages short and conversational
- Ask only ONE question at a time
- Detect language (Hindi/Hinglish/English) and respond in the same language
"""

# ── Stage prompts ─────────────────────────────────────────────────────────────

_STAGE_PROMPTS: Dict[str, str] = {
    "re_engaging": (
        "Welcome the volunteer back warmly. Acknowledge their previous contribution. "
        "Let them know you're here to help them get back into teaching. "
        "Ask if they're ready to continue or if anything has changed since they last volunteered."
        # TODO: surface their last activity (school, subject, grade) from profile context
    ),
    "profile_refresh": (
        "Check if the volunteer's availability or skills have changed. "
        "Ask one question at a time — start with availability (days/hours per week). "
        "If nothing has changed, confirm and move forward."
        # TODO: show current profile values and ask for confirmation or updates
    ),
    "matching_ready": (
        "The volunteer's profile is up to date. "
        "Let them know the team will start matching them with a school. "
        "Thank them for their continued commitment."
        # TODO: trigger matching agent handoff
    ),
    "paused": (
        "Acknowledge the volunteer wants to pause. "
        "Confirm their progress is saved and they can return anytime."
    ),
}


class EngagementLLMAdapter:
    """LLM adapter for the engagement agent — plain text generation per stage."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = (
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")
        )
        self._model: str = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self._api_key:
                return None
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError:
                logger.warning("anthropic package not installed")
        return self._client

    async def generate_response(
        self,
        stage: str,
        messages: List[Dict[str, str]],
        user_message: str,
        volunteer_context: Optional[Dict] = None,
    ) -> str:
        """Generate a conversational response for the given stage."""
        client = self._get_client()
        if client is None:
            return self._fallback(stage)

        stage_instr = _STAGE_PROMPTS.get(stage, _STAGE_PROMPTS["re_engaging"])
        system = f"{_SERVE_CONTEXT}\n\n{stage_instr}"

        if volunteer_context:
            name = volunteer_context.get("volunteer_name") or volunteer_context.get("full_name", "")
            if name:
                system += f"\n\nVOLUNTEER: {name}"
            last_active = volunteer_context.get("last_active_at", "")
            if last_active:
                system += f"\nLast active: {last_active}"

        convo = ""
        for msg in messages[-6:]:
            role = "Volunteer" if msg.get("role") == "user" else "Project Serve"
            convo += f"{role}: {msg.get('content', '')}\n"
        full_msg = f"{convo}\nVolunteer: {user_message}" if convo else user_message

        try:
            response = await client.messages.create(
                model=self._model,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": full_msg}],
            )
            return next(
                (b.text for b in response.content if hasattr(b, "text") and b.text),
                self._fallback(stage),
            )
        except Exception as exc:
            logger.error(f"LLM error (stage={stage}): {exc}")
            return self._fallback(stage)

    def _fallback(self, stage: str) -> str:
        fallbacks = {
            "re_engaging":     "Welcome back! Great to hear from you again. Are you ready to start teaching?",
            "profile_refresh": "Has anything changed since you last volunteered — availability or subjects?",
            "matching_ready":  "Your profile is all set. We'll start matching you with a school soon!",
            "paused":          "No problem! Your progress is saved. Come back whenever you're ready.",
        }
        return fallbacks.get(stage, "How can I help you today?")


# Singleton
llm_adapter = EngagementLLMAdapter()
