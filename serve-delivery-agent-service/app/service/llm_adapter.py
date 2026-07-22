"""
SERVE Delivery Agent Service - LLM Adapter

The LLM's job is narrow and conversational:
  • Activation mode: introduce the assignment, answer questions, and record the
    volunteer's acknowledgement + first-session readiness.
  • Operations mode: answer questions about a session, and when the volunteer
    reports what happened, record the verified outcome, blocker, or reschedule.

The LLM NEVER decides whether reminders go out — that is deterministic policy in
reminder_engine.py / policy_engine.py. The LLM only converses and calls tools to
persist confirmed facts. Model-agnostic via LiteLLM.
"""
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("delivery.llm")

# Retry policy (mirrors the onboarding adapter): free-tier models can be slow, so
# give each attempt a generous timeout and retry transient failures once.
_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "25"))
_MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "2"))
_RETRY_BACKOFF_SECONDS = float(os.environ.get("LLM_RETRY_BACKOFF_SECONDS", "1"))

_UNAVAILABLE_RESPONSE = (
    "I'm having a little trouble responding right now. Could you please send that again?"
)


DELIVERY_TOOLS = [
    {
        "name": "confirm_acknowledgement",
        "description": (
            "Record that the volunteer has acknowledged / understood their teaching "
            "assignment. Call this once the volunteer clearly confirms they are aware "
            "of the assignment and willing to proceed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "confirm_readiness",
        "description": (
            "Record that the volunteer is ready for their first scheduled session "
            "(they have the meeting link / details and no blocker). Call only after "
            "they confirm readiness."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "record_session_outcome",
        "description": (
            "Record what happened for a scheduled session, based on what the volunteer "
            "reports. outcome is one of: completed, partially_completed, missed, disrupted, "
            "cancelled, reschedule_requested, support_needed. Include the session_id being "
            "reported on and a short reason when it did not fully happen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scheduled_session_id": {"type": "string"},
                "outcome": {
                    "type": "string",
                    "enum": ["completed", "partially_completed", "missed", "disrupted",
                             "cancelled", "reschedule_requested", "support_needed"],
                },
                "reason": {"type": "string"},
                "attendance_count": {"type": "integer", "description": "Only if the volunteer states a number — never guess."},
                "duration_minutes": {"type": "integer", "description": "Only if the volunteer states this — never guess."},
                "disruption_type": {"type": "string", "description": "Only for outcome=disrupted, e.g. power_cut, internet_issue."},
            },
            "required": ["scheduled_session_id", "outcome"],
        },
    },
    {
        "name": "log_blocker",
        "description": (
            "Record an operational blocker the volunteer reports (technical, meeting "
            "link, institution unavailable, learner attendance, personal conflict, "
            "material, communication, or other)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "blocker_type": {"type": "string"},
                "description": {"type": "string"},
                "scheduled_session_id": {"type": "string"},
            },
            "required": ["blocker_type"],
        },
    },
    {
        "name": "capture_reschedule_request",
        "description": (
            "Capture a request to reschedule a session. This is only a REQUEST — it "
            "is not confirmed. Include the session_id, reason, and any preferred new "
            "date/time the volunteer gives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scheduled_session_id": {"type": "string"},
                "reason": {"type": "string"},
                "preferred_date": {"type": "string"},
                "preferred_time": {"type": "string"},
            },
            "required": ["scheduled_session_id"],
        },
    },
    {
        "name": "notify_linked_stakeholder",
        "description": (
            "Notify the volunteer's coordinator about something relevant to this delivery "
            "(e.g. the volunteer wants the coordinator kept in the loop about a blocker, "
            "reschedule, or their progress). Only call this when the volunteer actually "
            "asks you to inform the coordinator, or when it's clearly appropriate (e.g. "
            "a session was missed and the coordinator should know) — never as a substitute "
            "for logging a blocker or reschedule request, which you should always do first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short, factual summary of what the coordinator should know."},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "signal_outcome",
        "description": (
            "Call this when the conversation reaches a resolution. "
            "outcome='activation_complete': volunteer acknowledged AND is ready for the first session. "
            "outcome='delivery_complete': the whole delivery/programme is finished. "
            "outcome='paused': the volunteer wants to continue later. "
            "outcome='escalate': needs a human / operations reviewer. "
            "outcome='continue': stay in the conversation (no state change)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": ["activation_complete", "delivery_complete", "paused", "escalate", "continue"],
                },
                "reason": {"type": "string"},
            },
            "required": ["outcome"],
        },
    },
]


_GUARDRAILS = """RULES (important):
- You are the eVidyaloka Delivery Assistant. Always say "eVidyaloka". NEVER say "Project Serve".
- Match the volunteer's language — Hindi, Hinglish, or English. Keep messages short (mobile).
- NEVER promise a schedule change, reschedule, or reassignment — you can only capture a REQUEST.
- NEVER invent attendance, learner participation, session duration, or completion. Only record what the volunteer actually tells you.
- NEVER assume the volunteer caused a missed session. Ask neutrally what happened.
- NEVER mention internal systems, tools, "database", "MCP", "osid", "escalation", or scoring.
- Do NOT overwhelm the volunteer with many questions at once — ask one thing at a time.
- If something is sensitive, unsafe, or you cannot resolve it, call signal_outcome(outcome="escalate", reason=...)."""


