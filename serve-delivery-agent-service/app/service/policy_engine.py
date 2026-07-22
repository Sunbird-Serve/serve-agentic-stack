"""
SERVE Delivery Agent Service - Policy Engine (pure functions, no I/O)

This module is the single source of truth for delivery *policy*:
  • which reminders are due for a scheduled session (and when to suppress them)
  • the one-follow-up-then-unverified rule
  • valid conversation-stage transitions
  • escalation thresholds
  • deterministic reminder text templates

Every function here is pure and unit-testable — no DB, no network, no clock
except the `now` passed in. The spec's core mandate lives here: reminders are a
deterministic function of schedule + state, never an LLM decision.

Time handling: `now` and session times are treated as school-local naive
datetimes. The reminder engine supplies `now`; tests supply fixed values.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("delivery.policy")

# Reminder types (ordered by when they fire)
SESSION_DAY = "session_day"
PRE_SESSION = "pre_session"
COMPLETION_CHECK = "completion_check"
FOLLOWUP_NUDGE = "followup_nudge"

# Session states considered terminal (no reminders, no further transitions)
_SESSION_TERMINAL = {"completed", "partially_completed", "missed", "cancelled"}
# Delivery statuses that suppress all reminders. Deliberately NOT including
# on_track/interrupted/resumed/nearing_completion/at_risk — those are still
# "ongoing" variants where reminders should keep flowing.
_DELIVERY_SUPPRESSED = {"paused", "completed", "escalated", "discontinued"}


@dataclass(frozen=True)
class DeliveryConfig:
    pre_session_minutes: int = 45
    followup_delay_minutes: int = 60
    # grace after the follow-up nudge before a silent session is marked unverified
    unverified_grace_minutes: int = 60
    escalation_miss_threshold: int = 2
    escalation_unverified_threshold: int = 2
    stale_blocker_days: int = 3
    reschedule_pattern_threshold: int = 2
    timezone: str = "Asia/Kolkata"

    @classmethod
    def from_env(cls) -> "DeliveryConfig":
        return cls(
            pre_session_minutes=int(os.environ.get("DELIVERY_PRE_SESSION_MINUTES", "45")),
            followup_delay_minutes=int(os.environ.get("DELIVERY_FOLLOWUP_DELAY_MINUTES", "60")),
            unverified_grace_minutes=int(os.environ.get("DELIVERY_UNVERIFIED_GRACE_MINUTES", "60")),
            escalation_miss_threshold=int(os.environ.get("DELIVERY_ESCALATION_MISS_THRESHOLD", "2")),
            escalation_unverified_threshold=int(os.environ.get("DELIVERY_ESCALATION_UNVERIFIED_THRESHOLD", "2")),
            stale_blocker_days=int(os.environ.get("DELIVERY_STALE_BLOCKER_DAYS", "3")),
            reschedule_pattern_threshold=int(os.environ.get("DELIVERY_RESCHEDULE_PATTERN_THRESHOLD", "2")),
            timezone=os.environ.get("DELIVERY_TIMEZONE", "Asia/Kolkata"),
        )


# ── Datetime helpers ──────────────────────────────────────────────────────────

def parse_session_datetime(date_str: Optional[str], time_str: Optional[str]) -> Optional[datetime]:
    """Combine an ISO date and an HH:MM time into a naive datetime. Returns None
    if the date is missing/invalid. Missing time defaults to 00:00."""
    if not date_str:
        return None
    try:
        d = datetime.fromisoformat(date_str.strip()).date() if "T" not in date_str \
            else datetime.fromisoformat(date_str.strip()).date()
    except ValueError:
        try:
            d = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    hour, minute = 0, 0
    if time_str:
        try:
            parts = time_str.strip().split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            hour, minute = 0, 0
    return datetime(d.year, d.month, d.day, hour, minute)


# ── Suppression ───────────────────────────────────────────────────────────────

def suppression_reason(candidate: Dict[str, Any]) -> Optional[str]:
    """Return a reason string if reminders for this candidate must be suppressed,
    else None. Candidate shape: {delivery_status, session:{...}, sent_reminder_types}."""
    status = candidate.get("delivery_status")
    if status in _DELIVERY_SUPPRESSED:
        return f"delivery_{status}"
    session = candidate.get("session", {})
    state = session.get("session_state")
    if state == "cancelled":
        return "session_cancelled"
    if session.get("outcome") in _SESSION_TERMINAL:
        return "session_completed"
    if state == "reschedule_requested":
        return "session_reschedule_pending"
    return None


# ── Reminder decisions ────────────────────────────────────────────────────────

def due_reminders(candidate: Dict[str, Any], now: datetime, cfg: DeliveryConfig) -> List[str]:
    """Return the reminder types that should be SENT for this candidate right now.

    Excludes reminders already recorded (candidate['sent_reminder_types']) and
    anything under a suppression condition. Deterministic — same inputs, same output.
    """
    if suppression_reason(candidate):
        return []

    session = candidate.get("session", {})
    sent = set(candidate.get("sent_reminder_types", []))
    date_str = session.get("scheduled_date")
    start_dt = parse_session_datetime(date_str, session.get("start_time"))
    end_dt = parse_session_datetime(date_str, session.get("end_time")) or (
        start_dt + timedelta(hours=1) if start_dt else None
    )
    if not start_dt:
        return []

    has_outcome = session.get("outcome") is not None
    due: List[str] = []

    # Session-day reminder — from the morning of the scheduled date onward
    if SESSION_DAY not in sent and now.date() >= start_dt.date() and now < start_dt:
        due.append(SESSION_DAY)

    # Pre-session reminder — within the configured window before start
    pre_window_open = start_dt - timedelta(minutes=cfg.pre_session_minutes)
    if PRE_SESSION not in sent and pre_window_open <= now < start_dt:
        due.append(PRE_SESSION)

    # Completion check — after the session's scheduled end
    if end_dt and COMPLETION_CHECK not in sent and now >= end_dt and not has_outcome:
        due.append(COMPLETION_CHECK)

    # Follow-up nudge — one only, after the completion check has gone unanswered
    if (end_dt and FOLLOWUP_NUDGE not in sent and COMPLETION_CHECK in sent
            and not has_outcome
            and now >= end_dt + timedelta(minutes=cfg.followup_delay_minutes)):
        due.append(FOLLOWUP_NUDGE)

    return due


def should_mark_unverified(candidate: Dict[str, Any], now: datetime, cfg: DeliveryConfig) -> bool:
    """True when the follow-up nudge was sent, the grace period has elapsed, and
    still no outcome — the session should be recorded unverified (never fabricated
    as missed or completed)."""
    session = candidate.get("session", {})
    sent = set(candidate.get("sent_reminder_types", []))
    if session.get("outcome") is not None:
        return False
    if FOLLOWUP_NUDGE not in sent:
        return False
    end_dt = parse_session_datetime(session.get("scheduled_date"), session.get("end_time")) \
        or parse_session_datetime(session.get("scheduled_date"), session.get("start_time"))
    if not end_dt:
        return False
    deadline = end_dt + timedelta(minutes=cfg.followup_delay_minutes + cfg.unverified_grace_minutes)
    return now >= deadline


# ── Escalation ────────────────────────────────────────────────────────────────

def evaluate_escalation(signals: Dict[str, int], cfg: DeliveryConfig) -> Dict[str, Any]:
    """Decide escalation from raw continuity signals (as returned by the MCP
    delivery_evaluate_escalation tool). Pure — thresholds from cfg."""
    reasons: List[str] = []
    missed = signals.get("consecutive_missed", 0)
    unverified = signals.get("consecutive_unverified", 0)
    if missed >= cfg.escalation_miss_threshold:
        reasons.append(f"{missed} consecutive missed sessions")
    if unverified >= cfg.escalation_unverified_threshold:
        reasons.append(f"{unverified} consecutive unverified sessions")
    return {"escalate": bool(reasons), "reasons": reasons}


def evaluate_delivery_health(signals: Dict[str, int], cfg: DeliveryConfig) -> Dict[str, Any]:
    """Richer than evaluate_escalation — same pure-judgment pattern (MCP's
    delivery_evaluate_delivery_health tool supplies raw signals; this applies
    the agent's own configurable thresholds), extended with blocker-age and
    reschedule-pattern signals on top of the same consecutive-miss/unverified
    counts. MCP's own convenience verdict is informational only — this
    function is the actual policy decision, matching evaluate_escalation's
    established precedent of never trusting MCP's verdict as final."""
    base = evaluate_escalation(signals, cfg)
    reasons: List[str] = list(base["reasons"])
    stale = signals.get("stale_blocker_count", 0)
    reschedules = signals.get("reschedule_count", 0)
    if stale:
        reasons.append(f"{stale} blocker(s) open {cfg.stale_blocker_days}+ days")
    if reschedules >= cfg.reschedule_pattern_threshold:
        reasons.append(f"{reschedules} reschedule requests — recurring scheduling pattern")
    return {"escalate": bool(reasons), "reasons": reasons}


# ── Stage transitions ─────────────────────────────────────────────────────────

# Note: the activation stages may jump straight to activation_completed /
# delivery_operations because complete_activation is separately gated on the
# real DB flags (acknowledged AND first-session-ready). A volunteer can satisfy
# both in a single turn, so the conversation stage advances in one step.
_ACTIVATION_TARGETS = {"activation_completed", "delivery_operations", "activation_blocked",
                       "paused", "human_review", "activation_paused", "activation_escalated"}
_VALID_TRANSITIONS = {
    "activation_started": {"volunteer_acknowledged", "first_session_ready"} | _ACTIVATION_TARGETS,
    "volunteer_acknowledged": {"first_session_ready"} | _ACTIVATION_TARGETS,
    "first_session_ready": _ACTIVATION_TARGETS,
    "activation_completed": {"delivery_operations", "paused", "human_review"},
    "activation_blocked": {"activation_started", "volunteer_acknowledged", "human_review", "paused"},
    "delivery_operations": {"delivery_operations", "delivery_complete", "paused", "human_review"},
    # Control stages can resume back into the flow. human_review mirrors paused's
    # full resume set: escalation can happen at any point in activation too, so
    # resuming must be able to land on wherever the volunteer's real progress
    # left off, not just activation_started.
    "paused": {"activation_started", "volunteer_acknowledged", "first_session_ready",
               "activation_completed", "delivery_operations", "human_review"},
    "human_review": {"activation_started", "volunteer_acknowledged", "first_session_ready",
                      "activation_completed", "delivery_operations", "paused"},
    # Activation-phase equivalents of paused/human_review (spec's per-phase
    # granularity) — identical resume set, since a pause/escalation during
    # activation must still be able to land wherever real progress left off.
    "activation_paused": {"activation_started", "volunteer_acknowledged", "first_session_ready",
                          "activation_completed", "delivery_operations", "activation_escalated"},
    "activation_escalated": {"activation_started", "volunteer_acknowledged", "first_session_ready",
                             "activation_completed", "delivery_operations", "activation_paused"},
}


def is_valid_transition(from_stage: str, to_stage: str) -> bool:
    """Whether a conversation-stage transition is permitted. Self-loops on the
    same stage are always allowed (a turn that doesn't advance)."""
    if from_stage == to_stage:
        return True
    return to_stage in _VALID_TRANSITIONS.get(from_stage, set())


# ── Reminder text templates (deterministic — no LLM) ──────────────────────────

def render_reminder(reminder_type: str, session: Dict[str, Any], delivery: Dict[str, Any]) -> str:
    """Render fixed reminder copy. Never model-generated — the spec requires the
    reminder content to be predictable."""
    name = (delivery.get("volunteer_name") or "there").split()[0] if delivery.get("volunteer_name") else "there"
    subject = session.get("subject") or "your session"
    start = session.get("start_time") or ""
    date_str = session.get("scheduled_date") or "today"
    link = session.get("meeting_link")
    link_line = f"\nJoin link: {link}" if link else ""

    if reminder_type == SESSION_DAY:
        return (f"Hi {name}! Reminder: you have a {subject} session today "
                f"({date_str}) at {start}.{link_line}\n"
                f"Please reply to confirm you're available.")
    if reminder_type == PRE_SESSION:
        return (f"Hi {name}, your {subject} session starts at {start}, in a little while."
                f"{link_line}\nReply here if you hit any issue joining.")
    if reminder_type == COMPLETION_CHECK:
        return (f"Hi {name}, did your {subject} session on {date_str} happen? "
                f"Reply: completed / partially / it didn't happen.")
    if reminder_type == FOLLOWUP_NUDGE:
        return (f"Hi {name}, just checking again about your {subject} session on {date_str}. "
                f"A quick reply helps us keep your record accurate — did it happen?")
    return f"Reminder about your {subject} session on {date_str}."
