"""
SERVE Engagement Agent Service - LLM Adapter (L3.5)

Tool-calling loop modelled on the fulfillment agent's L4 loop.
The LLM owns all branching logic. The state machine only enforces terminal conditions.

Flow for active volunteers who fulfilled needs:
  1. LLM silently calls get_engagement_context to load history + nominations.
  2. If already nominated → signal_outcome(outcome="already_active").
  3. Welcome back with real history. Ask if they want to continue.
  4. Collect school + slot preference conversationally (not a form).
  5. signal_outcome(outcome="ready", preference_notes=..., continuity=..., preferred_need_id=...)
     OR signal_outcome(outcome="deferred") / signal_outcome(outcome="declined").
"""
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Tool definitions ──────────────────────────────────────────────────────────

ENGAGEMENT_TOOLS = [
    {
        "name": "get_engagement_context",
        "description": (
            "Load the volunteer's fulfillment history and profile by their phone number. "
            "Call this FIRST and SILENTLY — do not tell the volunteer you are doing a lookup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "Volunteer's WhatsApp/mobile number"},
            },
            "required": ["phone"],
        },
    },
    {
        "name": "get_engagement_context_by_email",
        "description": (
            "Fallback: load the volunteer's fulfillment history by their email address. "
            "Use this ONLY when get_engagement_context (phone lookup) returned status='not_found'. "
            "Ask the volunteer for the email they used to register on eVidyaloka before calling this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Volunteer's email used for eVidyaloka registration"},
            },
            "required": ["email"],
        },
    },
    {
        "name": "signal_outcome",
        "description": (
            "Call this when the conversation reaches a terminal point. "
            "outcome='ready': volunteer confirmed they want to continue and preferences are captured. "
            "outcome='already_active': volunteer already has an active nomination — no action needed. "
            "outcome='deferred': volunteer wants to come back later. "
            "outcome='declined': volunteer does not want to continue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["ready", "already_active", "deferred", "declined"],
                },
                "preference_notes": {
                    "type": "string",
                    "description": (
                        "Natural language summary of the volunteer's preferences. "
                        "e.g. 'Prefers same school as before (Govt School Lucknow). "
                        "Flexible on time slot. Open to Grade 6 English again.'"
                    ),
                },
                "continuity": {
                    "type": "string",
                    "enum": ["same", "different"],
                    "description": "Whether the volunteer wants the same school/need or is open to a different one.",
                },
                "preferred_need_id": {
                    "type": "string",
                    "description": "need_id from fulfillment history if volunteer wants the same need.",
                },
                "available_from": {
                    "type": "string",
                    "description": (
                        "When the volunteer can start teaching. "
                        "Use 'immediately' if they can start right away. "
                        "Use an ISO date (YYYY-MM-DD) if they give a specific date. "
                        "Use natural language like 'after 2 weeks', 'next month', 'after exams' otherwise."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason (for deferred/declined/already_active).",
                },
            },
            "required": ["outcome"],
        },
    },
]

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You are the eVidyaloka Volunteer Engagement Assistant.
eVidyaloka connects volunteer teachers with rural schools across India.
You are talking to a returning volunteer who has previously taught with eVidyaloka.

IMPORTANT — BRANDING:
- Always refer to the organisation as "eVidyaloka" when talking to volunteers.
- NEVER say "Project Serve" to volunteers — that is an internal program name used by coordinators only.
- Say "teaching with eVidyaloka" or "volunteering with eVidyaloka", not "Project Serve".

LANGUAGE: Detect Hindi/Hinglish/English from the volunteer's messages and respond in the SAME language.
If they write in Hindi or Hinglish, reply in warm Hinglish. If English, reply in English.

WHAT YOU KNOW (from session):
{session_context}

YOUR GOAL: Re-engage this volunteer for the current teaching cycle.

WORKFLOW — follow this exactly:

