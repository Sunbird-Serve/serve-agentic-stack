"""Unit tests for the delivery policy engine (pure functions, no I/O)."""
from datetime import datetime, timedelta

from app.service import policy_engine as pe

CFG = pe.DeliveryConfig(
    pre_session_minutes=45, followup_delay_minutes=60,
    unverified_grace_minutes=60, escalation_miss_threshold=2,
    escalation_unverified_threshold=2,
)


def _candidate(sent=None, state="upcoming", outcome=None, status="active",
               date="2026-07-20", start="10:00", end="11:00"):
    return {
        "delivery_id": "d1", "delivery_status": status,
        "sent_reminder_types": sent or [],
        "session": {"id": "s1", "scheduled_date": date, "start_time": start,
                    "end_time": end, "subject": "Math", "session_state": state, "outcome": outcome},
    }


# ── parse_session_datetime ────────────────────────────────────────────────────

def test_parse_datetime_basic():
    dt = pe.parse_session_datetime("2026-07-20", "10:30")
    assert dt == datetime(2026, 7, 20, 10, 30)


def test_parse_datetime_missing_time_defaults_midnight():
    assert pe.parse_session_datetime("2026-07-20", None) == datetime(2026, 7, 20, 0, 0)


def test_parse_datetime_bad_date_returns_none():
    assert pe.parse_session_datetime("not-a-date", "10:00") is None


# ── Suppression ───────────────────────────────────────────────────────────────

def test_suppress_when_delivery_paused():
    assert pe.suppression_reason(_candidate(status="paused")) == "delivery_paused"


def test_suppress_when_session_cancelled():
    assert pe.suppression_reason(_candidate(state="cancelled")) == "session_cancelled"


def test_suppress_when_completed():
    assert pe.suppression_reason(_candidate(outcome="completed")) == "session_completed"


def test_no_suppression_for_active_upcoming():
    assert pe.suppression_reason(_candidate()) is None


# ── Reminder due windows ──────────────────────────────────────────────────────

def test_session_day_due_on_the_day_before_start():
    now = datetime(2026, 7, 20, 8, 0)  # morning, before 10:00 start
    assert pe.SESSION_DAY in pe.due_reminders(_candidate(), now, CFG)


def test_session_day_not_due_day_before():
    now = datetime(2026, 7, 19, 8, 0)
    assert pe.SESSION_DAY not in pe.due_reminders(_candidate(), now, CFG)


def test_pre_session_due_within_window():
    now = datetime(2026, 7, 20, 9, 30)  # 30 min before 10:00 (window is 45)
    due = pe.due_reminders(_candidate(sent=[pe.SESSION_DAY]), now, CFG)
    assert pe.PRE_SESSION in due


def test_pre_session_not_due_before_window_opens():
    now = datetime(2026, 7, 20, 9, 0)  # 60 min before, window is 45
    due = pe.due_reminders(_candidate(sent=[pe.SESSION_DAY]), now, CFG)
    assert pe.PRE_SESSION not in due


def test_completion_check_due_after_end():
    now = datetime(2026, 7, 20, 11, 30)  # after 11:00 end
    due = pe.due_reminders(_candidate(sent=[pe.SESSION_DAY, pe.PRE_SESSION]), now, CFG)
    assert pe.COMPLETION_CHECK in due


def test_completion_check_not_due_if_outcome_recorded():
    now = datetime(2026, 7, 20, 11, 30)
    due = pe.due_reminders(_candidate(sent=[pe.COMPLETION_CHECK], outcome="completed"), now, CFG)
    assert due == []  # suppressed by completed outcome


def test_already_sent_not_resent():
    now = datetime(2026, 7, 20, 8, 0)
    due = pe.due_reminders(_candidate(sent=[pe.SESSION_DAY]), now, CFG)
    assert pe.SESSION_DAY not in due


