"""Turn-logic tests — domain_client and LLM are mocked, no I/O."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.service import delivery_logic as dl
from app.schemas.delivery_schemas import (
    DeliveryAgentTurnRequest, DeliverySessionState, ActivationStage, OpsStage,
)


def _request(stage=ActivationStage.ACTIVATION_STARTED.value, msg="hi", sub_state=None,
             persona="new_volunteer", channel_metadata=None):
    sid = uuid4()
    return DeliveryAgentTurnRequest(
        session_id=sid,
        session_state=DeliverySessionState(id=sid, stage=stage, sub_state=sub_state, persona=persona),
        user_message=msg,
        channel_metadata=channel_metadata,
    )


def _delivery(activation_complete=False, status="activating"):
    return {
        "id": str(uuid4()), "volunteer_name": "Asha Rao", "programme": "eVidyaloka",
        "entity_id": "school-1", "delivery_status": status,
        "activation_completed_at": "2026-07-18T00:00:00" if activation_complete else None,
        "volunteer_acknowledged": False, "first_session_ready": False,
        "completed_sessions": 0, "expected_sessions": 3,
    }


@pytest.fixture
def patch_clients(monkeypatch):
    dc = AsyncMock()
    dc.save_message.return_value = {"status": "success"}
    dc.advance_state.return_value = {"status": "success"}
    dc.log_event.return_value = {"status": "success"}
    dc.update_status.return_value = {"status": "success"}
    dc.emit_handoff_event.return_value = {"status": "success"}
    dc.get_activation_content.return_value = {"status": "success", "content": ""}
    monkeypatch.setattr(dl, "domain_client", dc)
    llm = AsyncMock()
    monkeypatch.setattr(dl, "llm_adapter", llm)
    # keep the real fallback string
    llm._fallback = lambda: "fallback"
    return dc, llm


async def test_missing_context_blocks_activation(patch_clients):
    dc, llm = patch_clients
    dc.get_context.return_value = {"status": "not_found"}
    resp = await dl.delivery_agent_service.process_turn(_request())
    assert resp.state == ActivationStage.ACTIVATION_BLOCKED.value
    assert "team" in resp.assistant_message.lower()
    # LLM should never be called when there is no delivery
    llm.run_conversation_loop.assert_not_called()


async def test_activation_mode_dispatch(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Welcome!", {})
    resp = await dl.delivery_agent_service.process_turn(_request())
    llm.build_activation_prompt.assert_called_once()
    assert resp.state in (ActivationStage.ACTIVATION_STARTED.value,
                          ActivationStage.VOLUNTEER_ACKNOWLEDGED.value)
    assert resp.assistant_message == "Welcome!"


async def test_activation_complete_moves_to_operations(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    dc.complete_activation.return_value = {"status": "success"}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("You're all set!", {
        "signal_outcome": {"outcome": "activation_complete"}})
    resp = await dl.delivery_agent_service.process_turn(_request())
    dc.complete_activation.assert_awaited_once()
    assert resp.state == OpsStage.DELIVERY_OPERATIONS.value


async def test_premature_activation_complete_gives_honest_prompt_not_fallback(patch_clients):
    """Regression: if the LLM calls signal_outcome(activation_complete) before
    first_session_ready is confirmed, complete_activation blocks it. The reply
    must be a specific, honest follow-up prompt — NOT the generic 'trouble
    responding' outage message, since nothing actually failed."""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    dc.complete_activation.return_value = {"status": "blocked", "missing": ["first_session_ready"]}
    llm.build_activation_prompt.return_value = "SYS"
    llm._fallback = lambda: "I'm having a little trouble responding right now. Could you please send that again?"
    # LLM's tool-call-only message has empty text — this is what triggered the bug
    llm.run_conversation_loop.return_value = ("", {
        "confirm_acknowledgement": {"status": "success"},
        "signal_outcome": {"outcome": "activation_complete"}})
    resp = await dl.delivery_agent_service.process_turn(_request())
    assert "trouble responding" not in resp.assistant_message.lower()
    assert "first session" in resp.assistant_message.lower()
    # Still gated in activation — must NOT have advanced to daily operations
    assert resp.state != OpsStage.DELIVERY_OPERATIONS.value