_TOOL_NAMES = [t["name"] for t in DELIVERY_TOOLS]
_LEAKED_TOOL_CALL_RE = re.compile(
    r"\s*\b(?:" + "|".join(re.escape(n) for n in _TOOL_NAMES) + r")\s*[\(\{][^)}]*[\)\}]\s*"
)


def _sanitize_text(text: Optional[str]) -> str:
    """Strip raw tool-call-looking syntax a weaker model can leak into its prose
    (observed live with OpenRouter/Llama: a reply ending in
    'signal_outcome{"outcome": "continue"}'). Tool calls belong in the structured
    tool_calls field, never in what the volunteer reads — this is a defensive net
    for models that don't cleanly separate the two, not the primary path."""
    if not text:
        return text or ""
    return _LEAKED_TOOL_CALL_RE.sub(" ", text).strip()


class DeliveryLLMAdapter:

    def __init__(self) -> None:
        self._api_key: Optional[str] = next(
            (os.environ[k] for k in (
                "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                "OPENAI_API_KEY", "GEMINI_API_KEY", "EMERGENT_LLM_KEY",
            ) if os.environ.get(k)),
            None,
        )
        self._model: str = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
        if os.environ.get("EMERGENT_LLM_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["EMERGENT_LLM_KEY"]

    def build_activation_prompt(self, delivery: Dict[str, Any], sessions: List[Dict[str, Any]],
                                activation_content: Optional[Dict[str, Optional[str]]] = None) -> str:
        name = delivery.get("volunteer_name") or "the volunteer"
        subject = _first_subject(sessions)
        first = sessions[0] if sessions else {}
        acknowledged = delivery.get("volunteer_acknowledged")
        ready = delivery.get("first_session_ready")
        content = activation_content or {}
        reference_block = ""
        if content.get("intro") or content.get("instructions"):
            lines = ["\nAUTHORITATIVE PROGRAMME TEXT (relay the substance of this faithfully — "
                     "do not invent different facts, but you may phrase it naturally):"]
            if content.get("intro"):
                lines.append(f"- Intro: {content['intro']}")
            if content.get("instructions"):
                lines.append(f"- Expectations: {content['instructions']}")
            reference_block = "\n".join(lines) + "\n"
        return f"""You are the eVidyaloka Delivery Assistant, helping {name} get ready to start teaching.

ASSIGNMENT:
- Programme: {delivery.get('programme') or 'eVidyaloka teaching'}
- Subject/focus: {subject}
- School/institution id: {delivery.get('entity_id') or 'assigned school'}
- First session: {first.get('scheduled_date') or 'to be confirmed'} at {first.get('start_time') or 'TBD'}
- Meeting link: {first.get('meeting_link') or 'will be shared'}
- Already acknowledged: {bool(acknowledged)}
- Already ready for first session: {bool(ready)}
{reference_block}
YOUR TASK (activation):
1. Warmly introduce the assignment and what the volunteer will be doing.
2. Confirm they understand and are willing to proceed → call confirm_acknowledgement.
3. THEN, in your reply, separately share the first-session details (date, time, meeting link) and ask if they are ready. Only after they respond to THAT question → call confirm_readiness.
4. When BOTH acknowledgement and readiness are done, call signal_outcome(outcome="activation_complete").
5. If they raise a problem, call log_blocker. If they want to stop for now, signal_outcome(outcome="paused").
6. If they ask you to keep their coordinator informed, call notify_linked_stakeholder.

IMPORTANT: acknowledgement and first-session readiness are two SEPARATE confirmations from
two SEPARATE volunteer replies. A generic "yes I confirm" / "I'm in" only satisfies
acknowledgement. NEVER call confirm_readiness in the same turn as confirm_acknowledgement —
ask the first-session question first and wait for their answer.

{_GUARDRAILS}"""

    def build_operations_prompt(self, delivery: Dict[str, Any], sessions: List[Dict[str, Any]]) -> str:
        name = delivery.get("volunteer_name") or "the volunteer"
        session_lines = []
        for s in sessions:
            if s.get("session_state") == "cancelled" or s.get("outcome") in ("completed", "missed", "cancelled"):
                continue
            session_lines.append(
                f"  - session_id={s.get('id')} | {s.get('subject') or 'session'} on "
                f"{s.get('scheduled_date')} {s.get('start_time') or ''} | state={s.get('session_state')}"
            )
        sessions_block = "\n".join(session_lines) or "  (no open sessions right now)"
        return f"""You are the eVidyaloka Delivery Assistant, supporting {name} during their active teaching delivery.

OPEN SESSIONS:
{sessions_block}

PROGRESS: {delivery.get('completed_sessions', 0)} of {delivery.get('expected_sessions') or '?'} sessions completed.

YOUR TASK (daily operations):
- Answer the volunteer's questions about their sessions (timing, link, subject) from the details above.
- When the volunteer tells you whether a session happened, call record_session_outcome with the EXACT session_id (copy it from OPEN SESSIONS above — never invent or paraphrase it) and the outcome (completed / partially_completed / missed / cancelled). Add a short reason if it did not fully happen.
- IMPORTANT — multiple open sessions: if more than one session is listed above and the volunteer's reply does not make clear WHICH one they mean, ask them which date/session before recording anything. Do NOT assume. If a tool replies with status "needs_clarification", ask the volunteer which session (by date) and then record only after they tell you.
- If they report a problem, call log_blocker. If they want a different time, call capture_reschedule_request (a request only — do NOT promise it).
- If they ask you to keep their coordinator informed about something, call notify_linked_stakeholder — always log_blocker or capture_reschedule_request FIRST if applicable, notify_linked_stakeholder is in addition to that, never instead of it.
- Only call signal_outcome(outcome="delivery_complete") if the PROGRESS line shows all sessions are complete. Never before that.
- If they want to stop for now, signal_outcome(outcome="paused"). If it needs a human, signal_outcome(outcome="escalate").
- Otherwise, once you've answered or recorded what they said, call signal_outcome(outcome="continue").

{_GUARDRAILS}"""

    async def run_conversation_loop(
        self,
        system_prompt: str,
        messages: List[Dict],
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        max_iterations: int = 6,
    ) -> Tuple[str, Dict[str, Any]]:
        """Tool-calling loop. Returns (assistant_text, collected_tool_results).
        Retries transient LLM failures; falls back to an honest message."""
        if not self._api_key:
            logger.warning("No API key configured — using fallback response")
            return self._fallback(), {}

        import litellm
        litellm.drop_params = True

        collected: Dict[str, Any] = {}
        current_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") and m.get("content") is not None
        ]
        litellm_tools = [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in DELIVERY_TOOLS
        ]
        llm_messages = [{"role": "system", "content": system_prompt}] + current_messages

        try:
            for iteration in range(max_iterations):
                message = await self._acompletion_with_retry(llm_messages, litellm_tools)
                if message is None:
                    return (self._fallback(), collected) if not collected else ("", collected)

                if not message.tool_calls:
                    return _sanitize_text(message.content) or self._fallback(), collected

                llm_messages.append(message.model_dump())
                signalled = False
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_input = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    logger.info(f"Delivery loop: tool '{tool_name}' (iter {iteration + 1}) args={tool_input}")
                    result = await tool_executor(tool_name, tool_input)
                    collected[tool_name] = result
                    llm_messages.append({
                        "role": "tool", "tool_call_id": tool_call.id, "content": str(result),
                    })
                    if tool_name == "signal_outcome":
                        signalled = True

                if signalled:
                    cleaned = _sanitize_text(message.content)
                    if cleaned:
                        return cleaned, collected
                    # Some models (observed with OpenRouter/Llama) front-load
                    # signal_outcome with no accompanying text, expecting a
                    # follow-up turn to write the actual reply once it sees the
                    # tool result. Give it exactly one more, tools-off, so it
                    # can't loop forever — the volunteer is still owed a
                    # message, and an empty string here would wrongly read as
                    # a system failure downstream.
                    closing = await self._acompletion_with_retry(llm_messages)
                    return _sanitize_text(closing.content if closing else None), collected

            logger.warning("Delivery loop exhausted iterations")
            return "", collected
        except Exception as exc:
            logger.error(f"Delivery loop error: {exc}")
            return self._fallback(), collected

    async def _acompletion_with_retry(self, llm_messages, litellm_tools=None):
        """One LLM completion with retry on transient failure. Returns the message
        object or None if all attempts failed. Omits `tools` entirely when None —
        used for a text-only closing turn after signal_outcome."""
        import asyncio
        import litellm
        last_error = None
        kwargs: Dict[str, Any] = {
            # Replies are meant to be short (mobile) per the guardrails — 400 is
            # still generous for that, and caps the cost of a runaway/garbled
            # generation from a weaker model.
            "model": self._model, "messages": llm_messages,
            "max_tokens": 400, "timeout": _TIMEOUT,
        }
        if litellm_tools:
            kwargs["tools"] = litellm_tools
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await litellm.acompletion(**kwargs)
                return response.choices[0].message
            except Exception as e:
                last_error = e
                if attempt < _MAX_ATTEMPTS - 1:
                    logger.warning(f"LLM attempt {attempt + 1}/{_MAX_ATTEMPTS} failed: {e}. Retrying...")
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
        logger.error(f"LLM failed after {_MAX_ATTEMPTS} attempts: {last_error}")
        return None

    def _fallback(self) -> str:
        return _UNAVAILABLE_RESPONSE


def _first_subject(sessions: List[Dict[str, Any]]) -> str:
    for s in sessions:
        if s.get("subject"):
            return s["subject"]
    return "teaching sessions"


# Singleton
llm_adapter = DeliveryLLMAdapter()