def test_followup_due_after_delay_when_completion_unanswered():
    now = datetime(2026, 7, 20, 12, 5)  # >60 min after 11:00 end
    cand = _candidate(sent=[pe.COMPLETION_CHECK])
    assert pe.FOLLOWUP_NUDGE in pe.due_reminders(cand, now, CFG)


def test_followup_not_due_before_delay():
    now = datetime(2026, 7, 20, 11, 30)  # only 30 min after end
    cand = _candidate(sent=[pe.COMPLETION_CHECK])
    assert pe.FOLLOWUP_NUDGE not in pe.due_reminders(cand, now, CFG)


def test_only_one_followup_ever():
    now = datetime(2026, 7, 20, 14, 0)
    cand = _candidate(sent=[pe.COMPLETION_CHECK, pe.FOLLOWUP_NUDGE])
    assert pe.FOLLOWUP_NUDGE not in pe.due_reminders(cand, now, CFG)


# ── Unverified rule ───────────────────────────────────────────────────────────

def test_mark_unverified_after_grace():
    now = datetime(2026, 7, 20, 13, 5)  # end 11:00 + 60 delay + 60 grace = 13:00
    cand = _candidate(sent=[pe.COMPLETION_CHECK, pe.FOLLOWUP_NUDGE])
    assert pe.should_mark_unverified(cand, now, CFG) is True


def test_not_unverified_before_grace():
    now = datetime(2026, 7, 20, 12, 30)
    cand = _candidate(sent=[pe.COMPLETION_CHECK, pe.FOLLOWUP_NUDGE])
    assert pe.should_mark_unverified(cand, now, CFG) is False


def test_not_unverified_without_followup():
    now = datetime(2026, 7, 20, 15, 0)
    cand = _candidate(sent=[pe.COMPLETION_CHECK])
    assert pe.should_mark_unverified(cand, now, CFG) is False


def test_not_unverified_if_outcome_present():
    now = datetime(2026, 7, 20, 15, 0)
    cand = _candidate(sent=[pe.COMPLETION_CHECK, pe.FOLLOWUP_NUDGE], outcome="completed")
    assert pe.should_mark_unverified(cand, now, CFG) is False


# ── Escalation ────────────────────────────────────────────────────────────────

def test_escalate_on_two_consecutive_missed():
    v = pe.evaluate_escalation({"consecutive_missed": 2, "consecutive_unverified": 0}, CFG)
    assert v["escalate"] is True and v["reasons"]


def test_no_escalate_on_one_missed():
    v = pe.evaluate_escalation({"consecutive_missed": 1, "consecutive_unverified": 1}, CFG)
    assert v["escalate"] is False


def test_escalate_on_two_unverified():
    v = pe.evaluate_escalation({"consecutive_missed": 0, "consecutive_unverified": 2}, CFG)
    assert v["escalate"] is True


# ── Transition table ──────────────────────────────────────────────────────────

def test_valid_activation_progression():
    assert pe.is_valid_transition("activation_started", "volunteer_acknowledged")
    assert pe.is_valid_transition("volunteer_acknowledged", "first_session_ready")
    assert pe.is_valid_transition("first_session_ready", "activation_completed")
    assert pe.is_valid_transition("activation_completed", "delivery_operations")


def test_self_loop_allowed():
    assert pe.is_valid_transition("delivery_operations", "delivery_operations")


def test_invalid_jump_rejected():
    # delivery_complete is only reachable from delivery_operations
    assert not pe.is_valid_transition("activation_started", "delivery_complete")
    assert not pe.is_valid_transition("volunteer_acknowledged", "delivery_complete")
    # operations cannot silently drop back to activation
    assert not pe.is_valid_transition("delivery_operations", "activation_started")


def test_activation_can_shortcut_to_operations():
    # complete_activation gates the real DB flags, so a single turn that both
    # acknowledges and confirms readiness may jump straight to operations.
    assert pe.is_valid_transition("activation_started", "delivery_operations")