async def test_confirm_readiness_blocked_without_prior_acknowledgement(patch_clients):
    """Live-testing finding: a single vague 'yes I confirm I'm taking this on'
    let a weaker model call confirm_acknowledgement AND confirm_readiness in the
    same turn, marking someone ready for a session they were never actually
    shown. Readiness may only be recorded once acknowledgement was ALREADY true
    before this turn started — never in the same turn it was first granted."""
    dc, llm = patch_clients
    result = await dl.delivery_agent_service._execute_tool(
        "confirm_readiness", {}, delivery_id="d1", pre_turn_acknowledged=False)
    assert result["status"] == "blocked"
    dc.confirm_first_session_readiness.assert_not_called()


async def test_confirm_readiness_allowed_after_prior_acknowledgement(patch_clients):
    dc, llm = patch_clients
    dc.confirm_first_session_readiness.return_value = {"status": "success"}
    result = await dl.delivery_agent_service._execute_tool(
        "confirm_readiness", {}, delivery_id="d1", pre_turn_acknowledged=True)
    assert result["status"] == "success"
    dc.confirm_first_session_readiness.assert_awaited_once_with("d1")


async def test_synthesize_ack_readiness_blocked_asks_for_acknowledgement(patch_clients):
    msg = dl.delivery_agent_service._synthesize_ack({"confirm_readiness": {"status": "blocked"}})
    assert "acknowledge" in msg.lower()


async def test_activation_complete_blocked_overrides_llm_prose(patch_clients):
    """If the deterministic gate rejects activation_complete, the honest missing-
    fields prompt must win even when the LLM already wrote its own (incorrect,
    premature) success prose — otherwise a volunteer reads 'you're all set!'
    for a session they were never actually confirmed ready for."""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    dc.complete_activation.return_value = {"status": "blocked", "missing": ["first_session_ready"]}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("You're all set for your first session!", {
        "confirm_acknowledgement": {"status": "success"},
        "signal_outcome": {"outcome": "activation_complete"}})
    resp = await dl.delivery_agent_service.process_turn(_request())
    assert resp.assistant_message != "You're all set for your first session!"
    assert resp.assistant_message.endswith("?")
    assert "first session" in resp.assistant_message.lower()
    assert resp.state != OpsStage.DELIVERY_OPERATIONS.value


async def test_operations_mode_records_and_checks_escalation(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [{"id": "s1", "subject": "Math",
                                    "scheduled_date": "2026-07-20", "session_state": "completion_check_sent"}],
                                   "blockers": []}
    dc.evaluate_delivery_health.return_value = {"status": "success",
                                                "signals": {"consecutive_missed": 0, "consecutive_unverified": 0,
                                                           "stale_blocker_count": 0, "reschedule_count": 0}}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Noted, thanks!", {
        "record_session_outcome": {"status": "success"},
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="we finished the class"))
    dc.evaluate_delivery_health.assert_awaited()  # health evaluated after outcome
    assert resp.state == OpsStage.DELIVERY_OPERATIONS.value


async def test_execute_tool_record_outcome_autocorrects_single_open_session(patch_clients):
    """Regression: a smaller/free-tier LLM can send a placeholder like
    "today's session id" instead of the real UUID. When exactly one session is
    open, that's unambiguous — auto-correct rather than fail the recording."""
    dc, llm = patch_clients
    dc.record_session_outcome.return_value = {"status": "success"}
    sessions = [{"id": "real-session-id", "session_state": "completion_check_sent"}]
    result = await dl.delivery_agent_service._execute_tool(
        "record_session_outcome", {"scheduled_session_id": "today's session id", "outcome": "completed"},
        delivery_id="d1", sessions=sessions,
    )
    assert dc.record_session_outcome.call_args.args[0] == "real-session-id"
    assert result == {"status": "success"}


