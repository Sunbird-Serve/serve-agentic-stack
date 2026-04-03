"""
SERVE Fulfillment Agent Service - LLM Adapter (L4)

Extended tool-calling loop. Runs Claude with the full FULFILLMENT_TOOLS set,
accumulating conversation history across turns. Stops when Claude produces
a text response OR calls signal_outcome.
"""
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Tool definitions ──────────────────────────────────────────────────────────

FULFILLMENT_TOOLS = [
    {
        "name": "get_needs_for_entity",
        "description": (
            "Get all open needs for a school/entity. "
            "entity_id MUST be school.entity_id from resolve_school_context result, "
            "or preferred_school_id from handoff. "
            "NEVER use volunteer_id or any 1- prefixed ID as entity_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string", "description": "School UUID from school.entity_id — NOT volunteer_id"}},
            "required": ["entity_id"],
        },
    },
    {
        "name": "get_need_details",
        "description": "Enrich a need with subject, grade, schedule, and time slots.",
        "input_schema": {
            "type": "object",
            "properties": {"need_id": {"type": "string"}},
            "required": ["need_id"],
        },
    },
    {
        "name": "resolve_school_context",
        "description": (
            "Find a school by name hint. Returns school.entity_id — use that value "
            "as entity_id when calling get_needs_for_entity. Never use school.id or volunteer_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "coordinator_id": {"type": "string"},
                "school_hint": {"type": "string"},
            },
        },
    },
    {
        "name": "get_nominations_for_need",
        "description": "Check existing nominations for a need. Skip needs with Approved nominations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "need_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["Nominated", "Approved", "Proposed", "Backfill", "Rejected"],
                },
            },
            "required": ["need_id"],
        },
    },
    {
        "name": "get_all_entities",
        "description": (
            "Get all schools/entities. Use this as a fallback when the preferred school "
            "has no needs matching the volunteer's time preference. "
            "Returns a list of schools with entity_id fields."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "nominate_volunteer_for_need",
        "description": "Nominate the volunteer for a need. Call ONLY after the volunteer has confirmed yes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "need_id": {"type": "string"},
                "volunteer_id": {"type": "string"},
            },
            "required": ["need_id", "volunteer_id"],
        },
    },
    {
        "name": "signal_outcome",
        "description": (
            "Call this when the conversation is complete. "
            "outcome='nominated': volunteer confirmed and nomination submitted. "
            "outcome='human_review': no match found or volunteer declined. "
            "outcome='paused': volunteer wants to continue later."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["nominated", "human_review", "paused"],
                },
                "need_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["outcome"],
        },
    },
]

# ── System prompt template ────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You are the eVidyaloka Volunteer Fulfillment Assistant.
eVidyaloka connects volunteer teachers with rural schools across India.
You are talking to a returning volunteer who has confirmed they want to continue teaching.

IMPORTANT — BRANDING: Always say "eVidyaloka". NEVER say "Project Serve" to volunteers.

LANGUAGE: Detect Hindi/Hinglish/English from conversation history and respond in the SAME language.

YOUR GOAL: Find the right open teaching need for this volunteer and nominate them.

WHAT YOU KNOW (from handoff — use this directly, no need to re-fetch):
{handoff_context}

WORKFLOW — follow this exactly:

STEP 1 — FIND THE NEED (silent, no user interaction):
- Use the handoff data above — do NOT call any context-fetch tool.
- If continuity=same and preferred_need_id is present: call get_need_details(preferred_need_id) to confirm it is still open.
- If continuity=same and preferred_school_id is present but no preferred_need_id: call get_needs_for_entity(entity_id=preferred_school_id).
- If continuity=same but neither school nor need ID: call resolve_school_context(school_hint=preference_notes or school name from Last teaching).
- If continuity=different: call resolve_school_context(school_hint=preference_notes).
- After resolve_school_context: use school.entity_id (NOT school.id, NOT volunteer_id) as entity_id for get_needs_for_entity.
- CRITICAL: entity_id for get_needs_for_entity must be a plain UUID like "b53e465c-...". If it starts with "1-", it is WRONG — do not use it.
- For each candidate need, call get_need_details(need_id) if not already done.
- Call get_nominations_for_need(need_id, status="Approved") — skip needs that already have Approved nominations.

STEP 1b — FALLBACK TO OTHER SCHOOLS (if preferred school has no time match):
- If the preferred school has needs but NONE match the volunteer's preferred time slot from preference_notes:
  - Call get_all_entities() to get all schools.
  - Pick the 2 most promising schools (different from preferred school).
  - For each, call get_needs_for_entity(entity_id=school.entity_id).
  - Find needs whose time_slots match the volunteer's preferred time.
  - Present the best match — mention it's a different school.
  - If still no match after 2 schools: call signal_outcome(outcome="human_review", reason="no_time_match").
- Do all of this WITHOUT asking the volunteer anything.

STEP 2 — CONFIRM WITH VOLUNTEER:
- If one clear match: present it warmly.
  English: "We found a great match — [Subject] at [School], [Days] [Time]. Would you like to take this up?"
  Hinglish: "Humne [School] mein [Subject] ki jagah dhundhi — [Days] [Time]. Theek hai?"
- If multiple matches: list them briefly and ask the volunteer to pick one.
- If no match: call signal_outcome(outcome="human_review", reason="no_open_needs") and tell the volunteer the team will follow up.

