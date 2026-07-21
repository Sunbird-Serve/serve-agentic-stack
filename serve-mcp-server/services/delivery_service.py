"""
SERVE MCP Server - Delivery Service

Persistence + data primitives for the delivery_assistant agent's post-handshake
delivery journey (activation + daily session operations).

Design split (matches the rest of the stack — MCP is the data layer, the agent
is the brain):
  • This service OWNS the delivery tables and enforces structural invariants
    (activation gating, duplicate-reminder prevention via unique constraint,
    completed-session counting).
  • Reminder scheduling *policy* (windows, suppression, follow-up limits) and
    conversation state transitions live in the delivery agent's policy_engine.
    Here, `get_due_reminders` returns the candidate reminder state and
    `evaluate_escalation` returns raw continuity signals plus a convenience
    verdict computed from env thresholds.

All reads/writes go to PostgreSQL (MCP DB). Falls back to an in-memory store
when Postgres is unavailable (same pattern as SessionService).
"""
import logging
import os
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, update

from services.database import (
    Delivery, DeliveryScheduledSession, DeliveryReminder,
    DeliveryBlocker, DeliveryRescheduleRequest, DeliveryNotification,
    get_db, is_db_healthy,
)

logger = logging.getLogger("delivery.service")

# Escalation thresholds (env-configurable; agent policy_engine mirrors these)
_MISS_THRESHOLD = int(os.environ.get("DELIVERY_ESCALATION_MISS_THRESHOLD", "2"))
_UNVERIFIED_THRESHOLD = int(os.environ.get("DELIVERY_ESCALATION_UNVERIFIED_THRESHOLD", "2"))

# Only used by notify_linked_stakeholder — the one place this service calls
# OUT to the orchestrator instead of the other way around. Fails safely (logs
# + records status="failed") if unset or unreachable; never raises.
_ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL", "http://serve-orchestrator:8001")

_ACTIVE_STATUSES = ("activating", "active", "on_track", "at_risk", "interrupted", "resumed", "nearing_completion")
_TERMINAL_OUTCOMES = {"completed", "missed", "cancelled"}
_SESSION_TERMINAL_STATES = {"completed", "partially_completed", "missed", "cancelled"}

_READINESS_DIMENSIONS = ("volunteer", "coordinator", "session", "classroom",
                         "material", "meeting_link", "infrastructure")

_BLOCKER_KEYWORDS = {
    "technical":        ["technical", "app not working", "crash", "error", "device", "laptop", "phone issue"],
    "meeting_link":     ["link", "zoom", "meet", "join", "url", "can't join", "cant join"],
    "institution_unavailable": ["school closed", "institution", "holiday", "no school", "closed today"],
    "learner_attendance": ["students didn't come", "no students", "kids absent", "learner", "attendance"],
    "personal_conflict": ["personal", "emergency", "family", "sick", "unwell", "health"],
    "material":         ["material", "book", "content", "curriculum", "lesson plan"],
    "communication":    ["couldn't reach", "no response", "communication", "contact"],
}

_SUPPORT_GUIDANCE = {
    "technical": "Ask the volunteer to restart the app/device and confirm their internet connection. If it persists, log a technical blocker for the ops team.",
    "meeting_link": "Confirm the correct meeting link was shared and is still valid. Offer to resend it via the session resources tool.",
    "institution_unavailable": "Confirm with the coordinator whether the institution is open. If closed, capture a reschedule request.",
    "learner_attendance": "This is a school-side attendance issue, not something the volunteer can resolve alone. Log it and notify the coordinator.",
    "personal_conflict": "Be understanding — offer to capture a reschedule request and, if needed, a short pause.",
    "material": "Point the volunteer to the programme's shared material via session resources. Escalate to ops if materials are missing.",
    "communication": "Try reaching the linked stakeholder via their preferred channel; log an ops support request if unreachable.",
    "other": "Log the blocker with as much detail as possible so the ops team can triage it.",
}


# ─── In-memory fallback ───────────────────────────────────────────────────────

class _MemStore:
    def __init__(self):
        self.deliveries: Dict[str, Dict] = {}
        self.sessions: Dict[str, Dict] = {}
        self.reminders: Dict[str, Dict] = {}
        self.blockers: Dict[str, Dict] = {}
        self.reschedules: Dict[str, Dict] = {}
        self.notifications: Dict[str, Dict] = {}

_mem = _MemStore()