async def test_execute_tool_prefers_session_awaiting_completion_answer(patch_clients):
    """One session already asked-about (completion_check_sent) + one still
    upcoming: a 'yes it happened' reply can only be about the asked-about one,
    so it resolves there without needing to ask."""
    dc, llm = patch_clients
    dc.record_session_outcome.return_value = {"status": "success"}
    sessions = [{"id": "upcoming1", "session_state": "upcoming", "scheduled_date": "2026-07-25"},
                {"id": "asked1", "session_state": "completion_check_sent", "scheduled_date": "2026-07-18"}]
    await dl.delivery_agent_service._execute_tool(
        "record_session_outcome", {"scheduled_session_id": "bogus", "outcome": "completed"},
        delivery_id="d1", sessions=sessions, user_message="yes it happened",
    )
    assert dc.record_session_outcome.call_args.args[0] == "asked1"


async def test_execute_tool_refuses_when_two_sessions_awaiting_and_no_hint(patch_clients):
    """Two completion checks outstanding and a bare 'yes' — genuinely ambiguous.
    Must NOT guess: returns needs_clarification so the agent asks which one."""
    dc, llm = patch_clients
    sessions = [{"id": "a", "session_state": "completion_check_sent", "scheduled_date": "2026-07-16", "subject": "Math"},
                {"id": "b", "session_state": "completion_check_sent", "scheduled_date": "2026-07-18", "subject": "Math"}]
    result = await dl.delivery_agent_service._execute_tool(
        "record_session_outcome", {"scheduled_session_id": "bogus", "outcome": "completed"},
        delivery_id="d1", sessions=sessions, user_message="yes it happened",
    )
    dc.record_session_outcome.assert_not_called()
    assert result["status"] == "needs_clarification"
    assert len(result["sessions"]) == 2


async def test_execute_tool_disambiguates_two_sessions_by_date_in_message(patch_clients):
    """Two outstanding checks, but the volunteer names a date — record that one."""
    dc, llm = patch_clients
    dc.record_session_outcome.return_value = {"status": "success"}
    sessions = [{"id": "a", "session_state": "completion_check_sent", "scheduled_date": "2026-07-16", "subject": "Math"},
                {"id": "b", "session_state": "completion_check_sent", "scheduled_date": "2026-07-18", "subject": "Math"}]
    await dl.delivery_agent_service._execute_tool(
        "record_session_outcome", {"scheduled_session_id": "bogus", "outcome": "completed"},
        delivery_id="d1", sessions=sessions, user_message="the 2026-07-18 class happened",
    )
    assert dc.record_session_outcome.call_args.args[0] == "b"


async def test_execute_tool_disambiguates_by_weekday_in_message(patch_clients):
    """Volunteer says the weekday name rather than the ISO date."""
    dc, llm = patch_clients
    dc.record_session_outcome.return_value = {"status": "success"}
    # 2026-07-16 is a Thursday, 2026-07-18 is a Saturday
    sessions = [{"id": "thu", "session_state": "completion_check_sent", "scheduled_date": "2026-07-16", "subject": "Math"},
                {"id": "sat", "session_state": "completion_check_sent", "scheduled_date": "2026-07-18", "subject": "Math"}]
    await dl.delivery_agent_service._execute_tool(
        "record_session_outcome", {"scheduled_session_id": "bogus", "outcome": "completed"},
        delivery_id="d1", sessions=sessions, user_message="Thursday's class went well",
    )
    assert dc.record_session_outcome.call_args.args[0] == "thu"


async def test_execute_tool_record_outcome_trusts_valid_session_id(patch_clients):
    dc, llm = patch_clients
    dc.record_session_outcome.return_value = {"status": "success"}
    sessions = [{"id": "s1", "session_state": "upcoming"}]
    await dl.delivery_agent_service._execute_tool(
        "record_session_outcome", {"scheduled_session_id": "s1", "outcome": "completed"},
        delivery_id="d1", sessions=sessions,
    )
    assert dc.record_session_outcome.call_args.args[0] == "s1"