STEP 3 — NOMINATE:
- If volunteer says yes: call nominate_volunteer_for_need(need_id=<need_id>, volunteer_id=<volunteer_id from handoff>).
- Then call signal_outcome(outcome="nominated", need_id=<need_id>).
- Thank the volunteer warmly. Tell them the coordinator will review and be in touch.
- If volunteer says no: call signal_outcome(outcome="human_review", reason="volunteer_declined").
- If volunteer wants to pause: call signal_outcome(outcome="paused").

GROUNDING RULES — NON-NEGOTIABLE:
- NEVER invent or guess need details. Only use data from tool results.
- NEVER call nominate_volunteer_for_need before the volunteer has said yes.
- NEVER mention "nomination", "system", "agent", "workflow", "MCP", "osid", "database".
- If any tool returns an error: continue without mentioning the error; try the next approach.
- Keep messages short — volunteers are on mobile, often on WhatsApp."""


class FulfillmentLLMAdapter:
    """L4 extended tool-calling loop for the fulfillment agent."""

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

    def build_system_prompt(self, handoff: Dict[str, Any]) -> str:
        """Build the system prompt with injected handoff context."""
        volunteer_name = handoff.get("volunteer_name", "Volunteer")
        volunteer_id = handoff.get("volunteer_id", "")
        continuity = handoff.get("continuity", "same")
        preferred_school_id = handoff.get("preferred_school_id")
        preferred_need_id = handoff.get("preferred_need_id")
        preference_notes = handoff.get("preference_notes")
        fulfillment_history = handoff.get("fulfillment_history", [])

        lines = [
            f"Volunteer Name: {volunteer_name}",
            f"Volunteer ID: {volunteer_id}",
            f"Continuity preference: {continuity}",
        ]
        if preferred_need_id:
            lines.append(f"Preferred need ID: {preferred_need_id}")
        if preferred_school_id:
            lines.append(f"Preferred school ID: {preferred_school_id}")
        if preference_notes:
            lines.append(f"Preference notes: {preference_notes}")

        # Surface last fulfillment details so LLM can reference them
        if fulfillment_history:
            latest = fulfillment_history[0]
            parts = []
            if latest.get("school_name"):
                parts.append(f"school={latest['school_name']}")
            if latest.get("need_purpose") or latest.get("need_name"):
                parts.append(f"need={latest.get('need_purpose') or latest.get('need_name')}")
            if latest.get("days"):
                parts.append(f"days={latest['days']}")
            if latest.get("time_slots"):
                s = latest["time_slots"][0]
                parts.append(f"time={s.get('startTime','')}-{s.get('endTime','')}")
            if latest.get("need_id"):
                parts.append(f"need_id={latest['need_id']}")
            if parts:
                lines.append(f"Last teaching: {'; '.join(parts)}")

        handoff_context = "\n".join(lines)
        return _SYSTEM_PROMPT_TEMPLATE.format(handoff_context=handoff_context)

    async def run_l4_loop(
        self,
        system_prompt: str,
        messages: List[Dict],
        tool_executor: Callable[[str, Dict], Any],
        max_tool_iterations: int = 10,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Run the L4 extended tool-calling loop.

        Runs Claude with the full conversation history, executing tools until
        Claude produces a text response OR calls signal_outcome.

        Returns: (text_response_for_volunteer, collected_tool_results)
        """
        client = self._get_client()
        if client is None:
            return self._fallback(), {}

        collected_tool_results: Dict[str, Any] = {}
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
                    max_tokens=1024,
                    system=system_prompt,
                    tools=FULFILLMENT_TOOLS,
                    messages=current_messages,
                )

                # Check if Claude produced a text response (message for volunteer)
                text_blocks = [b for b in response.content if hasattr(b, "text") and b.text]
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

                # If no tool calls, Claude is done — return the text
                if not tool_use_blocks:
                    text = next((b.text for b in text_blocks), self._fallback())
                    return text, collected_tool_results

                # Execute all tool calls in this response
                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name = tool_block.name
                    tool_input = tool_block.input or {}

                    logger.info(f"L4 loop: executing tool '{tool_name}' (iteration {iteration + 1})")
                    result = await tool_executor(tool_name, tool_input)
                    collected_tool_results[tool_name] = result

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_block.id,
                        "content": str(result),
                    })

                    # signal_outcome terminates the loop immediately
                    if tool_name == "signal_outcome":
                        # Return any text produced alongside signal_outcome, or empty string
                        text = next((b.text for b in text_blocks), "")
                        return text, collected_tool_results

                # Append assistant message and tool results to conversation
                current_messages.append({"role": "assistant", "content": response.content})
                current_messages.append({"role": "user", "content": tool_results})

            # Loop exhausted — return empty to trigger human_review
            logger.warning("L4 loop exhausted max iterations without signal_outcome")
            return "", collected_tool_results

        except Exception as exc:
            logger.error(f"L4 loop error: {exc}")
            return self._fallback(), collected_tool_results

    def _fallback(self) -> str:
        return (
            "Abhi koi jagah nahi mili. Hamari team jald hi aapse contact karegi. "
            "Aapke saath kaam karne ka mauka milega!"
        )


# Singleton
llm_adapter = FulfillmentLLMAdapter()
