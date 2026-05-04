"""
SERVE Fulfillment Agent Service - LLM Adapter (simplified)

The LLM's only job here is to:
  1. Present the pre-found match to the volunteer warmly
  2. Handle yes/no confirmation
  3. Call nominate_volunteer_for_need on yes
  4. Call signal_outcome to close the conversation

Match finding is done in Python (matching_service.py) — NOT by the LLM.
This reduces LLM calls from 8-12 per session to 1-2.
"""
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Tool definitions — L3 set ────────────────────────────────────────────────

FULFILLMENT_TOOLS = [
    {
        "name": "get_more_needs",
        "description": (
            "Fetch alternative teaching needs when the volunteer asks for more options, "
            "wants a different school, different subject, or different time. "
            "Pass a hint describing what they want. Returns up to 5 candidates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hint": {
                    "type": "string",
                    "description": "What the volunteer is looking for, e.g. 'different school', 'morning slot', 'maths'",
                },
            },
            "required": ["hint"],
        },
    },
    {
        "name": "nominate_volunteer_for_need",
        "description": "Nominate the volunteer for a need. Call ONLY after the volunteer has explicitly said yes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "need_id":      {"type": "string", "description": "Need UUID from the match context"},
                "volunteer_id": {"type": "string", "description": "Volunteer ID from the handoff context"},
            },
            "required": ["need_id", "volunteer_id"],
        },
    },
    {
        "name": "signal_outcome",
        "description": (
            "Call this when the conversation is complete. "
            "outcome='nominated': volunteer confirmed and nomination submitted. "
            "outcome='human_review': no match, volunteer declined, or needs human follow-up. "
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
                "reason":  {"type": "string"},
            },
            "required": ["outcome"],
        },
    },
]

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You are the eVidyaloka Volunteer Fulfillment Assistant.
eVidyaloka connects volunteer teachers with rural schools across India.

IMPORTANT — BRANDING: Always say "eVidyaloka". NEVER say "Project Serve".

LANGUAGE: Match the volunteer's language — Hindi, Hinglish, or English.

VOLUNTEER:
{handoff_context}

MATCH RESULT:
{match_context}

YOUR TASK:

CRITICAL RULE — ALWAYS PRESENT MATCHES:
- If MATCH STATUS is "found" or "multiple", you MUST present the options to the volunteer. No exceptions.
- Do NOT filter or reject matches based on the volunteer's preferences. The matching system already considered preferences. Your job is to PRESENT what was found and let the volunteer decide.
- Even if the match does not perfectly align with stated preferences (e.g. volunteer wanted mornings but match is afternoon), STILL present it. Say something like: "The closest available opportunity is..." and let them choose.
- Only call signal_outcome(outcome="human_review", reason="no_open_needs") if MATCH STATUS is literally "not_found". NEVER call it when matches exist.

PRESENTING THE MATCH:
- If one match: present it warmly in one short message.
  English: "Great news! We found [Subject] at [School] — [Days], [Time]. Would you like to take this up?"
  Hinglish: "Khushkhabri! [School] mein [Subject] ki jagah mili — [Days], [Time]. Lena chahenge?"
- If multiple matches: list them as a numbered list and ask the volunteer to pick one.
- GRADE PROMOTION: If the volunteer previously taught a lower grade (e.g. Grade 6) and the matched need at the SAME school is the next grade up (e.g. Grade 7), mention it naturally:
  "Your Grade 6 students have been promoted to Grade 7 — would you like to continue teaching them?"
  Only mention promotion if the school is the same AND the grade is exactly one higher.

HANDLING QUESTIONS:
- If the volunteer asks anything about the match (subject, school, timing, location, grade) — answer it directly from the MATCH RESULT above. Do NOT call any tool.
- If the volunteer asks for more options, different school, different time, or different subject: call get_more_needs(hint="<what they want>"). Present the new results the same way.

CONFIRMING:
- If volunteer says YES to a match: call nominate_volunteer_for_need(need_id=<need_id>, volunteer_id=<volunteer_id from VOLUNTEER above>), then call signal_outcome(outcome="nominated", need_id=<need_id>). Thank them warmly.
- If volunteer says NO or not interested: call signal_outcome(outcome="human_review", reason="volunteer_declined"). Say the team will follow up.
- If volunteer wants to pause: call signal_outcome(outcome="paused").

RULES:
- Do NOT greet or introduce yourself. Go directly to presenting the match results.
- NEVER call nominate_volunteer_for_need before the volunteer says yes.
- NEVER invent need details — only use what's in MATCH RESULT or get_more_needs results.
- NEVER mention "nomination", "system", "agent", "MCP", "database", "osid".
- Keep messages short — volunteers are on mobile."""


class FulfillmentLLMAdapter:
    """Minimal LLM adapter — present match, confirm, nominate."""

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

    def build_support_prompt(self, handoff: Dict[str, Any]) -> str:
        """System prompt for human_review stage — support mode, no nomination."""
        volunteer_name = handoff.get("volunteer_name", "Volunteer")
        return f"""You are the eVidyaloka Volunteer Support Assistant.