class DeliveryService:

    # ── Activation ────────────────────────────────────────────────────────────

    async def start_activation(self, **kw) -> Dict[str, Any]:
        """Create a delivery record. Guards against a duplicate active delivery
        for the same volunteer+need."""
        volunteer_id = kw.get("volunteer_id")
        need_id = kw.get("need_id")

        existing = await self._find_active_delivery(volunteer_id, need_id)
        if existing:
            logger.info(f"start_activation: reusing active delivery {existing['id']} "
                        f"(volunteer={volunteer_id}, need={need_id})")
            # Re-link to the NEW conversation session if one was provided and
            # differs from the delivery's current session — this is the
            # "returning volunteer resuming an interrupted journey" case: the
            # same volunteer/need reconnects via a fresh session while their
            # delivery is still active. Without this, the new session can never
            # find its delivery context, and reminders would keep landing in
            # the old (possibly abandoned) conversation.
            new_session_id = kw.get("session_id")
            if new_session_id and existing.get("session_id") != new_session_id:
                await self._relink_delivery_session(existing["id"], new_session_id)
                existing["session_id"] = new_session_id
                logger.info(f"start_activation: re-linked delivery {existing['id']} "
                            f"to session {new_session_id}")
            return {"status": "success", "delivery": existing, "reused": True}

        delivery_id = str(uuid4())
        now = datetime.utcnow()
        record = {
            "id": delivery_id,
            "session_id": kw.get("session_id"),
            "volunteer_id": volunteer_id,
            "volunteer_name": kw.get("volunteer_name"),
            "need_id": need_id,
            "nomination_id": kw.get("nomination_id"),
            "entity_id": kw.get("entity_id"),
            "coordinator_id": kw.get("coordinator_id"),
            "coordinator_phone": kw.get("coordinator_phone"),
            "programme": kw.get("programme"),
            "start_date": kw.get("start_date"),
            "end_date": kw.get("end_date"),
            "expected_sessions": kw.get("expected_sessions", 0) or 0,
            "completed_sessions": 0,
            "volunteer_acknowledged": False,
            "coordinator_acknowledged": False,
            "first_session_ready": False,
            "activation_completed_at": None,
            "readiness_checklist": None,
            "last_summary": None,
            "risk_level": None,
            "delivery_status": "activating",
            "status_reason": None,
        }

        if is_db_healthy():
            try:
                async with get_db() as db:
                    db.add(Delivery(
                        id=UUID(delivery_id),
                        session_id=UUID(record["session_id"]) if record["session_id"] else None,
                        volunteer_id=volunteer_id,
                        volunteer_name=record["volunteer_name"],
                        need_id=need_id,
                        nomination_id=record["nomination_id"],
                        entity_id=record["entity_id"],
                        coordinator_id=record["coordinator_id"],
                        coordinator_phone=record["coordinator_phone"],
                        programme=record["programme"],
                        start_date=record["start_date"],
                        end_date=record["end_date"],
                        expected_sessions=record["expected_sessions"],
                        completed_sessions=0,
                        delivery_status="activating",
                        created_at=now, updated_at=now,
                    ))
                logger.info(f"Delivery created in DB: {delivery_id} (volunteer={volunteer_id}, need={need_id})")
                return {"status": "success", "delivery": record, "reused": False}
            except Exception as e:
                logger.warning(f"DB start_activation failed, using memory: {e}")

        _mem.deliveries[delivery_id] = record
        return {"status": "success", "delivery": record, "reused": False, "storage": "memory"}

    async def confirm_acknowledgement(self, delivery_id: str, party: str) -> Dict[str, Any]:
        field = "volunteer_acknowledged" if party == "volunteer" else "coordinator_acknowledged"
        ok = await self._patch_delivery(delivery_id, {field: True})
        if not ok:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        logger.info(f"Delivery {delivery_id}: {party} acknowledged")
        return {"status": "success", "delivery_id": delivery_id, "party": party}

    async def set_coordinator_phone(self, delivery_id: str, phone: str) -> Dict[str, Any]:
        """Self-healing capture: there is no reliable coordinator_id -> phone
        directory anywhere in this stack (Serve Registry has no GET-by-id for
        coordinators). The first time a coordinator messages in on their own,
        the delivery agent captures their number here so future
        notify_linked_stakeholder calls have a real contact to reach."""
        ok = await self._patch_delivery(delivery_id, {"coordinator_phone": phone})
        if not ok:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        return {"status": "success", "delivery_id": delivery_id}

    async def confirm_first_session_readiness(self, delivery_id: str) -> Dict[str, Any]:
        ok = await self._patch_delivery(delivery_id, {"first_session_ready": True})
        if not ok:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        logger.info(f"Delivery {delivery_id}: first-session readiness confirmed")
        return {"status": "success", "delivery_id": delivery_id}

    async def complete_activation(self, delivery_id: str) -> Dict[str, Any]:
        """Mark activation complete — GATED: refuses unless the volunteer has
        acknowledged AND first-session readiness is confirmed."""
        delivery = await self._get_delivery(delivery_id)
        if not delivery:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}

        missing = []
        if not delivery.get("volunteer_acknowledged"):
            missing.append("volunteer_acknowledged")
        if not delivery.get("first_session_ready"):
            missing.append("first_session_ready")
        if missing:
            logger.info(f"Delivery {delivery_id}: complete_activation blocked, missing {missing}")
            return {"status": "blocked", "missing": missing,
                    "message": "Activation requires volunteer acknowledgement and first-session readiness."}

        await self._patch_delivery(delivery_id, {
            "activation_completed_at": datetime.utcnow(),
            "delivery_status": "active",
        })
        logger.info(f"Delivery {delivery_id}: activation COMPLETED → active")
        return {"status": "success", "delivery_id": delivery_id, "delivery_status": "active"}

    # ── Context ───────────────────────────────────────────────────────────────

    async def get_delivery_context(
        self, delivery_id: Optional[str] = None, session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """One-call context: assignment + activation + sessions + reminder/blocker
        history. Mirrors the spec's delivery.resume_context."""
        delivery = None
        if delivery_id:
            delivery = await self._get_delivery(delivery_id)
        elif session_id:
            delivery = await self._find_delivery_by_session(session_id)

        if not delivery:
            return {"status": "not_found",
                    "message": "No delivery found for the given identifier."}

        did = delivery["id"]
        sessions = await self._sessions_for(did)
        blockers = await self._blockers_for(did)
        reschedules = await self._reschedules_for(did)
        return {
            "status": "success",
            "delivery": delivery,
            "scheduled_sessions": sessions,
            "blockers": blockers,
            "reschedule_requests": reschedules,
        }

    # ── Scheduled sessions ────────────────────────────────────────────────────

    async def create_scheduled_session(self, **kw) -> Dict[str, Any]:
        delivery_id = kw["delivery_id"]
        if not await self._get_delivery(delivery_id):
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}

        sid = str(uuid4())
        now = datetime.utcnow()
        record = {
            "id": sid,
            "delivery_id": delivery_id,
            "session_number": kw.get("session_number"),
            "scheduled_date": kw.get("scheduled_date"),
            "start_time": kw.get("start_time"),
            "end_time": kw.get("end_time"),
            "subject": kw.get("subject"),
            "meeting_link": kw.get("meeting_link"),
            "delivery_mode": kw.get("delivery_mode", "online"),
            "session_state": "upcoming",
            "outcome": None,
            "outcome_reason": None,
            "outcome_reported_by": None,
        }
        if is_db_healthy():
            try:
                async with get_db() as db:
                    db.add(DeliveryScheduledSession(
                        id=UUID(sid),
                        delivery_id=UUID(delivery_id),
                        session_number=record["session_number"],
                        scheduled_date=record["scheduled_date"],
                        start_time=record["start_time"],
                        end_time=record["end_time"],
                        subject=record["subject"],
                        meeting_link=record["meeting_link"],
                        delivery_mode=record["delivery_mode"],
                        session_state="upcoming",
                        created_at=now, updated_at=now,
                    ))
                logger.info(f"Scheduled session created: {sid} for delivery {delivery_id} on {record['scheduled_date']}")
                return {"status": "success", "session": record}
            except Exception as e:
                logger.warning(f"DB create_scheduled_session failed, using memory: {e}")

        _mem.sessions[sid] = record
        return {"status": "success", "session": record, "storage": "memory"}

    async def get_scheduled_sessions(self, delivery_id: str, today_only: bool = False) -> Dict[str, Any]:
        sessions = await self._sessions_for(delivery_id)
        if today_only:
            today = date.today().isoformat()
            sessions = [s for s in sessions if s.get("scheduled_date") == today]
        return {"status": "success", "sessions": sessions}

    # ── Reminders ─────────────────────────────────────────────────────────────

    async def get_due_reminders(
        self, delivery_id: Optional[str] = None, now: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return candidate reminder state for policy evaluation by the agent.

        For every active (non-terminal) delivery's non-terminal, non-cancelled
        session, return the session detail plus which reminder types have already
        been recorded. The agent's policy_engine decides which are actually due.
        """
        deliveries = await self._active_deliveries(delivery_id)
        candidates: List[Dict[str, Any]] = []
        for d in deliveries:
            for s in await self._sessions_for(d["id"]):
                if s.get("session_state") == "cancelled" or s.get("outcome") in _TERMINAL_OUTCOMES:
                    continue
                sent = await self._reminder_types_for(s["id"])
                candidates.append({
                    "delivery_id": d["id"],
                    "delivery_status": d["delivery_status"],
                    "delivery_session_id": d.get("session_id"),
                    "volunteer_name": d.get("volunteer_name"),
                    "session": s,
                    "sent_reminder_types": sent,
                })
        return {"status": "success", "now": now or datetime.utcnow().isoformat(),
                "candidates": candidates}

    async def mark_reminder(
        self, scheduled_session_id: str, reminder_type: str,
        status: str = "sent", suppressed_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a reminder. Idempotent: the (session, type) unique constraint
        means a duplicate is a no-op success, never a second send."""
        session = await self._get_session(scheduled_session_id)
        if not session:
            return {"status": "error", "error": f"Scheduled session {scheduled_session_id} not found"}

        rid = str(uuid4())
        now = datetime.utcnow()
        if is_db_healthy():
            try:
                async with get_db() as db:
                    # Uniqueness guard — avoid IntegrityError on duplicate
                    existing = await db.execute(
                        select(DeliveryReminder).where(
                            DeliveryReminder.scheduled_session_id == UUID(scheduled_session_id),
                            DeliveryReminder.reminder_type == reminder_type,
                        )
                    )
                    if existing.scalar_one_or_none():
                        logger.info(f"Reminder already recorded: session={scheduled_session_id} type={reminder_type} (no-op)")
                        return {"status": "success", "duplicate": True}
                    db.add(DeliveryReminder(
                        id=UUID(rid),
                        delivery_id=UUID(session["delivery_id"]),
                        scheduled_session_id=UUID(scheduled_session_id),
                        reminder_type=reminder_type,
                        status=status,
                        suppressed_reason=suppressed_reason,
                        sent_at=now,
                    ))
                # advance session_state to reflect the reminder
                await self._advance_session_state_for_reminder(scheduled_session_id, reminder_type)
                logger.info(f"Reminder recorded: session={scheduled_session_id} type={reminder_type} status={status}")
                return {"status": "success", "duplicate": False}
            except Exception as e:
                logger.warning(f"DB mark_reminder failed, using memory: {e}")

        key = f"{scheduled_session_id}:{reminder_type}"
        if key in _mem.reminders:
            return {"status": "success", "duplicate": True}
        _mem.reminders[key] = {"id": rid, "scheduled_session_id": scheduled_session_id,
                               "reminder_type": reminder_type, "status": status,
                               "suppressed_reason": suppressed_reason, "sent_at": now.isoformat()}
        await self._advance_session_state_for_reminder(scheduled_session_id, reminder_type)
        return {"status": "success", "duplicate": False, "storage": "memory"}

    # ── Outcomes ──────────────────────────────────────────────────────────────

    async def record_session_outcome(
        self, scheduled_session_id: str, outcome: str,
        reason: Optional[str] = None, reported_by: str = "volunteer",
        attendance_count: Optional[int] = None, duration_minutes: Optional[int] = None,
        disruption_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        session = await self._get_session(scheduled_session_id)
        if not session:
            return {"status": "error", "error": f"Scheduled session {scheduled_session_id} not found"}
        if session.get("outcome") in _TERMINAL_OUTCOMES:
            return {"status": "error", "error": "already_recorded",
                    "existing_outcome": session["outcome"]}

        patch = {"outcome": outcome, "outcome_reason": reason,
                 "outcome_reported_by": reported_by, "session_state": outcome}
        if attendance_count is not None:
            patch["attendance_count"] = attendance_count
        if duration_minutes is not None:
            patch["duration_minutes"] = duration_minutes
        if disruption_type is not None:
            patch["disruption_type"] = disruption_type
        await self._patch_session(scheduled_session_id, patch)

        # Count a delivery session as completed when fully or partially completed
        if outcome in ("completed", "partially_completed"):
            await self._increment_completed(session["delivery_id"])
        logger.info(f"Session {scheduled_session_id}: outcome={outcome} reported_by={reported_by}")
        return {"status": "success", "scheduled_session_id": scheduled_session_id, "outcome": outcome}

    # ── Blockers ──────────────────────────────────────────────────────────────

    async def log_blocker(self, **kw) -> Dict[str, Any]:
        delivery_id = kw["delivery_id"]
        if not await self._get_delivery(delivery_id):
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        bid = str(uuid4())
        now = datetime.utcnow()
        record = {
            "id": bid, "delivery_id": delivery_id,
            "scheduled_session_id": kw.get("scheduled_session_id"),
            "blocker_type": kw["blocker_type"], "description": kw.get("description"),
            "status": "open", "raised_by": kw.get("raised_by", "volunteer"),
        }
        if is_db_healthy():
            try:
                async with get_db() as db:
                    db.add(DeliveryBlocker(
                        id=UUID(bid), delivery_id=UUID(delivery_id),
                        scheduled_session_id=UUID(record["scheduled_session_id"]) if record["scheduled_session_id"] else None,
                        blocker_type=record["blocker_type"], description=record["description"],
                        status="open", raised_by=record["raised_by"],
                        created_at=now, updated_at=now,
                    ))
                logger.info(f"Blocker logged: {bid} type={record['blocker_type']} delivery={delivery_id}")
                return {"status": "success", "blocker": record}
            except Exception as e:
                logger.warning(f"DB log_blocker failed, using memory: {e}")
        _mem.blockers[bid] = record
        return {"status": "success", "blocker": record, "storage": "memory"}

    # ── Reschedule ────────────────────────────────────────────────────────────

    async def capture_reschedule_request(self, **kw) -> Dict[str, Any]:
        """Capture a reschedule request — always pending, never auto-approved."""
        delivery_id = kw["delivery_id"]
        if not await self._get_delivery(delivery_id):
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        rid = str(uuid4())
        now = datetime.utcnow()
        record = {
            "id": rid, "delivery_id": delivery_id,
            "scheduled_session_id": kw.get("scheduled_session_id"),
            "reason": kw.get("reason"), "preferred_date": kw.get("preferred_date"),
            "preferred_time": kw.get("preferred_time"),
            "requested_by": kw.get("requested_by", "volunteer"), "status": "pending",
        }
        if kw.get("scheduled_session_id"):
            await self._patch_session(kw["scheduled_session_id"],
                                      {"session_state": "reschedule_requested"})
        if is_db_healthy():
            try:
                async with get_db() as db:
                    db.add(DeliveryRescheduleRequest(
                        id=UUID(rid), delivery_id=UUID(delivery_id),
                        scheduled_session_id=UUID(record["scheduled_session_id"]) if record["scheduled_session_id"] else None,
                        reason=record["reason"], preferred_date=record["preferred_date"],
                        preferred_time=record["preferred_time"], requested_by=record["requested_by"],
                        status="pending", created_at=now, updated_at=now,
                    ))
                logger.info(f"Reschedule request captured (pending): {rid} delivery={delivery_id}")
                return {"status": "success", "reschedule_request": record}
            except Exception as e:
                logger.warning(f"DB capture_reschedule failed, using memory: {e}")
        _mem.reschedules[rid] = record
        return {"status": "success", "reschedule_request": record, "storage": "memory"}

    # ── Status & escalation ───────────────────────────────────────────────────

    async def update_delivery_status(
        self, delivery_id: str, delivery_status: str, status_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        ok = await self._patch_delivery(delivery_id,
                                        {"delivery_status": delivery_status, "status_reason": status_reason})
        if not ok:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        logger.info(f"Delivery {delivery_id}: status → {delivery_status} ({status_reason})")
        return {"status": "success", "delivery_id": delivery_id, "delivery_status": delivery_status}

    async def evaluate_escalation(self, delivery_id: str) -> Dict[str, Any]:
        """Deterministic continuity signals + convenience verdict from env
        thresholds. The agent's policy_engine may re-decide."""
        sessions = await self._sessions_for(delivery_id)
        # order by session_number then date for consecutiveness
        sessions.sort(key=lambda s: (s.get("session_number") or 0, s.get("scheduled_date") or ""))

        consecutive_missed = 0
        consecutive_unverified = 0
        for s in reversed(sessions):
            o = s.get("outcome")
            if o is None:
                continue
            if o == "missed":
                consecutive_missed += 1
            else:
                break
        for s in reversed(sessions):
            o = s.get("outcome")
            if o is None:
                continue
            if o == "unverified":
                consecutive_unverified += 1
            else:
                break

        blockers = await self._blockers_for(delivery_id)
        open_blockers = [b for b in blockers if b.get("status") == "open"]
        reschedules = await self._reschedules_for(delivery_id)

        reasons = []
        if consecutive_missed >= _MISS_THRESHOLD:
            reasons.append(f"{consecutive_missed} consecutive missed sessions")
        if consecutive_unverified >= _UNVERIFIED_THRESHOLD:
            reasons.append(f"{consecutive_unverified} consecutive unverified sessions")

        verdict = {
            "escalate": bool(reasons),
            "reasons": reasons,
            "signals": {
                "consecutive_missed": consecutive_missed,
                "consecutive_unverified": consecutive_unverified,
                "open_blocker_count": len(open_blockers),
                "reschedule_count": len(reschedules),
            },
        }
        logger.info(f"Delivery {delivery_id}: escalation eval → {verdict['escalate']} ({reasons})")
        return {"status": "success", **verdict}

    # ── Granular reads ────────────────────────────────────────────────────────

    async def read_assignment_context(self, delivery_id: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        return {"status": "success", "assignment": {
            "volunteer_id": d.get("volunteer_id"), "volunteer_name": d.get("volunteer_name"),
            "need_id": d.get("need_id"), "nomination_id": d.get("nomination_id"),
            "entity_id": d.get("entity_id"), "coordinator_id": d.get("coordinator_id"),
            "programme": d.get("programme"), "start_date": d.get("start_date"),
            "end_date": d.get("end_date"), "expected_sessions": d.get("expected_sessions"),
        }}

    async def read_activation_context(self, delivery_id: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        return {"status": "success", "activation": {
            "volunteer_acknowledged": d.get("volunteer_acknowledged"),
            "coordinator_acknowledged": d.get("coordinator_acknowledged"),
            "first_session_ready": d.get("first_session_ready"),
            "activation_completed_at": d.get("activation_completed_at"),
            "readiness_checklist": d.get("readiness_checklist"),
        }}

    async def read_schedule_context(self, delivery_id: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        sessions = await self._sessions_for(delivery_id)
        today = date.today().isoformat()
        upcoming = [s for s in sessions if s.get("outcome") is None and (s.get("scheduled_date") or "") >= today]
        todays = [s for s in sessions if s.get("scheduled_date") == today]
        missed = [s for s in sessions if s.get("outcome") == "missed"]
        return {"status": "success", "upcoming_sessions": upcoming, "today_sessions": todays,
                "missed_sessions": missed, "all_sessions": sessions}

    async def read_session_context(self, scheduled_session_id: str) -> Dict[str, Any]:
        session = await self._get_session(scheduled_session_id)
        if not session:
            return {"status": "error", "error": f"Scheduled session {scheduled_session_id} not found"}
        reminders_sent = await self._reminder_types_for(scheduled_session_id)
        return {"status": "success", "session": session, "reminders_sent": reminders_sent}

    async def read_delivery_history(self, delivery_id: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        sessions = await self._sessions_for(delivery_id)
        sessions.sort(key=lambda s: (s.get("session_number") or 0, s.get("scheduled_date") or ""))
        outcomes = [{"scheduled_date": s.get("scheduled_date"), "outcome": s.get("outcome")}
                    for s in sessions if s.get("outcome")]
        blockers = await self._blockers_for(delivery_id)
        reschedules = await self._reschedules_for(delivery_id)
        cancelled = [s for s in sessions if s.get("session_state") == "cancelled"]
        return {"status": "success", "outcome_history": outcomes, "blockers": blockers,
                "reschedule_requests": reschedules, "cancelled_sessions": cancelled}

    # ── Signal processing & evaluation ──────────────────────────────────────────

    def extract_delivery_signals(self, text: str) -> Dict[str, Any]:
        """Deterministic, keyword-based structured guess at what a free-form
        message signals. Advisory only — the LLM's own tool calls (e.g.
        record_session_outcome) remain the authoritative extraction path; this
        is additional named surface matching the spec's tool list."""
        low = (text or "").lower()
        signals: Dict[str, Any] = {}
        if any(w in low for w in ("happened", "done", "completed", "finished", "went well")):
            signals["completion_signal"] = "completed"
        elif any(w in low for w in ("didn't happen", "did not happen", "missed", "couldn't", "cant", "wasn't able")):
            signals["completion_signal"] = "missed"
        elif any(w in low for w in ("partial", "half", "cut short")):
            signals["completion_signal"] = "partially_completed"
        if any(w in low for w in ("reschedule", "postpone", "different time", "move the", "move my")):
            signals["reschedule_signal"] = True
        if any(w in low for w in ("problem", "issue", "broken", "not working", "trouble")):
            signals["blocker_signal"] = True
        if any(w in low for w in ("ready", "all set", "good to go", "prepared")):
            signals["readiness_signal"] = True
        if any(w in low for w in ("busy", "can't make it", "unavailable", "not free")):
            signals["availability"] = False
        if any(w in low for w in ("quit", "stop teaching", "leaving", "can't continue", "won't be able to continue")):
            signals["disengagement_signal"] = True
        if any(w in low for w in ("help", "support", "assist", "guidance")):
            signals["support_request_signal"] = True
        return {"status": "success", "signals": signals}

    def detect_blockers(self, text: str) -> Dict[str, Any]:
        """Deterministic keyword classifier — advisory pre-check, not a
        replacement for the LLM's own log_blocker call."""
        low = (text or "").lower()
        for blocker_type, keywords in _BLOCKER_KEYWORDS.items():
            if any(kw in low for kw in keywords):
                return {"status": "success", "detected": True, "blocker_type": blocker_type, "confidence": "low"}
        return {"status": "success", "detected": False, "blocker_type": None, "confidence": "low"}

    async def get_missing_signals(self, delivery_id: str, target: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        missing: List[str] = []
        if target == "activation_complete":
            if not d.get("volunteer_acknowledged"):
                missing.append("volunteer_acknowledged")
            if not d.get("first_session_ready"):
                missing.append("first_session_ready")
        elif target == "readiness_confirmed":
            checklist = d.get("readiness_checklist") or {}
            missing = [dim for dim in _READINESS_DIMENSIONS if not checklist.get(dim)]
        elif target in ("session_completed", "session_missed", "partial_completion"):
            missing = [] if d.get("activation_completed_at") else ["activation_completed_at"]
        elif target == "reschedule":
            missing = []  # only needs a reason, always collectible in-conversation
        elif target == "delivery_completed":
            expected = d.get("expected_sessions") or 0
            completed = d.get("completed_sessions") or 0
            if completed < expected:
                missing.append(f"{expected - completed}_more_sessions")
        elif target == "escalation":
            missing = []  # escalation criteria are evaluated, not "collected"
        return {"status": "success", "target": target, "missing": missing, "satisfied": not missing}

    async def evaluate_activation(self, delivery_id: str) -> Dict[str, Any]:
        """Dry-run of complete_activation's gate — does not commit anything."""
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        missing = []
        if not d.get("volunteer_acknowledged"):
            missing.append("volunteer_acknowledged")
        if not d.get("first_session_ready"):
            missing.append("first_session_ready")
        return {"status": "success", "ready": not missing, "missing": missing}

    async def evaluate_readiness(self, delivery_id: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        checklist = d.get("readiness_checklist") or {}
        missing = [dim for dim in _READINESS_DIMENSIONS if not checklist.get(dim)]
        return {"status": "success", "ready": not missing, "checklist": checklist, "missing": missing}

    async def set_readiness_dimension(self, delivery_id: str, dimension: str, value: bool) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        checklist = dict(d.get("readiness_checklist") or {})
        checklist[dimension] = value
        await self._patch_delivery(delivery_id, {"readiness_checklist": checklist})
        logger.info(f"Delivery {delivery_id}: readiness.{dimension} = {value}")
        return {"status": "success", "checklist": checklist}

    async def evaluate_delivery_health(self, delivery_id: str) -> Dict[str, Any]:
        """Richer than evaluate_escalation — adds blocker-age and reschedule-
        pattern signals on top of the same consecutive-miss/unverified counts."""
        base = await self.evaluate_escalation(delivery_id)
        if base.get("status") != "success":
            return base
        blockers = await self._blockers_for(delivery_id)
        open_blockers = [b for b in blockers if b.get("status") == "open"]
        stale_blockers = 0
        now = datetime.utcnow()
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryBlocker).where(
                            DeliveryBlocker.delivery_id == UUID(delivery_id),
                            DeliveryBlocker.status == "open",
                        )
                    )
                    for row in result.scalars().all():
                        if (now - row.created_at).days >= 3:
                            stale_blockers += 1
            except Exception as e:
                logger.warning(f"DB evaluate_delivery_health stale-blocker check failed: {e}")
        reschedules = await self._reschedules_for(delivery_id)
        reasons = list(base.get("reasons", []))
        if stale_blockers:
            reasons.append(f"{stale_blockers} blocker(s) open 3+ days")
        if len(reschedules) >= 2:
            reasons.append(f"{len(reschedules)} reschedule requests — recurring scheduling pattern")
        return {
            "status": "success",
            "escalate": base.get("escalate") or bool(stale_blockers) or len(reschedules) >= 2,
            "reasons": reasons,
            "signals": {**base.get("signals", {}), "open_blocker_count": len(open_blockers),
                       "stale_blocker_count": stale_blockers, "reschedule_count": len(reschedules)},
        }

    async def evaluate_next_action(self, delivery_id: str) -> Dict[str, Any]:
        """Read-only advisory: what the deterministic flow would do next. Never
        grants the caller authority to act — the agent's own _finalize /
        _compute_stage remain the sole enforcement point."""
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        if d.get("activation_completed_at"):
            return {"status": "success", "mode": "operations",
                    "recommended_next": "delivery_operations",
                    "reason": "activation already complete"}
        if d.get("first_session_ready"):
            return {"status": "success", "mode": "activation",
                    "recommended_next": "activation_completed",
                    "reason": "both acknowledgement and readiness confirmed"}
        if d.get("volunteer_acknowledged"):
            return {"status": "success", "mode": "activation",
                    "recommended_next": "first_session_ready",
                    "reason": "awaiting first-session readiness confirmation"}
        return {"status": "success", "mode": "activation",
                "recommended_next": "volunteer_acknowledged",
                "reason": "awaiting volunteer acknowledgement"}

    # ── Activation content (deterministic, never LLM-authored) ─────────────────

    async def get_activation_content(self, delivery_id: str, content_type: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        name = (d.get("volunteer_name") or "there").split()[0]
        programme = d.get("programme") or "eVidyaloka teaching"
        entity = d.get("entity_id") or "your assigned school"
        if content_type == "intro":
            content = (f"Welcome {name}! You've been assigned to {programme} at {entity}. "
                       f"We're excited to have you on board.")
        elif content_type == "instructions":
            content = ("As a volunteer you're expected to: join every scheduled session on time, "
                       "let us know as early as possible if you can't make it, and reach out any "
                       "time you hit a problem — we're here to help.")
        elif content_type == "resources":
            content = ("Your session details, meeting link, and any shared material will be sent "
                       "to you before each class. Reply any time to ask about a specific session.")
        else:
            content = ""
        return {"status": "success", "content_type": content_type, "content": content}

    # ── Coordinator notification ────────────────────────────────────────────────

    async def notify_linked_stakeholder(self, delivery_id: str, stakeholder: str, reason: str) -> Dict[str, Any]:
        """Records the notification intent and attempts a real WhatsApp send via
        the orchestrator's internal endpoint. Message content is a fixed template
        built from `reason` — never LLM-authored — since this reaches someone who
        isn't in the current conversation and can't correct a wrong message.
        Honest about failure: if there is no phone on file or the send fails,
        status reflects that rather than silently pretending it worked."""
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        if stakeholder != "coordinator":
            return {"status": "error", "error": f"Unsupported stakeholder type: {stakeholder}"}

        phone = d.get("coordinator_phone") or await self._lookup_coordinator_phone(d.get("coordinator_id"))
        nid = str(uuid4())
        now = datetime.utcnow()
        volunteer = d.get("volunteer_name") or "your volunteer"
        template = (f"Hi, this is an update from eVidyaloka about {volunteer}'s teaching delivery. "
                    f"{reason} Please reach out to the volunteer or our team if you have questions.")

        status = "no_contact_on_file"
        sent_at = None
        if phone:
            sent = await self._send_whatsapp(phone, template)
            status = "sent" if sent else "failed"
            sent_at = now if sent else None

        record = {"id": nid, "delivery_id": delivery_id, "stakeholder_type": stakeholder,
                  "reason": reason, "channel": "whatsapp", "status": status,
                  "sent_at": sent_at.isoformat() if sent_at else None}
        if is_db_healthy():
            try:
                async with get_db() as db:
                    db.add(DeliveryNotification(
                        id=UUID(nid), delivery_id=UUID(delivery_id), stakeholder_type=stakeholder,
                        reason=reason, channel="whatsapp", status=status, sent_at=sent_at,
                        created_at=now,
                    ))
                logger.info(f"Delivery {delivery_id}: coordinator notification → {status}")
                return {"status": "success", "notification": record}
            except Exception as e:
                logger.warning(f"DB notify_linked_stakeholder failed, using memory: {e}")
        _mem.notifications[nid] = record
        return {"status": "success", "notification": record, "storage": "memory"}

    async def _lookup_coordinator_phone(self, coordinator_id: Optional[str]) -> Optional[str]:
        """Best-effort only — Serve Registry has no GET-coordinator-by-id
        endpoint today (see coordinator_service.get_coordinator), so this
        almost always returns None unless/until that's implemented upstream.
        The reliable path is set_coordinator_phone, captured the first time a
        coordinator messages in on their own."""
        if not coordinator_id:
            return None
        try:
            from services.coordinator_service import coordinator_service as _coord_svc
            record = await _coord_svc.get_coordinator(coordinator_id)
            return (record or {}).get("phone")
        except Exception as e:
            logger.warning(f"Coordinator phone lookup failed for {coordinator_id}: {e}")
            return None

    async def _send_whatsapp(self, phone: str, message: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(f"{_ORCHESTRATOR_URL}/api/internal/notify",
                                      json={"phone": phone, "message": message})
                r.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"WhatsApp send via orchestrator failed: {e}")
            return False

    # ── Reminder wrappers, history, manual suppression ──────────────────────────

    async def send_session_day_reminder(self, scheduled_session_id: str, now: Optional[str] = None) -> Dict[str, Any]:
        return await self._send_named_reminder(scheduled_session_id, "session_day")

    async def send_pre_session_reminder(self, scheduled_session_id: str, now: Optional[str] = None) -> Dict[str, Any]:
        return await self._send_named_reminder(scheduled_session_id, "pre_session")

    async def send_completion_check(self, scheduled_session_id: str, now: Optional[str] = None) -> Dict[str, Any]:
        return await self._send_named_reminder(scheduled_session_id, "completion_check")

    async def send_followup_nudge(self, scheduled_session_id: str, now: Optional[str] = None) -> Dict[str, Any]:
        return await self._send_named_reminder(scheduled_session_id, "followup_nudge")

    async def _send_named_reminder(self, scheduled_session_id: str, reminder_type: str) -> Dict[str, Any]:
        """Named single-type wrapper around mark_reminder — due-date policy math
        stays entirely in policy_engine.due_reminders; this just lets a caller
        (or future ops tooling) fire one specific type by name, matching the
        spec's 4 named tools without duplicating the underlying scheduling logic."""
        session = await self._get_session(scheduled_session_id)
        if not session:
            return {"status": "error", "error": f"Scheduled session {scheduled_session_id} not found"}
        return await self.mark_reminder(scheduled_session_id, reminder_type, status="sent")

    async def read_reminder_history(self, delivery_id: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        history: List[Dict[str, Any]] = []
        sessions = await self._sessions_for(delivery_id)
        if is_db_healthy():
            try:
                async with get_db() as db:
                    for s in sessions:
                        result = await db.execute(
                            select(DeliveryReminder).where(DeliveryReminder.scheduled_session_id == UUID(s["id"]))
                        )
                        for r in result.scalars().all():
                            history.append({
                                "scheduled_session_id": s["id"], "reminder_type": r.reminder_type,
                                "status": r.status, "suppressed_reason": r.suppressed_reason,
                                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                            })
                return {"status": "success", "reminders": history}
            except Exception as e:
                logger.warning(f"DB read_reminder_history failed: {e}")
        for s in sessions:
            for key, v in _mem.reminders.items():
                if v.get("scheduled_session_id") == s["id"]:
                    history.append(v)
        return {"status": "success", "reminders": history, "storage": "memory"}

    async def suppress_reminder(self, scheduled_session_id: str, reminder_type: str, reason: str) -> Dict[str, Any]:
        """Explicit ops override — distinct from the automatic policy-driven
        suppression in policy_engine.due_reminders. Records a 'suppressed'
        status row via the same idempotent mark_reminder path, so this type
        will never fire for this session even if policy would otherwise allow it."""
        return await self.mark_reminder(scheduled_session_id, reminder_type,
                                        status="suppressed", suppressed_reason=reason)

    # ── Session check-in ─────────────────────────────────────────────────────────

    async def start_session_checkin(self, scheduled_session_id: str) -> Dict[str, Any]:
        ok = await self._patch_session(scheduled_session_id, {"session_state": "session_window_active"})
        if not ok:
            return {"status": "error", "error": f"Scheduled session {scheduled_session_id} not found"}
        return {"status": "success", "scheduled_session_id": scheduled_session_id}

    async def close_checkin(self, scheduled_session_id: str) -> Dict[str, Any]:
        """Closes the operational check-in without closing the whole delivery —
        only touches this one session's state."""
        session = await self._get_session(scheduled_session_id)
        if not session:
            return {"status": "error", "error": f"Scheduled session {scheduled_session_id} not found"}
        if session.get("outcome") is None:
            await self._patch_session(scheduled_session_id, {"session_state": "checkin_closed"})
        return {"status": "success", "scheduled_session_id": scheduled_session_id}

    # ── Blocker resolution & support ────────────────────────────────────────────

    async def update_blocker(self, blocker_id: str, status: str,
                             owner: Optional[str] = None, resolution_notes: Optional[str] = None) -> Dict[str, Any]:
        blocker = await self._get_blocker(blocker_id)
        if not blocker:
            return {"status": "error", "error": f"Blocker {blocker_id} not found"}
        patch: Dict[str, Any] = {"status": status}
        if owner is not None:
            patch["owner"] = owner
        if resolution_notes is not None:
            patch["resolution_notes"] = resolution_notes
        if status in ("resolved", "escalated"):
            patch["resolved_at"] = datetime.utcnow()
        await self._patch_blocker(blocker_id, patch)
        logger.info(f"Blocker {blocker_id}: status → {status}")
        return {"status": "success", "blocker_id": blocker_id, "new_status": status}

    def get_support_guidance(self, blocker_type: str) -> Dict[str, Any]:
        guidance = _SUPPORT_GUIDANCE.get(blocker_type, _SUPPORT_GUIDANCE["other"])
        return {"status": "success", "blocker_type": blocker_type, "guidance": guidance}

    async def create_ops_support_request(self, delivery_id: str, reason: str, urgency: str = "medium") -> Dict[str, Any]:
        """Lighter-weight than full escalation — reuses the same handoff
        mechanism with a distinct event_type so ops can triage separately."""
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        return {"status": "success", "delivery_id": delivery_id, "reason": reason,
                "urgency": urgency, "event_type": "support_request"}

    # ── Reschedule resolution ───────────────────────────────────────────────────

    async def submit_reschedule_request(self, reschedule_request_id: str) -> Dict[str, Any]:
        req = await self._get_reschedule(reschedule_request_id)
        if not req:
            return {"status": "error", "error": f"Reschedule request {reschedule_request_id} not found"}
        if req.get("status") != "pending":
            return {"status": "error", "error": f"Cannot submit from status '{req.get('status')}'"}
        await self._patch_reschedule(reschedule_request_id, {"status": "submitted"})
        logger.info(f"Reschedule request {reschedule_request_id}: submitted for ops review")
        return {"status": "success", "reschedule_request_id": reschedule_request_id, "new_status": "submitted"}

    async def read_reschedule_status(self, delivery_id: Optional[str] = None,
                                     reschedule_request_id: Optional[str] = None) -> Dict[str, Any]:
        if reschedule_request_id:
            req = await self._get_reschedule(reschedule_request_id)
            if not req:
                return {"status": "error", "error": f"Reschedule request {reschedule_request_id} not found"}
            return {"status": "success", "reschedule_request": req}
        requests = await self._reschedules_for(delivery_id)
        return {"status": "success", "reschedule_requests": requests}

    async def resolve_reschedule_request(self, reschedule_request_id: str, status: str,
                                         resolution_notes: Optional[str] = None) -> Dict[str, Any]:
        """Ops-only — the piece that lets a reschedule request finally reach a
        real outcome instead of sitting at 'pending' forever. Not exposed to
        the volunteer-facing LLM; exists for a future ops interface."""
        req = await self._get_reschedule(reschedule_request_id)
        if not req:
            return {"status": "error", "error": f"Reschedule request {reschedule_request_id} not found"}
        patch = {"status": status, "resolved_at": datetime.utcnow()}
        if resolution_notes is not None:
            patch["resolution_notes"] = resolution_notes
        await self._patch_reschedule(reschedule_request_id, patch)
        logger.info(f"Reschedule request {reschedule_request_id}: resolved → {status}")
        return {"status": "success", "reschedule_request_id": reschedule_request_id, "new_status": status}

    # ── Risk & handoff enrichment ───────────────────────────────────────────────

    async def raise_delivery_risk(self, delivery_id: str, risk_level: str, reason: str) -> Dict[str, Any]:
        ok = await self._patch_delivery(delivery_id, {"risk_level": risk_level, "status_reason": reason})
        if not ok:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        logger.info(f"Delivery {delivery_id}: risk_level → {risk_level} ({reason})")
        return {"status": "success", "delivery_id": delivery_id, "risk_level": risk_level}

    async def prepare_ops_handoff(self, delivery_id: str, reason: str) -> Dict[str, Any]:
        """Builds the fuller handoff bundle the spec describes — recent
        outcomes, open blockers, reminder summary, attempted resolutions —
        for use as the payload of an emit_handoff_event call."""
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        sessions = await self._sessions_for(delivery_id)
        recent_outcomes = [{"scheduled_date": s.get("scheduled_date"), "outcome": s.get("outcome")}
                           for s in sessions if s.get("outcome")][-5:]
        blockers = await self._blockers_for(delivery_id)
        open_blockers = [b for b in blockers if b.get("status") == "open"]
        reschedules = await self._reschedules_for(delivery_id)
        return {"status": "success", "handoff_bundle": {
            "delivery_id": delivery_id, "reason": reason,
            "assignment": {"volunteer_name": d.get("volunteer_name"), "programme": d.get("programme")},
            "recent_outcomes": recent_outcomes, "open_blockers": open_blockers,
            "pending_reschedules": [r for r in reschedules if r.get("status") == "pending"],
            "delivery_status": d.get("delivery_status"), "risk_level": d.get("risk_level"),
        }}

    # ── Summaries (deterministic, template-based — never LLM-generated) ────────

    async def write_session_summary(self, scheduled_session_id: str) -> Dict[str, Any]:
        session = await self._get_session(scheduled_session_id)
        if not session:
            return {"status": "error", "error": f"Scheduled session {scheduled_session_id} not found"}
        subject = session.get("subject") or "the session"
        date_str = session.get("scheduled_date") or "an unspecified date"
        outcome = session.get("outcome") or "not yet recorded"
        reason = session.get("outcome_reason")
        summary = f"{subject} on {date_str}: outcome is {outcome}."
        if reason:
            summary += f" Reason noted: {reason}."
        await self._patch_session(scheduled_session_id, {"last_summary": summary})
        return {"status": "success", "scheduled_session_id": scheduled_session_id, "summary": summary}

    async def write_delivery_summary(self, delivery_id: str) -> Dict[str, Any]:
        d = await self._get_delivery(delivery_id)
        if not d:
            return {"status": "error", "error": f"Delivery {delivery_id} not found"}
        completed = d.get("completed_sessions") or 0
        expected = d.get("expected_sessions") or 0
        blockers = await self._blockers_for(delivery_id)
        open_blockers = [b for b in blockers if b.get("status") == "open"]
        reschedules = await self._reschedules_for(delivery_id)
        pending_reschedules = [r for r in reschedules if r.get("status") == "pending"]
        parts = [
            f"{d.get('volunteer_name') or 'Volunteer'} — {d.get('programme') or 'delivery'}: "
            f"{completed} of {expected or '?'} sessions completed, status is {d.get('delivery_status')}.",
        ]
        if open_blockers:
            parts.append(f"{len(open_blockers)} open blocker(s).")
        if pending_reschedules:
            parts.append(f"{len(pending_reschedules)} pending reschedule request(s).")
        if d.get("risk_level") and d["risk_level"] != "none":
            parts.append(f"Risk level: {d['risk_level']}.")
        summary = " ".join(parts)
        await self._patch_delivery(delivery_id, {"last_summary": summary})
        return {"status": "success", "delivery_id": delivery_id, "summary": summary}

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _advance_session_state_for_reminder(self, session_id: str, reminder_type: str) -> None:
        mapping = {
            "session_day": "day_reminder_sent",
            "pre_session": "pre_session_reminder_sent",
            "completion_check": "completion_check_sent",
        }
        new_state = mapping.get(reminder_type)
        if new_state:
            # Only advance forward; don't regress a session that already has an outcome
            session = await self._get_session(session_id)
            if session and session.get("session_state") not in _SESSION_TERMINAL_STATES:
                await self._patch_session(session_id, {"session_state": new_state})

    async def _find_active_delivery(self, volunteer_id, need_id) -> Optional[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(Delivery).where(
                            Delivery.volunteer_id == volunteer_id,
                            Delivery.need_id == need_id,
                            Delivery.delivery_status.in_(_ACTIVE_STATUSES),
                        ).limit(1)
                    )
                    row = result.scalar_one_or_none()
                    return self._delivery_to_dict(row) if row else None
            except Exception as e:
                logger.warning(f"DB _find_active_delivery failed: {e}")
        for d in _mem.deliveries.values():
            if (d["volunteer_id"] == volunteer_id and d["need_id"] == need_id
                    and d["delivery_status"] in _ACTIVE_STATUSES):
                return d
        return None

    async def _active_deliveries(self, delivery_id: Optional[str]) -> List[Dict]:
        if delivery_id:
            d = await self._get_delivery(delivery_id)
            return [d] if d and d["delivery_status"] in _ACTIVE_STATUSES else []
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(Delivery).where(Delivery.delivery_status.in_(_ACTIVE_STATUSES))
                    )
                    return [self._delivery_to_dict(r) for r in result.scalars().all()]
            except Exception as e:
                logger.warning(f"DB _active_deliveries failed: {e}")
        return [d for d in _mem.deliveries.values() if d["delivery_status"] in _ACTIVE_STATUSES]

    async def _get_delivery(self, delivery_id: str) -> Optional[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(select(Delivery).where(Delivery.id == UUID(delivery_id)))
                    row = result.scalar_one_or_none()
                    return self._delivery_to_dict(row) if row else None
            except Exception as e:
                logger.warning(f"DB _get_delivery failed: {e}")
        return _mem.deliveries.get(delivery_id)

    async def _find_delivery_by_session(self, session_id: str) -> Optional[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(Delivery).where(Delivery.session_id == UUID(session_id))
                        .order_by(Delivery.created_at.desc()).limit(1)
                    )
                    row = result.scalar_one_or_none()
                    return self._delivery_to_dict(row) if row else None
            except Exception as e:
                logger.warning(f"DB _find_delivery_by_session failed: {e}")
        for d in _mem.deliveries.values():
            if d.get("session_id") == session_id:
                return d
        return None

    async def _get_session(self, session_id: str) -> Optional[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryScheduledSession).where(DeliveryScheduledSession.id == UUID(session_id))
                    )
                    row = result.scalar_one_or_none()
                    return self._session_to_dict(row) if row else None
            except Exception as e:
                logger.warning(f"DB _get_session failed: {e}")
        return _mem.sessions.get(session_id)

    async def _sessions_for(self, delivery_id: str) -> List[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryScheduledSession)
                        .where(DeliveryScheduledSession.delivery_id == UUID(delivery_id))
                        .order_by(DeliveryScheduledSession.scheduled_date)
                    )
                    return [self._session_to_dict(r) for r in result.scalars().all()]
            except Exception as e:
                logger.warning(f"DB _sessions_for failed: {e}")
        return [s for s in _mem.sessions.values() if s["delivery_id"] == delivery_id]

    async def _reminder_types_for(self, session_id: str) -> List[str]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryReminder.reminder_type)
                        .where(DeliveryReminder.scheduled_session_id == UUID(session_id))
                    )
                    return [r for r in result.scalars().all()]
            except Exception as e:
                logger.warning(f"DB _reminder_types_for failed: {e}")
        return [v["reminder_type"] for k, v in _mem.reminders.items() if v["scheduled_session_id"] == session_id]

    async def _blockers_for(self, delivery_id: str) -> List[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryBlocker).where(DeliveryBlocker.delivery_id == UUID(delivery_id))
                    )
                    return [self._blocker_to_dict(r) for r in result.scalars().all()]
            except Exception as e:
                logger.warning(f"DB _blockers_for failed: {e}")
        return [b for b in _mem.blockers.values() if b["delivery_id"] == delivery_id]

    async def _reschedules_for(self, delivery_id: str) -> List[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryRescheduleRequest).where(DeliveryRescheduleRequest.delivery_id == UUID(delivery_id))
                    )
                    return [self._reschedule_to_dict(r) for r in result.scalars().all()]
            except Exception as e:
                logger.warning(f"DB _reschedules_for failed: {e}")
        return [r for r in _mem.reschedules.values() if r["delivery_id"] == delivery_id]

    async def _notifications_for(self, delivery_id: str) -> List[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryNotification).where(DeliveryNotification.delivery_id == UUID(delivery_id))
                    )
                    return [self._notification_to_dict(r) for r in result.scalars().all()]
            except Exception as e:
                logger.warning(f"DB _notifications_for failed: {e}")
        return [n for n in _mem.notifications.values() if n["delivery_id"] == delivery_id]

    async def _get_reschedule(self, reschedule_request_id: str) -> Optional[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(DeliveryRescheduleRequest).where(DeliveryRescheduleRequest.id == UUID(reschedule_request_id))
                    )
                    row = result.scalar_one_or_none()
                    return self._reschedule_to_dict(row) if row else None
            except Exception as e:
                logger.warning(f"DB _get_reschedule failed: {e}")
        return _mem.reschedules.get(reschedule_request_id)

    async def _get_blocker(self, blocker_id: str) -> Optional[Dict]:
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(select(DeliveryBlocker).where(DeliveryBlocker.id == UUID(blocker_id)))
                    row = result.scalar_one_or_none()
                    return self._blocker_to_dict(row) if row else None
            except Exception as e:
                logger.warning(f"DB _get_blocker failed: {e}")
        return _mem.blockers.get(blocker_id)

    async def _patch_reschedule(self, reschedule_request_id: str, values: Dict[str, Any]) -> bool:
        values = {**values, "updated_at": datetime.utcnow()}
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(select(DeliveryRescheduleRequest).where(DeliveryRescheduleRequest.id == UUID(reschedule_request_id)))
                    if not result.scalar_one_or_none():
                        return False
                    await db.execute(update(DeliveryRescheduleRequest).where(DeliveryRescheduleRequest.id == UUID(reschedule_request_id)).values(**values))
                    return True
            except Exception as e:
                logger.warning(f"DB _patch_reschedule failed: {e}")
        if reschedule_request_id in _mem.reschedules:
            _mem.reschedules[reschedule_request_id].update({k: v for k, v in values.items() if k != "updated_at"})
            return True
        return False

    async def _patch_blocker(self, blocker_id: str, values: Dict[str, Any]) -> bool:
        values = {**values, "updated_at": datetime.utcnow()}
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(select(DeliveryBlocker).where(DeliveryBlocker.id == UUID(blocker_id)))
                    if not result.scalar_one_or_none():
                        return False
                    await db.execute(update(DeliveryBlocker).where(DeliveryBlocker.id == UUID(blocker_id)).values(**values))
                    return True
            except Exception as e:
                logger.warning(f"DB _patch_blocker failed: {e}")
        if blocker_id in _mem.blockers:
            _mem.blockers[blocker_id].update({k: v for k, v in values.items() if k != "updated_at"})
            return True
        return False

    async def _patch_delivery(self, delivery_id: str, values: Dict[str, Any]) -> bool:
        values = {**values, "updated_at": datetime.utcnow()}
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(select(Delivery).where(Delivery.id == UUID(delivery_id)))
                    if not result.scalar_one_or_none():
                        return False
                    await db.execute(update(Delivery).where(Delivery.id == UUID(delivery_id)).values(**values))
                    return True
            except Exception as e:
                logger.warning(f"DB _patch_delivery failed: {e}")
        if delivery_id in _mem.deliveries:
            _mem.deliveries[delivery_id].update({k: v for k, v in values.items() if k != "updated_at"})
            return True
        return False

    async def _relink_delivery_session(self, delivery_id: str, new_session_id: str) -> bool:
        """Point a delivery at a new conversation session_id. Separate from
        _patch_delivery because the DB column is PGUUID(as_uuid=True) and needs
        a real UUID object bound, while the in-memory fallback stores it as the
        plain string (matching how every other session_id is stored there)."""
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(select(Delivery).where(Delivery.id == UUID(delivery_id)))
                    if not result.scalar_one_or_none():
                        return False
                    await db.execute(
                        update(Delivery).where(Delivery.id == UUID(delivery_id))
                        .values(session_id=UUID(new_session_id), updated_at=datetime.utcnow())
                    )
                    return True
            except Exception as e:
                logger.warning(f"DB _relink_delivery_session failed: {e}")
        if delivery_id in _mem.deliveries:
            _mem.deliveries[delivery_id]["session_id"] = new_session_id
            return True
        return False

    async def _patch_session(self, session_id: str, values: Dict[str, Any]) -> bool:
        values = {**values, "updated_at": datetime.utcnow()}
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(select(DeliveryScheduledSession).where(DeliveryScheduledSession.id == UUID(session_id)))
                    if not result.scalar_one_or_none():
                        return False
                    await db.execute(update(DeliveryScheduledSession).where(DeliveryScheduledSession.id == UUID(session_id)).values(**values))
                    return True
            except Exception as e:
                logger.warning(f"DB _patch_session failed: {e}")
        if session_id in _mem.sessions:
            _mem.sessions[session_id].update({k: v for k, v in values.items() if k != "updated_at"})
            return True
        return False

    async def _increment_completed(self, delivery_id: str) -> None:
        delivery = await self._get_delivery(delivery_id)
        if not delivery:
            return
        new_count = (delivery.get("completed_sessions") or 0) + 1
        patch = {"completed_sessions": new_count}
        # Nearing/complete detection — only touches status while the delivery is
        # in a normal ongoing state, never overrides paused/escalated/discontinued.
        expected = delivery.get("expected_sessions") or 0
        current_status = delivery.get("delivery_status")
        if expected and new_count >= expected:
            patch["delivery_status"] = "completed"
        elif expected and new_count == expected - 1 and current_status in ("activating", "active", "at_risk"):
            patch["delivery_status"] = "nearing_completion"
        await self._patch_delivery(delivery_id, patch)

    # ── Row → dict ────────────────────────────────────────────────────────────

    def _delivery_to_dict(self, r) -> Dict:
        return {
            "id": str(r.id),
            "session_id": str(r.session_id) if r.session_id else None,
            "volunteer_id": r.volunteer_id, "volunteer_name": r.volunteer_name,
            "need_id": r.need_id, "nomination_id": r.nomination_id,
            "entity_id": r.entity_id, "coordinator_id": r.coordinator_id,
            "coordinator_phone": getattr(r, "coordinator_phone", None),
            "programme": r.programme, "start_date": r.start_date, "end_date": r.end_date,
            "expected_sessions": r.expected_sessions, "completed_sessions": r.completed_sessions,
            "volunteer_acknowledged": r.volunteer_acknowledged,
            "coordinator_acknowledged": r.coordinator_acknowledged,
            "first_session_ready": r.first_session_ready,
            "activation_completed_at": r.activation_completed_at.isoformat() if r.activation_completed_at else None,
            "readiness_checklist": getattr(r, "readiness_checklist", None),
            "last_summary": getattr(r, "last_summary", None),
            "risk_level": getattr(r, "risk_level", None),
            "delivery_status": r.delivery_status, "status_reason": r.status_reason,
        }

    def _session_to_dict(self, r) -> Dict:
        return {
            "id": str(r.id), "delivery_id": str(r.delivery_id),
            "session_number": r.session_number, "scheduled_date": r.scheduled_date,
            "start_time": r.start_time, "end_time": r.end_time, "subject": r.subject,
            "meeting_link": r.meeting_link, "delivery_mode": r.delivery_mode,
            "session_state": r.session_state, "outcome": r.outcome,
            "outcome_reason": r.outcome_reason, "outcome_reported_by": r.outcome_reported_by,
            "attendance_count": getattr(r, "attendance_count", None),
            "duration_minutes": getattr(r, "duration_minutes", None),
            "disruption_type": getattr(r, "disruption_type", None),
            "last_summary": getattr(r, "last_summary", None),
        }

    def _blocker_to_dict(self, r) -> Dict:
        return {
            "id": str(r.id), "delivery_id": str(r.delivery_id),
            "scheduled_session_id": str(r.scheduled_session_id) if r.scheduled_session_id else None,
            "blocker_type": r.blocker_type, "description": r.description,
            "status": r.status, "raised_by": r.raised_by,
            "owner": getattr(r, "owner", None),
            "resolution_notes": getattr(r, "resolution_notes", None),
            "resolved_at": r.resolved_at.isoformat() if getattr(r, "resolved_at", None) else None,
        }

    def _reschedule_to_dict(self, r) -> Dict:
        return {
            "id": str(r.id), "delivery_id": str(r.delivery_id),
            "scheduled_session_id": str(r.scheduled_session_id) if r.scheduled_session_id else None,
            "reason": r.reason, "preferred_date": r.preferred_date,
            "preferred_time": r.preferred_time, "requested_by": r.requested_by,
            "status": r.status,
            "resolution_notes": getattr(r, "resolution_notes", None),
            "resolved_at": r.resolved_at.isoformat() if getattr(r, "resolved_at", None) else None,
        }

    def _notification_to_dict(self, r) -> Dict:
        return {
            "id": str(r.id), "delivery_id": str(r.delivery_id),
            "stakeholder_type": r.stakeholder_type, "reason": r.reason,
            "channel": r.channel, "status": r.status,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }


# Singleton
delivery_service = DeliveryService()
