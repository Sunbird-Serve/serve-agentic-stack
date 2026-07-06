"""
SERVE Selection Agent Service - LLM Adapter

Natural conversation layer for the selection rubric. The LLM may ask the
volunteer one warm question at a time and should always emit structured
rubric signals through the `record_selection_turn` tool.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


SELECTION_TOOLS = [
    {
        "name": "record_selection_turn",
        "description": (
            "Record structured selection signals from the volunteer's latest response. "
            "Call this every turn before responding."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "signals": {
                    "type": "object",
                    "properties": {
                        "motivation_alignment": {
                            "type": "string",
                            "enum": ["strong", "moderate", "weak", "unknown"],
                        },
                        "continuity_intent": {
                            "type": "string",
                            "enum": ["committed", "uncertain", "low", "unknown"],
                        },
                        "communication_clarity": {
                            "type": "string",
                            "enum": ["clear", "mixed", "unclear", "unknown"],
                        },
                        "language_comfort": {
                            "type": "string",
                            "enum": ["comfortable", "limited", "unknown"],
                        },
                        "availability_realism": {
                            "type": "string",
                            "enum": ["realistic", "unclear", "not_realistic", "unknown"],
                        },
                        "readiness": {
                            "type": "string",
                            "enum": ["ready_now", "future_ready", "not_ready", "unknown"],
                        },
                        "blockers": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "risk_signals": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "notes": {
                    "type": "object",
                    "properties": {
                        "motivation": {"type": "string"},
                        "availability": {"type": "string"},
                        "language_notes": {"type": "string"},
                        "blockers": {"type": "string"},
                    },
                },
                "next_missing_signal": {
                    "type": "string",
                    "enum": [
                        "motivation_alignment",
                        "continuity_intent",
                        "language_comfort",
                        "availability_realism",
                        "readiness",
                        "blockers",
                        "none",
                    ],
                },
                "pause_requested": {"type": "boolean"},
                "human_review_needed": {"type": "boolean"},
                "human_review_reason": {"type": "string"},
            },
            "required": ["signals", "next_missing_signal"],
        },
    }
]


_SYSTEM_PROMPT_TEMPLATE = """You are the eVidyaloka Selection Assistant.
You are speaking with a new volunteer who has completed basic registration.

eVidyaloka connects volunteer teachers with children in rural India.

Your job is to have a short, natural evaluation conversation and gather evidence for:
- motivation and purpose alignment
- seriousness and continuity intent
- communication clarity
- language comfort and fluency
- realistic time availability
- current readiness for active needs versus future engagement
- blockers, concerns, or risk signals

WHAT YOU KNOW:
{context_block}

CURRENT STRUCTURED SIGNALS:
{signals_block}

CONVERSATION RULES:
- Do NOT greet or introduce yourself. The volunteer is already in a conversation. Go directly to your first question.
- Be warm, respectful, concise, and human.
- Ask only one question at a time.
- Do not sound like a form or interview checklist.
- Do not expose scores, internal routing, or hidden evaluation logic.
- Do not promise assignment, placement, or immediate opportunity.
- If the volunteer asks to continue later, acknowledge politely and mark pause_requested=true.
- If the case is sensitive, contradictory, or ambiguous, mark human_review_needed=true.
- Never say rejected, disqualified, or not selected.
- Keep responses mobile-friendly: usually 1-3 short sentences.

TOOL RULE:
- You must call `record_selection_turn` every turn before your final text response.
- Extract only what the volunteer actually said. Do not invent facts.
- Use "unknown" for signals that are not yet supported by evidence.
- Set next_missing_signal to the one best follow-up signal to gather next, or "none" when enough evidence is collected.

QUESTION GUIDANCE:
- If motivation is missing, ask what draws them to volunteer with eVidyaloka.
- If continuity intent is missing, ask how volunteering fits into the next few months.
- If language comfort is missing, ask about comfort teaching or communicating in English/Hindi.
- If availability is missing, ask what time they can realistically commit.
- If readiness is missing, ask whether they can start soon or need more time.
- If blockers are missing, ask if anything may make consistency difficult.
"""


class SelectionLLMAdapter:
    """Natural LLM conversation adapter for selection. Model-agnostic via LiteLLM."""

    def __init__(self) -> None:
        self._api_key: Optional[str] = next(
            (os.environ[k] for k in (
                "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                "OPENAI_API_KEY", "GEMINI_API_KEY", "EMERGENT_LLM_KEY",
            ) if os.environ.get(k)),
            None,
        )
        self._model: str = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
        # Emergent key is Anthropic-compatible; map it so LiteLLM finds it.
        if os.environ.get("EMERGENT_LLM_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["EMERGENT_LLM_KEY"]

    def build_system_prompt(
        self,
        *,
        profile: Dict[str, Any],
        onboarding_summary: Optional[str],
        key_facts: List[str],
        signals: Dict[str, Any],
    ) -> str:
        context_lines: List[str] = []
        if profile.get("full_name"):
            context_lines.append(f"Name: {profile['full_name']}")
        if profile.get("email"):
            context_lines.append(f"Email: {profile['email']}")
        if profile.get("phone"):
            context_lines.append(f"Phone: {profile['phone']}")
        if onboarding_summary:
            context_lines.append(f"Onboarding summary: {onboarding_summary}")
        if key_facts:
            context_lines.append("Key facts: " + "; ".join(str(f) for f in key_facts[:6]))

        context_block = "\n".join(context_lines) if context_lines else "(basic registration completed)"
        signals_block = json.dumps(signals or {}, indent=2, sort_keys=True)
        return _SYSTEM_PROMPT_TEMPLATE.format(
            context_block=context_block,
            signals_block=signals_block,
        )

    async def run_selection_loop(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, str]],
        tool_executor: Callable[[str, Dict[str, Any]], Any],
        fallback_question: str,
        max_tool_iterations: int = 4,
    ) -> Tuple[str, Dict[str, Any]]:
        if not self._api_key:
            return fallback_question, {}

        import litellm
        litellm.drop_params = True

        collected: Dict[str, Any] = {}
        current_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") and m.get("content") is not None
        ]

        # Ensure at least one user message — on handoff the history may be empty
        if not current_messages or current_messages[0]["role"] != "user":
            current_messages.insert(0, {"role": "user", "content": "Let's continue."})

        # Convert Anthropic tool format to OpenAI format for LiteLLM
        litellm_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in SELECTION_TOOLS
        ]

        # Prepend system message
        llm_messages = [{"role": "system", "content": system_prompt}] + current_messages

        try:
            for iteration in range(max_tool_iterations):
                response = await litellm.acompletion(
                    model=self._model,
                    messages=llm_messages,
                    tools=litellm_tools,
                    max_tokens=512,
                )

                choice = response.choices[0]
                message = choice.message

                # No tool calls — return text
                if not message.tool_calls:
                    text = message.content or fallback_question
                    return text, collected

                # Process tool calls
                llm_messages.append(message.model_dump())
                for tool_call in message.tool_calls:
                    tool_name = tool_call.function.name
                    tool_input = json.loads(tool_call.function.arguments) if tool_call.function.arguments else {}
                    logger.info("Selection loop: tool '%s' (iter %s)", tool_name, iteration + 1)
                    result = await tool_executor(tool_name, tool_input)
                    collected[tool_name] = tool_input
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })

            return fallback_question, collected
        except Exception as exc:
            logger.error("Selection LLM loop failed: %s", exc)
            return fallback_question, collected


llm_adapter = SelectionLLMAdapter()