You are talking to {volunteer_name}, a returning volunteer.

IMPORTANT — BRANDING: Always say "eVidyaloka". NEVER say "Project Serve".
LANGUAGE: Match the volunteer's language — Hindi, Hinglish, or English.

SITUATION: Our team has been notified and will follow up with {volunteer_name} about a teaching placement.

YOUR ROLE:
- Answer any questions the volunteer has warmly and helpfully.
- If they ask when someone will contact them: "Our team will reach out within 1-2 working days."
- If they ask about changing preferences: note it down and say the team will consider it.
- If they want to pause: call signal_outcome(outcome="paused").
- Do NOT attempt to find or nominate needs — that's being handled by the team.
- Keep messages short and reassuring."""

    def build_system_prompt(
        self,
        handoff: Dict[str, Any],
        match_context: str,
    ) -> str:
        """Build system prompt with volunteer handoff + pre-found match injected."""
        volunteer_name = handoff.get("volunteer_name", "Volunteer")
        volunteer_id   = handoff.get("volunteer_id", "")
        preference_notes = handoff.get("preference_notes", "")

        handoff_lines = [
            f"Name: {volunteer_name}",
            f"Volunteer ID: {volunteer_id}",
        ]
        if preference_notes:
            handoff_lines.append(f"Preferences: {preference_notes}")

        # Surface previous teaching history so LLM can detect grade promotion
        history = handoff.get("fulfillment_history") or []
        if history:
            latest = history[0]
            prev_parts = []
            if latest.get("school_name") or latest.get("need_purpose"):
                prev_parts.append(f"school={latest.get('school_name') or latest.get('need_purpose')}")
            if latest.get("grade_levels"):
                prev_parts.append(f"grades={latest['grade_levels']}")
            if latest.get("subjects"):
                prev_parts.append(f"subjects={latest['subjects']}")
            if prev_parts:
                handoff_lines.append(f"Previous teaching: {'; '.join(prev_parts)}")

        return _SYSTEM_PROMPT_TEMPLATE.format(
            handoff_context="\n".join(handoff_lines),
            match_context=match_context,
        )

    def format_match_context(self, match_result) -> str:
        """Serialize MatchResult into a readable block for the system prompt."""
        from app.service.matching_service import MatchResult
        if match_result.status == "not_found":
            return f"MATCH STATUS: not_found\nReason: {match_result.reason or 'no open needs'}"

        lines = [f"MATCH STATUS: {match_result.status}"]
        for i, need in enumerate(match_result.candidates, 1):
            prefix = f"Option {i}" if len(match_result.candidates) > 1 else "Match"
            lines.append(f"\n{prefix}:")
            lines.append(f"  need_id: {need.get('id', '')}")
            lines.append(f"  school: {need.get('school_name', need.get('needPurpose', ''))}")
            lines.append(f"  subject: {need.get('name', '')}")
            lines.append(f"  days: {need.get('days', '')}")
            slots = need.get("time_slots", [])
            if slots:
                s = slots[0]
                lines.append(f"  time: {s.get('startTime','')}-{s.get('endTime','')}")
            lines.append(f"  status: {need.get('status', '')}")
        return "\n".join(lines)

    async def run_conversation_loop(
        self,
        system_prompt: str,
        messages: List[Dict],
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        max_iterations: int = 4,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Minimal tool-calling loop — present match, handle yes/no, nominate.
        Max 4 iterations: present → confirm → nominate → signal.
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
            for iteration in range(max_iterations):
                response = await client.messages.create(
                    model=self._model,
                    max_tokens=512,
                    system=system_prompt,
                    tools=FULFILLMENT_TOOLS,
                    messages=current_messages,
                )

                text_blocks    = [b for b in response.content if hasattr(b, "text") and b.text]
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

                if not tool_use_blocks:
                    return next((b.text for b in text_blocks), self._fallback()), collected

                tool_results = []
                for tool_block in tool_use_blocks:
                    tool_name  = tool_block.name
                    tool_input = tool_block.input or {}
                    logger.info(f"Fulfillment loop: tool '{tool_name}' (iter {iteration + 1})")
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

            logger.warning("Fulfillment loop exhausted iterations")
            return "", collected

        except Exception as exc:
            logger.error(f"Fulfillment loop error: {exc}")
            return self._fallback(), collected

    def _fallback(self) -> str:
        return (
            "Hamari team aapke liye sahi jagah dhundh rahi hai. Jald hi contact karenge."
        )


# Singleton
llm_adapter = FulfillmentLLMAdapter()
