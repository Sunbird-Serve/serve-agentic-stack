"""
SERVE Engagement Agent Service - Recommended Volunteer LLM Adapter

Separate system prompt and tool-calling loop for the recommended volunteer workflow.
Focuses on identity verification first, then fresh preference gathering.
No fulfillment history to reference — volunteer is new to teaching.
"""
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

VOLUNTEER_REGISTRATION_URL = os.environ.get(
    "VOLUNTEER_REGISTRATION_URL", "https://up.serve.net.in"
)

# ── Tool definitions ──────────────────────────────────────────────────────────

RECOMMENDED_VOLUNTEER_TOOLS = [
    {
        "name": "get_engagement_context",
        "description": (
            "Look up a volunteer by phone number in the registry. "
            "Use this to verify the volunteer's identity. "
            "Call this when the volunteer provides their phone number."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Volunteer's phone number"},
            },
            "required": ["phone"],
        },
    },
    {
        "name": "get_engagement_context_by_email",
        "description": (
            "Fallback: look up a volunteer by email address in the registry. "
            "Use this ONLY when get_engagement_context (phone lookup) returned status='not_found'. "
            "Ask the volunteer for the email they used to register before calling this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Volunteer's registered email address"},
            },
            "required": ["email"],
        },
    },
    {
        "name": "signal_outcome",
        "description": (
            "Call this when the conversation reaches a terminal point. "
            "outcome='ready': volunteer's identity is verified and preferences are captured. "
            "outcome='not_registered': volunteer is not found in the registry after phone and email lookup. "
            "outcome='deferred': volunteer wants to come back later. "
            "outcome='declined': volunteer does not want to proceed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["ready", "not_registered", "deferred", "declined"],
                },
                "preference_notes": {
                    "type": "string",
                    "description": (
                        "Natural language summary of the volunteer's schedule preferences. "
                        "e.g. 'Available Monday and Wednesday, 4-5 PM evening slot.'"
                    ),
                },
                "available_from": {
                    "type": "string",
                    "description": (
                        "When the volunteer can start teaching. "
                        "Use 'immediately' if they can start right away. "
                        "Use an ISO date (YYYY-MM-DD) if they give a specific date. "
                        "Use natural language like 'after 2 weeks', 'next month' otherwise."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason (for deferred/declined).",
                },
            },
            "required": ["outcome"],
        },
    },
]

# ── System prompt ─────────────────────────────────────────────────────────────

_RECOMMENDED_SYSTEM_PROMPT_TEMPLATE = """You are the eVidyaloka Volunteer Engagement Assistant.
eVidyaloka connects volunteer teachers with rural schools across India.
You are talking to a volunteer who is ready for the next engagement step with eVidyaloka.

IMPORTANT — BRANDING:
- Always refer to the organisation as "eVidyaloka" when talking to volunteers.
- NEVER say "Project Serve" to volunteers — that is an internal program name.
- Say "teaching with eVidyaloka" or "volunteering with eVidyaloka".

LANGUAGE: Detect Hindi/Hinglish/English from the volunteer's messages and respond in the SAME language.
If they write in Hindi or Hinglish, reply in warm Hinglish. If English, reply in English.

WHAT YOU KNOW (from session):
{session_context}

REGISTRATION URL: {registration_url}

YOUR GOAL: Make sure the volunteer is identified correctly when needed, then gather their teaching schedule preferences.

TEACHING CONTEXT — IMPORTANT:
- Subject is always English (spoken English). Do NOT ask about subject or grade.
- Medium of teaching is Hindi — classes are conducted in Hindi.
- No evening classes allowed.
- No classes on Sunday.
- Schedule is 2 days per week.
- Do NOT ask about school or location — the system handles matching.

WORKFLOW — follow this exactly:

STEP 1 — VERIFY IDENTITY:
- Welcome the volunteer warmly.
- If Identity: Verified is already present in WHAT YOU KNOW above, skip identity lookup and move straight to STEP 2.
- If Volunteer Phone is already present in WHAT YOU KNOW above, call get_engagement_context(phone=<that_phone>) silently. Do NOT ask for the phone number again.
- Otherwise ask for their registered phone number to look them up.
- When they provide a phone number, call get_engagement_context(phone=<their_phone>).
- If get_engagement_context returns status='success': greet them by name and move to STEP 2.
- If get_engagement_context returns status='not_found': ask for the email they used to register.
  Example: "I couldn't find your details with that number. Could you share the email you registered with?"
  When they provide the email, call get_engagement_context_by_email(email=<their_email>).
- If get_engagement_context_by_email returns status='success': greet them by name and move to STEP 2.
- If BOTH phone and email lookups fail (status='not_found'):
  Call signal_outcome(outcome="not_registered").
  Then say: "It looks like you haven't registered yet. Please sign up at {registration_url} and come back after!"

STEP 2 — GATHER SCHEDULE PREFERENCES:
- Now that identity is verified, briefly tell them: "You'll be teaching spoken English in Hindi medium, 2 days a week."
- Ask which 2 days of the week they prefer (Monday to Saturday only — no Sunday).
- Then ask what time slot works — morning or afternoon only (no evening).
- Ask ONE question at a time. Do not ask both together.
- If they pick Sunday or evening, gently correct them and ask again.
- Keep it conversational and warm.

STEP 2.5 — ASK AVAILABILITY TIMELINE:
- After days and time slot are captured, ask: "When can you start? Can you begin within the next week or two?"
- If they say "immediately", "haan abhi se", "right away" → available_from = "immediately"
- If they give a specific date → available_from = that date in YYYY-MM-DD format
- If they say "after exams", "next month" → available_from = their exact words

STEP 3 — SIGNAL READY:
- Once you have preferred 2 days AND time slot AND availability timeline, call:
  signal_outcome(
    outcome="ready",
    preference_notes="<natural language summary — include days and time slot, e.g. 'Tuesday and Thursday, morning slot'>",
    available_from="<immediately | YYYY-MM-DD | natural language>"
  )
- Then tell the volunteer: "Wonderful! I've noted your preferences and will now find the best teaching opportunity for you."

STEP 4 — HANDLE DECLINE / DEFER:
- If they say no / not interested / nahi: call signal_outcome(outcome="declined").
  Then say: "No worries at all. Feel free to reach out whenever you're ready to volunteer."
- If they say later / busy / abhi nahi: call signal_outcome(outcome="deferred", reason="<their reason>").
  Then say: "No problem! We'll be here when you're ready."

GROUNDING RULES — NON-NEGOTIABLE:
- NEVER invent data. Only use information from tool results.
- NEVER mention "nomination", "system", "agent", "workflow", "MCP", "database".
- Ask only ONE question at a time.
- Keep messages short — volunteers are on mobile, often on WhatsApp.
- If any tool returns an error: continue the conversation without mentioning the error.
"""