async def test_execute_tool_disambiguates_by_relative_day(patch_clients):
    """Volunteer says 'yesterday' — resolve to the session dated yesterday in the
    delivery timezone, without asking."""
    from datetime import datetime as _dt, timedelta as _td
    dc, llm = patch_clients
    dc.record_session_outcome.return_value = {"status": "success"}
    # Compute "today" exactly as the resolver does — tz-aware if tzdata is present,
    # else naive local — so the expectation matches the code on any platform.
    try:
        from zoneinfo import ZoneInfo
        base = _dt.now(ZoneInfo(dl.delivery_agent_service.cfg.timezone)).date()
    except Exception:
        base = _dt.now().date()
    yesterday = (base - _td(days=1)).isoformat()
    older = (base - _td(days=5)).isoformat()
    sessions = [{"id": "old", "session_state": "completion_check_sent", "scheduled_date": older, "subject": "Math"},
                {"id": "yday", "session_state": "completion_check_sent", "scheduled_date": yesterday, "subject": "Math"}]
    await dl.delivery_agent_service._execute_tool(
        "record_session_outcome", {"scheduled_session_id": "bogus", "outcome": "completed"},
        delivery_id="d1", sessions=sessions, user_message="yes, yesterday's class happened",
    )
    assert dc.record_session_outcome.call_args.args[0] == "yday"


async def test_ambiguous_tool_turn_asks_which_session_not_outage(patch_clients):
    """End-to-end regression for the reported bug: two completion checks
    outstanding + a bare 'yes it happened'. The LLM records nothing (tool returns
    needs_clarification) and writes no prose. The reply must be a 'which session?'
    clarification listing the dates — NEVER the generic outage fallback."""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    sessions = [{"id": "a", "session_state": "completion_check_sent", "scheduled_date": "2026-07-16", "subject": "Math"},
                {"id": "b", "session_state": "completion_check_sent", "scheduled_date": "2026-07-18", "subject": "Math"}]
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": sessions, "blockers": []}
    dc.record_session_outcome.return_value = {"status": "success"}
    llm.build_operations_prompt.return_value = "SYS"
    llm._fallback = lambda: "I'm having a little trouble responding right now. Could you please send that again?"

    async def _loop(system_prompt, messages, tool_executor, max_iterations=6):
        # Simulate the LLM: it calls record_session_outcome (which will come back
        # needs_clarification) then signal_outcome(continue), writing NO prose.
        rec = await tool_executor("record_session_outcome",
                                  {"scheduled_session_id": "bogus", "outcome": "completed"})
        return "", {"record_session_outcome": rec, "signal_outcome": {"outcome": "continue"}}

    llm.run_conversation_loop = _loop
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="yes it happened"))
    dc.record_session_outcome.assert_not_called()  # never guessed
    assert "trouble responding" not in resp.assistant_message.lower()
    assert "which one" in resp.assistant_message.lower()
    assert "2026-07-16" in resp.assistant_message and "2026-07-18" in resp.assistant_message


async def test_premature_delivery_complete_blocked_until_all_sessions_done(patch_clients):
    """Regression: the LLM signalling delivery_complete after only 1 of 3
    sessions must NOT close the delivery. Real completed/expected counts gate it,
    matching the spec: 'Completed Delivery — use only when required completion
    criteria satisfied.'"""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    delivery["completed_sessions"] = 1
    delivery["expected_sessions"] = 3
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("", {
        "record_session_outcome": {"status": "success"},
        "signal_outcome": {"outcome": "delivery_complete"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="we finished the class"))
    assert resp.state == OpsStage.DELIVERY_OPERATIONS.value
    assert "session" in resp.assistant_message.lower()
    dc.update_status.assert_not_awaited()  # delivery must NOT be marked completed/anything else


async def test_delivery_complete_succeeds_when_all_sessions_done(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    delivery["completed_sessions"] = 3
    delivery["expected_sessions"] = 3
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("All done, thank you!", {
        "signal_outcome": {"outcome": "delivery_complete"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="that was the last class"))
    assert resp.state == OpsStage.DELIVERY_COMPLETE.value
    assert dc.update_status.call_args.args[1] == "completed"


async def test_delivery_complete_terminal_guard_returns_early(patch_clients):
    """DELIVERY_COMPLETE is the one genuinely terminal stage: a finished
    delivery has nothing left to process, so the guard short-circuits before
    any context/LLM work."""
    dc, llm = patch_clients
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_COMPLETE.value, msg="hello"))
    dc.get_context.assert_not_called()
    llm.run_conversation_loop.assert_not_called()
    assert resp.state == OpsStage.DELIVERY_COMPLETE.value


async def test_paused_stage_is_resumable_not_a_dead_end(patch_clients):
    """Regression (found via live testing): PAUSED must never be a blanket
    terminal guard the way delivery_complete is — policy_engine's own
    transition table explicitly allows resuming out of paused into every
    earlier stage. Previously any message sent while paused just re-showed
    the canned "we can pick this up" line forever, because the terminal guard
    short-circuited before the message was ever processed. It must now
    actually run the turn, and delivery_status must come back out of "paused"
    too — otherwise reminder suppression stays stuck even after the
    conversation resumes."""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="paused")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Welcome back!", {
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage="paused", msg="I'm back, let's continue"))
    dc.get_context.assert_called()
    llm.run_conversation_loop.assert_called()
    assert resp.state == OpsStage.DELIVERY_OPERATIONS.value
    assert dc.update_status.call_args.args[0] == delivery["id"]
    assert dc.update_status.call_args.args[1] == "active"


