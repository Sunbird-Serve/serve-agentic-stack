"""
SERVE Delivery Agent Service - Reminder Engine

Deterministic, policy-driven reminder dispatch. This is the spec's core mandate:
reminders and completion checks fire as a function of schedule + state, never an
LLM decision.

`tick(now)` runs one pass:
  1. Fetch candidate reminder state from MCP (delivery_get_due_reminders).
  2. For each candidate, ask policy_engine which reminders are due.
  3. Render fixed template text, persist it into the delivery's conversation
     session, and record the reminder (idempotent via MCP unique constraint).
  4. If a session's follow-up nudge has gone unanswered past the grace window,
     mark it unverified (never fabricated as missed/completed) and re-evaluate
     escalation.

Exposed via POST /api/reminders/tick (manual/test driver) and an optional
background loop started from main.py's lifespan.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.clients.domain_client import domain_client
from app.service import policy_engine as pe

logger = logging.getLogger("delivery.reminders")


class ReminderEngine:

    def __init__(self, cfg: Optional[pe.DeliveryConfig] = None):
        self.cfg = cfg or pe.DeliveryConfig.from_env()

    async def tick(self, now: Optional[datetime] = None, delivery_id: Optional[str] = None) -> Dict[str, Any]:
        """Run one reminder pass. Returns a summary of actions taken."""
        now = now or datetime.now()
        result = await domain_client.get_due_reminders(delivery_id=delivery_id)
        if result.get("status") == "error":
            logger.warning(f"tick: get_due_reminders failed: {result.get('error')}")
            return {"status": "error", "error": result.get("error"), "sent": [], "unverified": []}

        candidates: List[Dict[str, Any]] = result.get("candidates", [])
        sent_actions: List[Dict[str, Any]] = []
        unverified_actions: List[Dict[str, Any]] = []
        escalations: List[Dict[str, Any]] = []

        logger.info(f"tick @ {now.isoformat()}: {len(candidates)} candidate session(s)")

        for cand in candidates:
            session = cand.get("session", {})
            session_id = session.get("id")
            delivery_session_id = cand.get("delivery_session_id")
            delivery_ctx = {"volunteer_name": cand.get("volunteer_name")}

            # 1. Send any due reminders
            for rtype in pe.due_reminders(cand, now, self.cfg):
                text = pe.render_reminder(rtype, session, delivery_ctx)
                if delivery_session_id:
                    await domain_client.save_message(delivery_session_id, "assistant", text)
                mark = await domain_client.mark_reminder(session_id, rtype, status="sent")
                await domain_client.log_event(
                    delivery_session_id or session_id, "delivery_reminder_sent",
                    {"reminder_type": rtype, "scheduled_session_id": session_id,
                     "duplicate": mark.get("duplicate", False)},
                )
                logger.info(f"tick: sent {rtype} for session {session_id} "
                            f"(duplicate={mark.get('duplicate', False)})")
                sent_actions.append({"session_id": session_id, "reminder_type": rtype,
                                     "duplicate": mark.get("duplicate", False)})

            # 2. Mark unverified if the follow-up window has fully elapsed
            if pe.should_mark_unverified(cand, now, self.cfg):
                await domain_client.record_session_outcome(session_id, "unverified",
                                                           reason="no response after follow-up", reported_by="system")
                await domain_client.log_event(
                    delivery_session_id or session_id, "delivery_session_unverified",
                    {"scheduled_session_id": session_id},
                )
                logger.info(f"tick: session {session_id} marked unverified (no response)")
                unverified_actions.append({"session_id": session_id})

                esc = await self._maybe_escalate(cand.get("delivery_id"), delivery_session_id)
                if esc:
                    escalations.append(esc)

        return {
            "status": "success",
            "now": now.isoformat(),
            "sent": sent_actions,
            "unverified": unverified_actions,
            "escalations": escalations,
        }

    async def _maybe_escalate(self, delivery_id: Optional[str], delivery_session_id: Optional[str]) -> Optional[Dict]:
        if not delivery_id:
            return None
        signals = await domain_client.evaluate_escalation(delivery_id)
        if signals.get("status") != "success":
            return None
        verdict = pe.evaluate_escalation(signals.get("signals", {}), self.cfg)
        if verdict["escalate"]:
            await domain_client.update_status(delivery_id, "escalated",
                                              status_reason="; ".join(verdict["reasons"]))
            if delivery_session_id:
                await domain_client.emit_handoff_event(
                    delivery_session_id, "delivery_assistant", "delivery_assistant",
                    "escalation", payload={"delivery_id": delivery_id, "reasons": verdict["reasons"]},
                    reason="; ".join(verdict["reasons"]),
                )
            logger.info(f"tick: delivery {delivery_id} ESCALATED — {verdict['reasons']}")
            return {"delivery_id": delivery_id, "reasons": verdict["reasons"]}
        return None


# Singleton
reminder_engine = ReminderEngine()
