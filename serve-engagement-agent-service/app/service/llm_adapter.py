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
            "Load the volunteer's fulfillment history, active nominations, and profile. "
            "Call this FIRST and SILENTLY — do not tell the volunteer you are doing a lookup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "volunteer_id": {"type": "string", "description": "Serve Registry volunteer osid"},
            },
            "required": ["volunteer_id"],
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

_SYSTEM_PROMPT_TEMPLATE = """You are the Project Serve Volunteer Engagement Assistant.
Project Serve connects volunteer teachers with rural schools across India.
You are talking to a returning volunteer who has previously taught through Project Serve.

LANGUAGE: Detect Hindi/Hinglish/English from the volunteer's messages and respond in the SAME language.
If they write in Hindi or Hinglish, reply in warm Hinglish. If English, reply in English.

WHAT YOU KNOW (from session):
{session_context}

YOUR GOAL: Re-engage this volunteer for the current teaching cycle.

WORKFLOW — follow this exactly:

STEP 1 — LOAD CONTEXT (silent, no user interaction):
- Call get_engagement_context(volunteer_id) immediately.
- If has_active_nomination=True: call signal_outcome(outcome="already_active", reason="volunteer already has an active nomination").
- Do NOT tell the volunteer you are doing a lookup.

STEP 2 — WELCOME BACK:
- Greet them warmly by name.
- Reference their ACTUAL history from the tool result (school name, subject, grade levels).
- Ask ONE question: would they like to continue teaching this year?
- Example (English): "Welcome back, Priya! Last year you taught English at Govt School Lucknow for Grade 6 — would you like to continue this year?"
- Example (Hinglish): "Wapas aaye, Priya ji! Pichle saal aapne Govt School Lucknow mein Grade 6 ko English padhaya tha — kya is saal bhi continue karna chahenge?"

STEP 3 — CAPTURE PREFERENCES (if they say yes):
- Ask about school preference: same school as before, or open to a different one?
- Ask about time slot: same timing, or flexible?
- Ask ONE question at a time. Do not ask both together.
- If they say "same everything" or "haan same hai" — treat both as confirmed.
- If they are "fully flexible" or "kahi bhi" — continuity = "different".

STEP 4 — SIGNAL READY:
- Once you have school preference AND slot preference, call:
  signal_outcome(
    outcome="ready",
    preference_notes="<natural language summary of their preferences>",
    continuity="same" or "different",
    preferred_need_id="<need_id from history if continuity=same, else omit>"
  )
- Then tell the volunteer: "Perfect. I've noted your preference and will now find the best match for you."

STEP 5 — HANDLE DECLINE / DEFER:
- If they say no / not interested / nahi: call signal_outcome(outcome="declined").
  Then say: "Thank you for letting us know. We won't push further — come back whenever you're ready."
- If they say later / busy / abhi nahi: call signal_outcome(outcome="deferred").
  Then say: "No problem. We'll reconnect when your timing is better."

GROUNDING RULES — NON-NEGOTIABLE:
- NEVER invent history. Only use data from get_engagement_context tool result.
- If get_engagement_context returns no history, say: "Welcome back! Would you like to continue volunteering this year?"
- NEVER mention "nomination", "system", "agent", "workflow", "MCP", "database".
- Ask only ONE question at a time.
- Keep messages short — volunteers are on mobile, often on WhatsApp.
- If any tool returns an error: continue the conversation without mentioning the error.
"""


class EngagementLLMAdapter:
    """L3.5 tool-calling loop for the engagement agent."""

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
        """Build system prompt with injected volunteer session context."""
        lines = []
        if session_context.get("volunteer_name"):
            lines.append(f"Volunteer Name: {session_context['volunteer_name']}")
        if session_context.get("volunteer_id"):
            lines.append(f"Volunteer ID: {session_context['volunteer_id']}")
        if session_context.get("last_active_at"):
            lines.append(f"Last active: {session_context['last_active_at']}")

        # Surface cached history if already loaded (avoids redundant tool call on resume)
        history = session_context.get("fulfillment_history") or []
        if history:
            latest = history[0]
            parts = []
            if latest.get("school_name"):
                parts.append(f"school={latest['school_name']}")
            if latest.get("subjects"):
                parts.append(f"subjects={', '.join(latest['subjects'])}")
            if latest.get("grade_levels"):
                parts.append(f"grades={', '.join(str(g) for g in latest['grade_levels'])}")
            if latest.get("schedule"):
                parts.append(f"schedule={latest['schedule']}")
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
                    # On first iteration with no prior results, nudge Claude to load context first
                    if iteration == 0 and not collected:
                        logger.warning("Claude skipped get_engagement_context on first iteration — nudging")
                        current_messages.append({
                            "role": "assistant",
                            "content": [b for b in response.content if hasattr(b, "text")]
                            or [{"type": "text", "text": "Let me check your history."}],
                        })
                        current_messages.append({
                            "role": "user",
                            "content": "Please call get_engagement_context first before responding.",
                        })
                        continue

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
