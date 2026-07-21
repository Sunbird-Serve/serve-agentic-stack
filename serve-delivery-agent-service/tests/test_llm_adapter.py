"""Tool-loop tests for DeliveryLLMAdapter. litellm isn't installed in this venv
(delivery_logic tests avoid it by mocking llm_adapter wholesale) — here we stub
sys.modules['litellm'] with a scripted acompletion() so we can drive the loop's
own control flow directly, in particular the signal_outcome/empty-text path."""
import sys
import types
from unittest.mock import AsyncMock

import pytest

from app.service.llm_adapter import DeliveryLLMAdapter, _sanitize_text


def _tool_call(name, args_json, call_id="tc1"):
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(name=name, arguments=args_json),
    )


class _Msg:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self):
        return {"role": "assistant", "content": self.content}


def _install_fake_litellm(sequence):
    """Each call to acompletion() returns the next item in `sequence`, in order.
    Returns the captured call kwargs list for assertions (e.g. tools presence)."""
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        msg = sequence[len(calls) - 1]
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

    mod = types.ModuleType("litellm")
    mod.acompletion = acompletion
    mod.drop_params = False
    sys.modules["litellm"] = mod
    return calls


@pytest.fixture
def adapter():
    a = DeliveryLLMAdapter()
    a._api_key = "test-key"
    a._model = "test-model"
    return a


def test_sanitize_text_strips_leaked_tool_call_syntax():
    """Regression (observed live with OpenRouter/Llama): a reply ending in raw
    tool-call syntax like 'signal_outcome{"outcome": "continue"}' must never
    reach the volunteer — that's an internal-mechanics leak the guardrails
    explicitly forbid."""
    leaked = ('Your request to reschedule the session has been noted by eVidyaloka. '
              'We will get back to you soon about the new schedule. '
              'signal_outcome{"outcome": "continue"}')
    cleaned = _sanitize_text(leaked)
    assert "signal_outcome" not in cleaned
    assert cleaned == ("Your request to reschedule the session has been noted by eVidyaloka. "
                        "We will get back to you soon about the new schedule.")


def test_sanitize_text_leaves_normal_prose_untouched():
    text = "Great, thanks for confirming! One more thing — are you ready for your first session?"
    assert _sanitize_text(text) == text


async def test_signal_outcome_leaked_tool_syntax_is_stripped_in_loop(adapter):
    """End-to-end through the loop: content carries prose + a leaked call — the
    caller must see clean prose only."""
    calls = _install_fake_litellm([
        _Msg('Noted, thanks! signal_outcome{"outcome": "continue"}',
             tool_calls=[_tool_call("signal_outcome", '{"outcome":"continue"}')]),
    ])
    executor = AsyncMock(return_value={"status": "ok"})
    text, collected = await adapter.run_conversation_loop(
        "SYS", [{"role": "user", "content": "ok"}], executor)
    assert text == "Noted, thanks!"
    assert len(calls) == 1


async def test_signal_outcome_with_text_returns_immediately(adapter):
    """Model writes prose alongside signal_outcome — use it as-is, no extra call."""
    calls = _install_fake_litellm([
        _Msg("Here's your update!", tool_calls=[_tool_call("signal_outcome", '{"outcome":"continue"}')]),
    ])
    executor = AsyncMock(return_value={"status": "ok"})
    text, collected = await adapter.run_conversation_loop(
        "SYS", [{"role": "user", "content": "hi"}], executor)
    assert text == "Here's your update!"
    assert collected["signal_outcome"] == {"status": "ok"}
    assert len(calls) == 1


async def test_signal_outcome_with_empty_text_gets_a_followup_turn(adapter):
    """Regression (observed live with OpenRouter/Llama): the model can front-load
    signal_outcome with NO prose. It must get one more, tools-off turn to produce
    the reply it owes the volunteer — never silently return empty text when the
    model still has something to say."""
    calls = _install_fake_litellm([
        _Msg("", tool_calls=[_tool_call("signal_outcome", '{"outcome":"continue"}')]),
        _Msg("Your next session is Monday at 10am."),
    ])
    executor = AsyncMock(return_value={"status": "ok"})
    text, collected = await adapter.run_conversation_loop(
        "SYS", [{"role": "user", "content": "any update?"}], executor)
    assert text == "Your next session is Monday at 10am."
    assert len(calls) == 2
    assert "tools" not in calls[1]  # follow-up turn is tools-off, can't loop forever


async def test_signal_outcome_followup_also_empty_returns_empty_string(adapter):
    """If even the follow-up turn produces nothing, return an empty string (not
    a canned message) — delivery_logic's _synthesize_ack / fallback gets the
    final say over what the volunteer actually sees."""
    calls = _install_fake_litellm([
        _Msg("", tool_calls=[_tool_call("signal_outcome", '{"outcome":"continue"}')]),
        _Msg(""),
    ])
    executor = AsyncMock(return_value={"status": "ok"})
    text, collected = await adapter.run_conversation_loop(
        "SYS", [{"role": "user", "content": "any update?"}], executor)
    assert text == ""
    assert collected["signal_outcome"] == {"status": "ok"}
    assert len(calls) == 2