STEP 1 — LOAD CONTEXT (silent, no user interaction):
- If "Last fulfillment:" is already present in WHAT YOU KNOW above, skip this step — context is already loaded.
- Otherwise call get_engagement_context(phone=<volunteer_phone>) once and silently.
- Do NOT tell the volunteer you are doing a lookup.
- If get_engagement_context returns status='not_found': ask the volunteer warmly for the email they used to register on eVidyaloka.
  Example: "I couldn't find your details with this number. Could you share the email you used when you registered on eVidyaloka?"
  When they provide the email, call get_engagement_context_by_email(email=<their_email>) silently.
- If both phone and email lookups fail, say: "Welcome back! I wasn't able to find your previous details, but no worries — would you like to continue volunteering this year?"
# TEMPORARILY DISABLED: active nomination check
# - If has_active_nomination=True: call signal_outcome(outcome="already_active", reason="volunteer already has an active nomination").

STEP 2 — WELCOME BACK:
- Greet them warmly by name (use volunteer_name from the tool result).
- Reference their ACTUAL history from the tool result:
  - school_name (extracted from needPurpose — e.g. "Government Vocational Junior College Nampally")
  - need_purpose or need_name for subject/grade context
  - days and time_slots for schedule context
- If fulfillment_history is empty, say: "Welcome back! Would you like to continue volunteering this year?"
- Ask ONE question: would they like to continue teaching this year?
- Example (English): "Welcome back, Priya! Last year you taught at Government Vocational Junior College Nampally on Tuesdays and Wednesdays — would you like to continue teaching with eVidyaloka this year?"
- Example (Hinglish): "Wapas aaye, Priya ji! Pichle saal aapne Government Vocational Junior College Nampally mein eVidyaloka ke saath padhaya tha — kya is saal bhi continue karna chahenge?"

STEP 3 — CAPTURE PREFERENCES (if they say yes):
- Ask about school preference: same school as before, or open to a different one?
- Ask about time slot: same timing, or flexible?
- Ask ONE question at a time. Do not ask both together.
- If they say "same everything" or "haan same hai" — treat both as confirmed.
- If they are "fully flexible" or "kahi bhi" — continuity = "different".

STEP 3.5 — ASK AVAILABILITY TIMELINE:
- After school and time preferences are captured, ask: "When can you start? Can you begin within the next week or two?"
- If they say "immediately", "haan abhi se", "right away", "kal se" → available_from = "immediately"
- If they give a specific date → available_from = that date in YYYY-MM-DD format
- If they say "after exams", "next month", "2-3 weeks" → available_from = their exact words
- Ask this as a separate question. Do NOT combine it with preference questions.

STEP 4 — SIGNAL READY:
- Once you have school preference AND slot preference AND availability timeline, call:
  signal_outcome(
    outcome="ready",
    preference_notes="<natural language summary of their preferences>",
    continuity="same" or "different",
    preferred_need_id="<need_id from history if continuity=same, else omit>",
    available_from="<immediately | YYYY-MM-DD | natural language>"
  )
- Then tell the volunteer: "Perfect. I've noted your preference and will now find the best match for you."

STEP 5 — HANDLE DECLINE / DEFER:
- If they say no / not interested / nahi: call signal_outcome(outcome="declined").
  Then say: "Thank you for letting us know. We won't push further — come back whenever you're ready."
- If they say later / busy / abhi nahi: call signal_outcome(outcome="deferred").
  Then say: "No problem. We'll reconnect when your timing is better."