def test_pause_can_resume():
    assert pe.is_valid_transition("paused", "delivery_operations")


def test_human_review_can_resume_to_any_activation_progress_stage():
    """Regression: human_review previously only allowed resuming to
    activation_started or delivery_operations. A volunteer who escalates mid
    activation (already past volunteer_acknowledged or first_session_ready)
    must be able to resume exactly where they left off, the same as paused."""
    assert pe.is_valid_transition("human_review", "activation_started")
    assert pe.is_valid_transition("human_review", "volunteer_acknowledged")
    assert pe.is_valid_transition("human_review", "first_session_ready")
    assert pe.is_valid_transition("human_review", "activation_completed")
    assert pe.is_valid_transition("human_review", "delivery_operations")


def test_activation_paused_can_resume_to_any_activation_progress_stage():
    """Full-spec expansion: activation_paused mirrors paused's full resume set."""
    assert pe.is_valid_transition("activation_paused", "activation_started")
    assert pe.is_valid_transition("activation_paused", "volunteer_acknowledged")
    assert pe.is_valid_transition("activation_paused", "first_session_ready")
    assert pe.is_valid_transition("activation_paused", "activation_completed")
    assert pe.is_valid_transition("activation_paused", "delivery_operations")


def test_activation_escalated_can_resume_to_any_activation_progress_stage():
    assert pe.is_valid_transition("activation_escalated", "activation_started")
    assert pe.is_valid_transition("activation_escalated", "volunteer_acknowledged")
    assert pe.is_valid_transition("activation_escalated", "first_session_ready")
    assert pe.is_valid_transition("activation_escalated", "activation_completed")
    assert pe.is_valid_transition("activation_escalated", "delivery_operations")


# ── evaluate_delivery_health ────────────────────────────────────────────────────

def test_evaluate_delivery_health_clean_signals_no_escalate():
    signals = {"consecutive_missed": 0, "consecutive_unverified": 0,
               "stale_blocker_count": 0, "reschedule_count": 0}
    v = pe.evaluate_delivery_health(signals, CFG)
    assert v["escalate"] is False
    assert v["reasons"] == []


def test_evaluate_delivery_health_flags_stale_blockers():
    signals = {"consecutive_missed": 0, "consecutive_unverified": 0,
               "stale_blocker_count": 2, "reschedule_count": 0}
    v = pe.evaluate_delivery_health(signals, CFG)
    assert v["escalate"] is True
    assert any("3+ days" in r for r in v["reasons"])


def test_evaluate_delivery_health_flags_reschedule_pattern():
    signals = {"consecutive_missed": 0, "consecutive_unverified": 0,
               "stale_blocker_count": 0, "reschedule_count": 2}
    v = pe.evaluate_delivery_health(signals, CFG)
    assert v["escalate"] is True
    assert any("recurring scheduling pattern" in r for r in v["reasons"])


def test_evaluate_delivery_health_still_includes_base_escalation_reasons():
    """evaluate_delivery_health must not lose evaluate_escalation's own signals."""
    signals = {"consecutive_missed": 2, "consecutive_unverified": 0,
               "stale_blocker_count": 0, "reschedule_count": 0}
    v = pe.evaluate_delivery_health(signals, CFG)
    assert v["escalate"] is True
    assert any("consecutive missed" in r for r in v["reasons"])


# ── Reminder templates ────────────────────────────────────────────────────────

def test_render_includes_link_and_subject():
    session = {"subject": "Science", "start_time": "10:00", "scheduled_date": "2026-07-20",
               "meeting_link": "https://x"}
    text = pe.render_reminder(pe.SESSION_DAY, session, {"volunteer_name": "Asha Rao"})
    assert "Science" in text and "https://x" in text and "Asha" in text


def test_render_completion_check_asks_did_it_happen():
    text = pe.render_reminder(pe.COMPLETION_CHECK, {"subject": "Math", "scheduled_date": "2026-07-20"}, {})
    assert "happen" in text.lower()