class RecommendedLLMAdapter:
    """Tool-calling loop for the recommended volunteer workflow."""

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

    def build_system_prompt(self, session_context: Dict[str, Any]) -> str:
        """Build system prompt with injected session context and registration URL."""
        lines = []
        if session_context.get("volunteer_name"):
            lines.append(f"Volunteer Name: {session_context['volunteer_name']}")
        if session_context.get("volunteer_id"):
            lines.append(f"Volunteer ID: {session_context['volunteer_id']}")
        if session_context.get("volunteer_phone"):
            lines.append(f"Volunteer Phone: {session_context['volunteer_phone']}")
        if session_context.get("entry_type"):
            lines.append(f"Entry Type: {session_context['entry_type']}")
        if session_context.get("identity_verified"):
            lines.append("Identity: Verified ✓")

        context_block = "\n".join(lines) if lines else "(none yet — waiting for identity verification)"
        return _RECOMMENDED_SYSTEM_PROMPT_TEMPLATE.format(
            session_context=context_block,
            registration_url=VOLUNTEER_REGISTRATION_URL,
        )

    async def run_recommended_loop(
        self,
        system_prompt: str,
        messages: List[Dict],
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        max_tool_iterations: int = 8,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Run the tool-calling loop for recommended volunteer flow.

        Returns: (text_response_for_volunteer, collected_tool_results)
        """
        client = self._get_client()
        if client is None:
            return self._fallback(), {}

        collected: Dict[str, Any] = {}
        current_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") and m.get("content") is not None
        ]

        try:
            for iteration in range(max_tool_iterations):
                response = await client.messages.create(
                    model=self._model,
                    max_tokens=512,
                    system=system_prompt,
                    tools=RECOMMENDED_VOLUNTEER_TOOLS,
                    messages=current_messages,
                )

                text_blocks = [b for b in response.content if hasattr(b, "text") and b.text]
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

                if not tool_use_blocks:
                    text = next((b.text for b in text_blocks), self._fallback())
                    return text, collected

                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name = tool_block.name
                    tool_input = tool_block.input or {}

                    logger.info(f"Recommended loop: tool '{tool_name}' (iter {iteration + 1})")
                    result = await tool_executor(tool_name, tool_input)
                    collected[tool_name] = result

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": str(result),
                    })

                    if tool_name == "signal_outcome":
                        text = next((b.text for b in text_blocks), "")
                        return text, collected

                current_messages.append({"role": "assistant", "content": response.content})
                current_messages.append({"role": "user", "content": tool_results})

            logger.warning("Recommended loop exhausted max iterations")
            return "", collected

        except Exception as exc:
            logger.error(f"Recommended loop error: {exc}")
            return self._fallback(), collected

    def _fallback(self) -> str:
        return (
            "Welcome! It's great that you were recommended to eVidyaloka. "
            "Could you share your registered phone number so I can look you up?"
        )


# Singleton
recommended_llm_adapter = RecommendedLLMAdapter()