GROUNDING RULES — NON-NEGOTIABLE:
- NEVER invent history. Only use data from get_engagement_context tool result.
- If get_engagement_context returns no history or status=not_found, say: "Welcome back! Would you like to continue volunteering this year?"
- NEVER mention "nomination", "system", "agent", "workflow", "MCP", "database".
- Ask only ONE question at a time.
- Keep messages short — volunteers are on mobile, often on WhatsApp.
- If any tool returns an error: continue the conversation without mentioning the error.
"""


class EngagementLLMAdapter:
    """L3.5 tool-calling loop for the engagement agent."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = (
            os.environ.get("ANTHROPIC_API_KEY")
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
        """Build system prompt with injected volunteer session context."""
        lines = []
        if session_context.get("volunteer_name"):
            lines.append(f"Volunteer Name: {session_context['volunteer_name']}")
        if session_context.get("volunteer_id"):
            lines.append(f"Volunteer ID: {session_context['volunteer_id']}")
        if session_context.get("volunteer_phone"):
            lines.append(f"Volunteer Phone: {session_context['volunteer_phone']}")
        if session_context.get("last_active_at"):
            lines.append(f"Last active: {session_context['last_active_at']}")

        # For new volunteers from selection — no fulfillment history
        entry_type = session_context.get("entry_type")
        if entry_type == "selected_new_volunteer":
            lines.append("Entry: NEW volunteer (just completed onboarding + selection). No prior teaching history.")
            lines.append("IMPORTANT: Identity is already verified. Do NOT ask for phone number or do any lookup.")
            lines.append("Go directly to understanding their teaching preferences — subject, time, availability.")

        # Surface cached history if already loaded (avoids redundant tool call on resume)
        history = session_context.get("fulfillment_history") or []
        if history:
            latest = history[0]
            parts = []
            if latest.get("school_name"):
                parts.append(f"school={latest['school_name']}")
            elif latest.get("need_purpose"):
                parts.append(f"need={latest['need_purpose']}")
            if latest.get("subjects"):
                parts.append(f"subjects={', '.join(latest['subjects'])}")
            if latest.get("grade_levels"):
                parts.append(f"grades={', '.join(str(g) for g in latest['grade_levels'])}")
            if latest.get("days"):
                parts.append(f"days={latest['days']}")
            if latest.get("time_slots"):
                slots = latest["time_slots"]
                if slots:
                    s = slots[0]
                    parts.append(f"time={s.get('startTime','')}-{s.get('endTime','')}")
            if latest.get("need_id"):
                parts.append(f"need_id={latest['need_id']}")
            if parts:
                lines.append(f"Last fulfillment: {'; '.join(parts)}")

        context_block = "\n".join(lines) if lines else "(none yet — call get_engagement_context)"
        return _SYSTEM_PROMPT_TEMPLATE.format(session_context=context_block)

    async def run_engagement_loop(
        self,
        system_prompt: str,
        messages: List[Dict],
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        max_tool_iterations: int = 8,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Run the L3.5 engagement tool-calling loop.

        Runs Claude with conversation history, executing tools until Claude
        produces a text response OR calls signal_outcome.

        Returns: (text_response_for_volunteer, collected_tool_results)
        """
        client = self._get_client()
        if client is None:
            return self._fallback(), {}

        collected: Dict[str, Any] = {}
        # Strip any extra fields — Anthropic only accepts role + content
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
                    tools=ENGAGEMENT_TOOLS,
                    messages=current_messages,
                )

                text_blocks = [b for b in response.content if hasattr(b, "text") and b.text]
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

                # No tool calls — Claude produced a message for the volunteer
                if not tool_use_blocks:
                    text = next((b.text for b in text_blocks), self._fallback())
                    return text, collected

                # Execute all tool calls
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name = tool_block.name
                    tool_input = tool_block.input or {}

                    logger.info(f"Engagement loop: tool '{tool_name}' (iter {iteration + 1})")
                    result = await tool_executor(tool_name, tool_input)
                    collected[tool_name] = result

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": str(result),
                    })

                    # signal_outcome terminates the loop immediately
                    if tool_name == "signal_outcome":
                        text = next((b.text for b in text_blocks), "")
                        return text, collected

                current_messages.append({"role": "assistant", "content": response.content})
                current_messages.append({"role": "user", "content": tool_results})

            logger.warning("Engagement loop exhausted max iterations")
            return "", collected

        except Exception as exc:
            logger.error(f"Engagement loop error: {exc}")
            return self._fallback(), collected

    def _fallback(self) -> str:
        return (
            "Welcome back! Would you like to continue volunteering this year? "
            "We'd love to have you back."
        )


# Singleton
llm_adapter = EngagementLLMAdapter()