async def test_human_review_is_resumable_and_clears_escalated_status(patch_clients):
    """Same bug, same fix, on the sibling control stage: escalation sets
    delivery_status='escalated' (which suppresses ALL reminders), and nothing
    ever reset it back — a resumed conversation would silently never remind
    the volunteer again. Also covers the transition-table gap: human_review
    previously could only resume to activation_started/delivery_operations,
    so a volunteer who escalated mid-activation (past the first step) got
    stuck forever even once the status bug was fixed."""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="escalated")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Thanks for your patience, let's continue.", {
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage="human_review", msg="Sorry about that, I'm ready to continue now"))
    assert resp.state == OpsStage.DELIVERY_OPERATIONS.value
    assert dc.update_status.call_args.args[0] == delivery["id"]
    assert dc.update_status.call_args.args[1] == "active"


async def test_log_blocker_failure_gives_honest_message_not_false_confirmation(patch_clients):
    """Regression: log_blocker's DB write can fail (bad session reference,
    transient MCP error). Unlike record_session_outcome/confirm_acknowledgement,
    nothing downstream ever re-verifies a blocker was actually saved — so if the
    turn claims "I've noted it" regardless of the tool's real status, the
    volunteer is falsely reassured and the blocker is silently lost forever."""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("", {
        "log_blocker": {"status": "error", "error": "invalid scheduled_session_id"},
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="the meeting link is broken"))
    assert "noted" not in resp.assistant_message.lower()
    assert "wasn't able to save" in resp.assistant_message.lower()


async def test_capture_reschedule_failure_gives_honest_message_not_false_confirmation(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("", {
        "capture_reschedule_request": {"status": "error", "error": "invalid scheduled_session_id"},
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="can we move this session?"))
    assert "captured" not in resp.assistant_message.lower()
    assert "wasn't able to save" in resp.assistant_message.lower()


# ── Full-spec expansion: coordinator wiring ─────────────────────────────────────

async def test_coordinator_persona_routes_acknowledgement_as_coordinator(patch_clients):
    """_execute_tool is the actual site of the party-routing logic — the LLM
    tool-loop itself is fully mocked in these tests (run_conversation_loop's
    return_value is injected directly), so exercising it means calling
    _execute_tool directly, the same pattern the existing resolver tests use."""
    dc, llm = patch_clients
    dc.confirm_acknowledgement.return_value = {"status": "success"}
    await dl.delivery_agent_service._execute_tool(
        "confirm_acknowledgement", {}, delivery_id="d1", persona="coordinator")
    dc.confirm_acknowledgement.assert_awaited_with("d1", "coordinator")


async def test_volunteer_persona_still_routes_acknowledgement_as_volunteer(patch_clients):
    """Regression guard: adding coordinator support must not change the
    default/volunteer path."""
    dc, llm = patch_clients
    dc.confirm_acknowledgement.return_value = {"status": "success"}
    await dl.delivery_agent_service._execute_tool(
        "confirm_acknowledgement", {}, delivery_id="d1", persona="new_volunteer")
    dc.confirm_acknowledgement.assert_awaited_with("d1", "volunteer")


async def test_coordinator_phone_captured_on_first_contact(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    delivery["coordinator_phone"] = None
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Hi!", {})
    await dl.delivery_agent_service.process_turn(
        _request(stage=ActivationStage.ACTIVATION_STARTED.value, msg="hi", persona="coordinator",
                 channel_metadata={"phone_number": "+911234567890"}))
    dc.set_coordinator_phone.assert_awaited_with(delivery["id"], "+911234567890")


async def test_coordinator_phone_not_recaptured_if_already_on_file(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    delivery["coordinator_phone"] = "+911111111111"
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Hi!", {})
    await dl.delivery_agent_service.process_turn(
        _request(stage=ActivationStage.ACTIVATION_STARTED.value, msg="hi", persona="coordinator",
                 channel_metadata={"phone_number": "+922222222222"}))
    dc.set_coordinator_phone.assert_not_awaited()


# ── Full-spec expansion: notify_linked_stakeholder honesty ─────────────────────

async def test_notify_stakeholder_sent_gives_positive_ack(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("", {
        "notify_linked_stakeholder": {"status": "success", "notification": {"status": "sent"}},
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="please tell my coordinator"))
    assert "let your coordinator know" in resp.assistant_message.lower()


async def test_notify_stakeholder_no_contact_gives_honest_message(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("", {
        "notify_linked_stakeholder": {"status": "success",
                                      "notification": {"status": "no_contact_on_file"}},
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="please tell my coordinator"))
    assert "let your coordinator know" not in resp.assistant_message.lower()
    assert "couldn't reach them" in resp.assistant_message.lower()


async def test_notify_stakeholder_send_failed_gives_honest_message(patch_clients):
    """Regression: the outer MCP call succeeding (status='success', the write
    was recorded) must never be read as the actual WhatsApp send succeeding —
    those are two different things, checked at two different layers."""
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("", {
        "notify_linked_stakeholder": {"status": "success", "notification": {"status": "failed"}},
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="please tell my coordinator"))
    assert "let your coordinator know" not in resp.assistant_message.lower()
    assert "wasn't able to reach" in resp.assistant_message.lower()


# ── Full-spec expansion: phase-aware pause/escalate stages ─────────────────────

async def test_pause_during_activation_uses_activation_paused_stage(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Sure, talk later!", {
        "signal_outcome": {"outcome": "paused"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=ActivationStage.ACTIVATION_STARTED.value, msg="pause please"))
    assert resp.state == "activation_paused"


async def test_pause_during_operations_uses_plain_paused_stage(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=True, status="active")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_operations_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Sure, talk later!", {
        "signal_outcome": {"outcome": "paused"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=OpsStage.DELIVERY_OPERATIONS.value, msg="pause please"))
    assert resp.state == "paused"


async def test_escalate_during_activation_uses_activation_escalated_stage(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False)
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("I've flagged this.", {
        "signal_outcome": {"outcome": "escalate", "reason": "sensitive issue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage=ActivationStage.VOLUNTEER_ACKNOWLEDGED.value, msg="I need help"))
    assert resp.state == "activation_escalated"


async def test_resume_from_activation_paused_resets_status_to_activating(patch_clients):
    dc, llm = patch_clients
    delivery = _delivery(activation_complete=False, status="paused")
    dc.get_context.return_value = {"status": "success", "delivery": delivery,
                                   "scheduled_sessions": [], "blockers": []}
    llm.build_activation_prompt.return_value = "SYS"
    llm.run_conversation_loop.return_value = ("Welcome back!", {
        "signal_outcome": {"outcome": "continue"}})
    resp = await dl.delivery_agent_service.process_turn(
        _request(stage="activation_paused", msg="I'm back"))
    assert resp.state == ActivationStage.ACTIVATION_STARTED.value
    assert dc.update_status.call_args.args[0] == delivery["id"]
    assert dc.update_status.call_args.args[1] == "activating"
