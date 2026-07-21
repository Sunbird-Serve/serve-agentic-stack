"""
SERVE Delivery Agent Service - Core Turn Logic

Orchestrates one conversational turn:
  1. Terminal-stage guard.
  2. Resolve delivery context (from sub_state, session, or a fulfillment handoff
     payload → start activation). Missing context → honest activation_blocked.
  3. Dispatch mode: activation vs. daily operations.
  4. Run the LLM tool-loop (converse + persist confirmed facts).
  5. Deterministic post-loop policy: compute the next stage, and after any
     recorded outcome, evaluate escalation (never LLM-decided).

Reminders are handled separately by reminder_engine.py and are unaffected by
LLM availability.
"""
import logging
import time
from typing import Any, Dict, List, Optional

from app.clients.domain_client import domain_client
from app.service.llm_adapter import llm_adapter
from app.service import policy_engine as pe
from app.schemas.delivery_schemas import (
    DeliveryAgentTurnRequest, DeliveryAgentTurnResponse,
    ActivationStage, OpsStage, ControlStage, TERMINAL_STAGES,
    load_sub_state, dump_sub_state,
)

logger = logging.getLogger("delivery.logic")

_SYNTHETIC = {"__handoff__", "__auto_continue__"}
_TERMINAL_MESSAGES = {
    ControlStage.PAUSED.value: "No problem — we can pick this up whenever you're ready. 🙂",
    OpsStage.DELIVERY_COMPLETE.value: "Your delivery is complete. Thank you for teaching with eVidyaloka! 🙏",
}


class DeliveryAgentService:

    def __init__(self):
        self.cfg = pe.DeliveryConfig.from_env()

    async def process_turn(self, request: DeliveryAgentTurnRequest) -> DeliveryAgentTurnResponse:
        started = time.time()
        session_id = str(request.session_id)
        stage_in = request.session_state.stage
        sub_state = load_sub_state(request.session_state.sub_state)

        # ── 1. Terminal guard ─────────────────────────────────────────────────
        if stage_in in TERMINAL_STAGES:
            logger.info(f"[{session_id}] terminal stage '{stage_in}' — returning closing message")
            return self._response(
                _TERMINAL_MESSAGES.get(stage_in, "Thank you!"),
                state=stage_in, sub_state=request.session_state.sub_state,
            )

        # ── 2. Resolve delivery context ───────────────────────────────────────
        delivery, sessions, blockers = await self._resolve_context(session_id, sub_state, request)
        if not delivery:
            msg = ("I couldn't find your delivery assignment yet. Our team has been notified "
                   "and will set this up shortly. Please check back soon.")
            await domain_client.save_message(session_id, "assistant", msg)
            await domain_client.log_event(session_id, "delivery_activation_blocked", {"reason": "no_delivery_context"})
            await domain_client.advance_state(session_id, ActivationStage.ACTIVATION_BLOCKED.value,
                                              sub_state=dump_sub_state(sub_state), active_agent="delivery_assistant",
                                              workflow="delivery_support")
            self._log_turn(session_id, "activation", stage_in, ActivationStage.ACTIVATION_BLOCKED.value,
                           [], [], 0, started)
            return self._response(msg, state=ActivationStage.ACTIVATION_BLOCKED.value,
                                  sub_state=dump_sub_state(sub_state))

        delivery_id = delivery["id"]
        sub_state["delivery_id"] = delivery_id
        mode = self._mode(delivery)
        sub_state["mode"] = mode
        persona = (request.session_state.persona or "").lower()

        # Self-healing coordinator contact capture: there is no reliable
        # coordinator_id -> phone directory anywhere in this stack, so the
        # first time a coordinator messages in on their own, cache their
        # number for future notify_linked_stakeholder calls.
        if persona == "coordinator" and not delivery.get("coordinator_phone"):
            phone = (request.channel_metadata or {}).get("phone_number")
            if phone:
                await domain_client.set_coordinator_phone(delivery_id, phone)

        # ── 3. Build conversation messages ────────────────────────────────────
        messages = self._build_messages(request, mode)

        # ── 4. LLM tool-loop ──────────────────────────────────────────────────
        if mode == "activation":
            intro = await domain_client.get_activation_content(delivery_id, "intro")
            instructions = await domain_client.get_activation_content(delivery_id, "instructions")
            activation_content = {
                "intro": intro.get("content") if intro.get("status") == "success" else None,
                "instructions": instructions.get("content") if instructions.get("status") == "success" else None,
            }
            system_prompt = llm_adapter.build_activation_prompt(delivery, sessions, activation_content)
        else:
            system_prompt = llm_adapter.build_operations_prompt(delivery, sessions)

        tool_calls: List[str] = []
        # Snapshot BEFORE the tool loop runs. Acknowledgement and first-session
        # readiness are meant to be two separate volunteer confirmations across
        # two separate turns (spec: ask about the assignment, then separately
        # share first-session details and ask if they're ready) — a model can
        # otherwise collapse both into one turn from a single generic "yes I
        # confirm", marking someone "ready" for a session they were never shown.
        # See _execute_tool's confirm_readiness gate below.
        pre_turn_acknowledged = bool(delivery.get("volunteer_acknowledged"))

        async def tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> Any:
            tool_calls.append(tool_name)
            return await self._execute_tool(tool_name, tool_input, delivery_id, sessions,
                                            request.user_message or "", persona,
                                            pre_turn_acknowledged=pre_turn_acknowledged)

        text, collected = await llm_adapter.run_conversation_loop(
            system_prompt=system_prompt, messages=messages,
            tool_executor=tool_executor, max_iterations=6,
        )
        await self._audit_collected(session_id, collected)

        # ── 5. Resolve outcome + next stage ───────────────────────────────────
        signal = collected.get("signal_outcome") or {}
        response = await self._finalize(
            session_id=session_id, delivery_id=delivery_id, mode=mode,
            stage_in=stage_in, text=text, signal=signal, collected=collected,
            sub_state=sub_state,
        )
        self._log_turn(session_id, mode, stage_in, response.state, tool_calls,
                       list(collected.keys()), 1, started)
        return response

    # ── Context resolution ─────────────────────────────────────────────────────

    async def _resolve_context(self, session_id, sub_state, request):
        delivery_id = sub_state.get("delivery_id")
        ctx = None
        if delivery_id:
            ctx = await domain_client.get_context(delivery_id=delivery_id)
        if not ctx or ctx.get("status") != "success":
            ctx = await domain_client.get_context(session_id=session_id)

        # Fulfillment handoff payload → start activation
        if (not ctx or ctx.get("status") != "success"):
            handoff = sub_state.get("handoff") or {}
            if handoff.get("volunteer_id") and handoff.get("need_id"):
                logger.info(f"[{session_id}] starting activation from handoff payload")
                started = await domain_client.start_activation(
                    session_id=session_id,
                    volunteer_id=handoff.get("volunteer_id"),
                    volunteer_name=handoff.get("volunteer_name") or request.session_state.volunteer_name,
                    need_id=handoff.get("need_id"),
                    nomination_id=handoff.get("nomination_id"),
                    entity_id=handoff.get("entity_id") or handoff.get("preferred_school_id"),
                    coordinator_id=handoff.get("coordinator_id"),
                    programme=handoff.get("programme"),
                )
                if started.get("status") == "success":
                    ctx = await domain_client.get_context(delivery_id=started["delivery"]["id"])

        if not ctx or ctx.get("status") != "success":
            return None, [], []
        return ctx.get("delivery"), ctx.get("scheduled_sessions", []), ctx.get("blockers", [])

    def _mode(self, delivery: Dict[str, Any]) -> str:
        if delivery.get("activation_completed_at") or delivery.get("delivery_status") in ("active", "at_risk", "completed"):
            return "operations"
        return "activation"

    def _build_messages(self, request, mode) -> List[Dict[str, str]]:
        # Delivery conversations are short, transactional check-ins, not long-running
        # chat — a smaller window keeps input tokens (and cost) down per turn without
        # losing context that actually matters for the current activation/session.
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in request.conversation_history[-10:]
            if m.get("role") and m.get("content")
        ]
        um = request.user_message
        if um and um not in _SYNTHETIC:
            messages.append({"role": "user", "content": um})
        elif not messages:
            starter = ("Please introduce my teaching assignment and what I need to do to get started."
                       if mode == "activation" else "Any update on my sessions?")
            messages.append({"role": "user", "content": starter})
        return messages

    # ── Tool execution ─────────────────────────────────────────────────────────

    async def _execute_tool(self, tool_name: str, tool_input: Dict[str, Any], delivery_id: str,
                            sessions: Optional[List[Dict[str, Any]]] = None,
                            user_message: str = "", persona: str = "volunteer",
                            pre_turn_acknowledged: bool = False) -> Any:
        # Whoever is actually chatting — volunteer or coordinator — attributes
        # their own actions. Falls back to volunteer for any other/unknown persona.
        actor = "coordinator" if persona == "coordinator" else "volunteer"

        if tool_name == "confirm_acknowledgement":
            return await domain_client.confirm_acknowledgement(delivery_id, actor)
        if tool_name == "confirm_readiness":
            # Deterministic gate, not LLM discretion: readiness may only be
            # recorded once acknowledgement was ALREADY true before this turn
            # started. This forces the two confirmations onto two separate
            # volunteer replies, so "ready" always means they were actually
            # shown the first-session details and responded to that specific
            # question — never inferred from one generic "yes I confirm".
            if not pre_turn_acknowledged:
                logger.info(f"confirm_readiness blocked for delivery {delivery_id}: "
                           f"acknowledgement not yet confirmed in a prior turn")
                return {"status": "blocked", "reason": "acknowledgement_not_yet_confirmed"}
            return await domain_client.confirm_first_session_readiness(delivery_id)
        if tool_name == "record_session_outcome":
            sid = tool_input.get("scheduled_session_id")
            target, ambiguous = self._resolve_target_session(sid, sessions or [], user_message)
            if target is None:
                # Genuinely ambiguous — do NOT guess which session the reply is
                # about (spec: never invent completion). Hand the LLM the list so
                # it asks the volunteer which one, by date.
                options = [{"id": s.get("id"), "date": s.get("scheduled_date"),
                            "subject": s.get("subject")} for s in ambiguous]
                logger.warning(
                    f"record_session_outcome: {len(ambiguous)} sessions awaiting an "
                    f"update and reply is ambiguous — asking volunteer to clarify"
                )
                return {"status": "needs_clarification",
                        "message": "More than one session is awaiting an update. Ask the volunteer "
                                   "which session they mean (by date) before recording anything.",
                        "sessions": options}
            if target != sid:
                logger.info(f"record_session_outcome: resolved session_id {sid!r} → {target}")
            return await domain_client.record_session_outcome(
                target, tool_input.get("outcome", "completed"),
                reason=tool_input.get("reason"), reported_by=actor,
                attendance_count=tool_input.get("attendance_count"),
                duration_minutes=tool_input.get("duration_minutes"),
                disruption_type=tool_input.get("disruption_type"))
        if tool_name == "log_blocker":
            return await domain_client.log_blocker(
                delivery_id=delivery_id, blocker_type=tool_input.get("blocker_type", "other"),
                description=tool_input.get("description"),
                scheduled_session_id=tool_input.get("scheduled_session_id"), raised_by=actor)
        if tool_name == "capture_reschedule_request":
            return await domain_client.capture_reschedule(
                delivery_id=delivery_id, scheduled_session_id=tool_input.get("scheduled_session_id"),
                reason=tool_input.get("reason"), preferred_date=tool_input.get("preferred_date"),
                preferred_time=tool_input.get("preferred_time"), requested_by=actor)
        if tool_name == "notify_linked_stakeholder":
            reason = tool_input.get("reason") or "The volunteer asked us to keep you updated."
            return await domain_client.notify_linked_stakeholder(delivery_id, reason, stakeholder="coordinator")
        if tool_name == "signal_outcome":
            return tool_input  # handled after the loop
        logger.warning(f"Unknown tool: {tool_name}")
        return {"status": "error", "error": f"unknown tool {tool_name}"}

    # ── Finalization ───────────────────────────────────────────────────────────

    async def _finalize(self, *, session_id, delivery_id, mode, stage_in, text, signal, collected, sub_state):
        outcome = signal.get("outcome")

        # Explicit terminal / control outcomes from the LLM. Pause/escalate pick
        # the activation-phase or operations-phase control stage variant based
        # on the CURRENT mode, so a pause/escalation mid-activation is tracked
        # distinctly from one during daily operations (spec's per-phase
        # granularity) while resuming behaves identically either way.
        if outcome == "paused":
            pause_stage = (ControlStage.ACTIVATION_PAUSED.value if mode == "activation"
                          else ControlStage.PAUSED.value)
            return await self._transition(session_id, delivery_id, stage_in, pause_stage,
                                          text or _TERMINAL_MESSAGES[ControlStage.PAUSED.value], sub_state,
                                          delivery_status="paused")
        if outcome == "escalate":
            reason = signal.get("reason") or "volunteer conversation flagged for review"
            escalate_stage = (ControlStage.ACTIVATION_ESCALATED.value if mode == "activation"
                             else ControlStage.HUMAN_REVIEW.value)
            await domain_client.emit_handoff_event(session_id, "delivery_assistant", "delivery_assistant",
                                                   "escalation", payload={"delivery_id": delivery_id}, reason=reason)
            return await self._transition(session_id, delivery_id, stage_in, escalate_stage,
                                          text or "I've flagged this for our team — they'll follow up with you soon.",
                                          sub_state, delivery_status="escalated", status_reason=reason)
        if outcome == "delivery_complete":
            # GATED — the same way activation_complete is gated below. The spec
            # is explicit: "Completed Delivery — Use only when required delivery
            # completion criteria satisfied, sufficient session-level evidence
            # exists." An LLM's signal alone is never sufficient; verify against
            # the real recorded session count before honoring it.
            fresh = await domain_client.get_context(delivery_id=delivery_id)
            d = fresh.get("delivery", {}) if fresh.get("status") == "success" else {}
            completed = d.get("completed_sessions") or 0
            expected = d.get("expected_sessions") or 0
            if not expected or completed >= expected:
                return await self._transition(session_id, delivery_id, stage_in, OpsStage.DELIVERY_COMPLETE.value,
                                              text or _TERMINAL_MESSAGES[OpsStage.DELIVERY_COMPLETE.value], sub_state,
                                              delivery_status="completed")
            remaining = expected - completed
            logger.info(f"[{session_id}] delivery_complete blocked — {completed}/{expected} sessions completed")
            text = text or (
                f"Thanks for confirming! You still have {remaining} session"
                f"{'s' if remaining != 1 else ''} left in this delivery — I'll keep you posted as they come up."
            )
            # Falls through to normal stage computation below — stays in operations.
        if outcome == "activation_complete":
            complete = await domain_client.complete_activation(delivery_id)
            if complete.get("status") == "success":
                # Activation done → move into daily operations
                return await self._transition(session_id, delivery_id, stage_in, OpsStage.DELIVERY_OPERATIONS.value,
                                              text or "You're all set for your first session. I'll remind you as it approaches!",
                                              sub_state, mode="operations")
            # Gate not satisfied — the LLM signalled completion early. Stay in
            # activation and ask about exactly what's missing. Do NOT fall back
            # to the "trouble responding" message here: nothing failed, the
            # deterministic gate just did its job of catching a premature signal.
            missing = complete.get("missing", [])
            logger.info(f"[{session_id}] activation_complete blocked, missing={missing}")
            # Always override here, even if the LLM already wrote prose — the
            # model just signalled completion that the deterministic gate
            # rejected, so its own text almost always claims a success that
            # didn't happen (e.g. "you're all set!"). The honest prompt about
            # what's actually still missing must win, not whatever it said.
            text = self._activation_blocked_prompt(missing)

        # Operations mode: after any recorded outcome, evaluate escalation deterministically
        if mode == "operations" and "record_session_outcome" in collected:
            await self._post_outcome_escalation(session_id, delivery_id)

        # No terminal signal → compute the next stage from delivery state.
        # Prose from the LLM wins; if it wrote nothing (a tool-only turn), build a
        # deterministic line from what the tools actually did — the outage fallback
        # is reserved for genuine failures where nothing at all was collected.
        next_stage = await self._compute_stage(delivery_id, mode, stage_in)
        message = text or self._synthesize_ack(collected) or llm_adapter._fallback()
        resume_status = None
        if stage_in in (ControlStage.PAUSED.value, ControlStage.HUMAN_REVIEW.value,
                        ControlStage.ACTIVATION_PAUSED.value, ControlStage.ACTIVATION_ESCALATED.value):
            # Leaving any pause/escalation stage (activation or operations
            # phase — the conversation stage is moving forward again):
            # delivery_status must come back out of "paused" / "escalated" too,
            # otherwise reminder suppression (which checks delivery_status)
            # stays stuck forever even though the conversation itself resumed.
            resume_status = "active" if mode == "operations" else "activating"
        return await self._transition(session_id, delivery_id, stage_in, next_stage,
                                      message, sub_state, delivery_status=resume_status)

    async def _post_outcome_escalation(self, session_id, delivery_id):
        signals = await domain_client.evaluate_delivery_health(delivery_id)
        if signals.get("status") != "success":
            return
        verdict = pe.evaluate_delivery_health(signals.get("signals", {}), self.cfg)
        if verdict["escalate"]:
            await domain_client.update_status(delivery_id, "at_risk", status_reason="; ".join(verdict["reasons"]))
            await domain_client.emit_handoff_event(session_id, "delivery_assistant", "delivery_assistant",
                                                   "escalation", payload={"delivery_id": delivery_id, "reasons": verdict["reasons"]},
                                                   reason="; ".join(verdict["reasons"]))
            logger.info(f"[{session_id}] delivery {delivery_id} flagged at_risk — {verdict['reasons']}")

    async def _compute_stage(self, delivery_id, mode, stage_in) -> str:
        if mode == "operations":
            return OpsStage.DELIVERY_OPERATIONS.value
        ctx = await domain_client.get_context(delivery_id=delivery_id)
        d = ctx.get("delivery", {}) if ctx.get("status") == "success" else {}
        if d.get("activation_completed_at"):
            return OpsStage.DELIVERY_OPERATIONS.value
        if d.get("first_session_ready"):
            return ActivationStage.FIRST_SESSION_READY.value
        if d.get("volunteer_acknowledged"):
            return ActivationStage.VOLUNTEER_ACKNOWLEDGED.value
        return ActivationStage.ACTIVATION_STARTED.value

    async def _transition(self, session_id, delivery_id, stage_in, stage_out, message, sub_state,
                          delivery_status: Optional[str] = None, status_reason: Optional[str] = None,
                          mode: Optional[str] = None) -> DeliveryAgentTurnResponse:
        if not pe.is_valid_transition(stage_in, stage_out):
            logger.warning(f"[{session_id}] invalid transition {stage_in} → {stage_out}; staying at {stage_in}")
            stage_out = stage_in
        if mode:
            sub_state["mode"] = mode
        if delivery_status:
            await domain_client.update_status(delivery_id, delivery_status, status_reason)
            await domain_client.log_event(session_id, "delivery_status_changed",
                                          {"new_status": delivery_status, "reason": status_reason})
        if stage_out in (ControlStage.PAUSED.value, ControlStage.ACTIVATION_PAUSED.value):
            await domain_client.log_event(session_id, "conversation_paused", {"delivery_id": delivery_id})
        elif stage_out == OpsStage.DELIVERY_COMPLETE.value:
            await domain_client.log_event(session_id, "conversation_closed", {"delivery_id": delivery_id})
        sub_state_str = dump_sub_state(sub_state)
        if message:
            await domain_client.save_message(session_id, "assistant", message)
        await domain_client.advance_state(session_id, stage_out, sub_state=sub_state_str,
                                          active_agent="delivery_assistant", workflow="delivery_support")
        return self._response(message, state=stage_out, sub_state=sub_state_str)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _response(self, message, state, sub_state=None, auto_continue=False) -> DeliveryAgentTurnResponse:
        return DeliveryAgentTurnResponse(
            assistant_message=message, auto_continue=auto_continue,
            active_agent="delivery_assistant", workflow="delivery_support",
            state=state, sub_state=sub_state,
        )

    _TERMINAL_SESSION_STATES = {"completed", "partially_completed", "missed", "cancelled"}

    def _resolve_target_session(self, sid: Optional[str], sessions: List[Dict[str, Any]],
                                user_message: str):
        """Decide which scheduled session an outcome should be recorded against.

        Returns (session_id, None) when a single unambiguous target is found, or
        (None, [ambiguous sessions]) when it genuinely cannot be determined — in
        which case the caller asks the volunteer to clarify rather than guessing.

        Deliberately does NOT blindly trust an id the LLM supplies: when several
        sessions are genuinely awaiting an answer, a small model will happily pick
        one at random. Recording against a session the volunteer didn't actually
        identify is a form of inventing completion, which the spec forbids — so
        with 2+ candidates we require the volunteer's OWN words to point at one,
        else we ask.

        Resolution order:
          1. Narrow to sessions actually awaiting a completion answer
             (completion_check_sent); fall back to all open sessions if none.
          2. Exactly one candidate → unambiguous, use it (and auto-correct a
             bogus/placeholder id the LLM may have sent).
          3. Multiple candidates → match the volunteer's own words (ISO date,
             weekday, relative day, or subject). Exactly one match → use it.
          4. Otherwise ambiguous → return the candidate list so the agent asks.
        """
        open_sessions = [
            s for s in sessions
            if s.get("outcome") is None and s.get("session_state") not in self._TERMINAL_SESSION_STATES
        ]

        # 1. Prefer sessions whose completion check has actually gone out.
        awaiting = [s for s in open_sessions if s.get("session_state") == "completion_check_sent"]
        candidates = awaiting or open_sessions

        if not candidates:
            return None, []

        # 2. Single candidate → unambiguous (even if the LLM sent a bogus id).
        if len(candidates) == 1:
            return candidates[0].get("id"), None

        # 3. Multiple candidates → the volunteer's own words must disambiguate.
        matched = self._match_session_from_text(candidates, user_message)
        if matched:
            return matched, None

        # 4. Truly ambiguous — do not guess.
        return None, candidates

    def _match_session_from_text(self, candidates: List[Dict[str, Any]], text: str) -> Optional[str]:
        """Return a candidate's id if the volunteer's message uniquely points at
        it via its ISO date (2026-07-20), weekday (Monday), a relative day
        (today / yesterday / tomorrow), or subject (Maths). Returns None if zero
        or more than one candidate matches."""
        if not text:
            return None
        low = text.lower()
        relative_dates = self._relative_date_map(low)  # {iso_date: True} mentioned relatively
        hits = set()
        for s in candidates:
            tokens = []
            date_str = s.get("scheduled_date")
            iso = (date_str or "")[:10]
            if date_str:
                tokens.append(date_str.lower())
                weekday = self._weekday_name(date_str)
                if weekday:
                    tokens.append(weekday)
            if s.get("subject"):
                tokens.append(str(s["subject"]).lower())
            matched = any(tok and tok in low for tok in tokens)
            if not matched and iso and iso in relative_dates:
                matched = True
            if matched:
                hits.add(s.get("id"))
        return next(iter(hits)) if len(hits) == 1 else None

    def _relative_date_map(self, low: str) -> Dict[str, bool]:
        """Map relative-day words present in the message to concrete ISO dates in
        the delivery timezone, so 'yes, yesterday's class happened' can pick the
        session dated yesterday. Empty when no relative word is present."""
        words = {
            "today": 0, "tonight": 0,
            "yesterday": -1, "kal": None,  # 'kal' is ambiguous (yesterday/tomorrow) — skip
            "tomorrow": 1,
        }
        present = {w: off for w, off in words.items() if off is not None and w in low}
        if not present:
            return {}
        try:
            from datetime import datetime as _dt, timedelta as _td
            from zoneinfo import ZoneInfo
            base = _dt.now(ZoneInfo(self.cfg.timezone)).date()
        except Exception:
            from datetime import datetime as _dt, timedelta as _td
            base = _dt.now().date()
        return {(base + _td(days=off)).isoformat(): True for off in present.values()}

    def _session_label(self, date_str: Optional[str], subject: Optional[str]) -> Optional[str]:
        """Human-friendly session label for a clarification prompt, e.g.
        'Mathematics — Monday (2026-07-20)'. No internal ids or jargon."""
        parts = []
        if subject:
            parts.append(str(subject))
        iso = (date_str or "")[:10]
        weekday = self._weekday_name(date_str) if date_str else None
        if weekday and iso:
            parts.append(f"{weekday.capitalize()} ({iso})")
        elif iso:
            parts.append(iso)
        return " — ".join(parts) if parts else None

    def _synthesize_ack(self, collected: Dict[str, Any]) -> Optional[str]:
        """Build a deterministic, user-facing line for a tool-only turn (LLM wrote
        no prose). Returns None only when nothing meaningful was collected, so the
        caller can fall back to the honest outage message. Never leaks internal
        ids, tool names, or jargon — spec guardrails apply to synthesized text too."""
        rec = collected.get("record_session_outcome")
        if isinstance(rec, dict):
            if rec.get("status") == "needs_clarification":
                lines = []
                for o in rec.get("sessions") or []:
                    label = self._session_label(o.get("date"), o.get("subject"))
                    if label:
                        lines.append(f"• {label}")
                listing = ("\n" + "\n".join(lines)) if lines else ""
                return ("I'm tracking more than one session for you — which one do you mean?"
                        + listing)
            if rec.get("status") == "success":
                return "Thanks for letting me know — I've noted that. 🙏"
        blocker = collected.get("log_blocker")
        if isinstance(blocker, dict):
            if blocker.get("status") == "success":
                return ("Thanks for flagging this — I've noted it so we can help sort it out. "
                        "Is there anything else I can help with?")
            # The write actually failed (bad session reference, transient MCP
            # error, etc). Never claim it was noted when it wasn't — that would
            # be a false confirmation the volunteer relies on and nobody follows
            # up on, since nothing downstream re-checks this the way the
            # activation gate re-checks confirm_acknowledgement/confirm_readiness.
            return ("I wasn't able to save that just now — could you try sending it again "
                    "in a moment?")
        resched = collected.get("capture_reschedule_request")
        if isinstance(resched, dict):
            if resched.get("status") == "success":
                return ("I've captured your reschedule request and passed it along — please note "
                        "it isn't confirmed yet, our team will follow up with you.")
            return ("I wasn't able to save that reschedule request just now — could you try "
                    "sending it again in a moment?")
        readiness = collected.get("confirm_readiness")
        if isinstance(readiness, dict):
            if readiness.get("status") == "success":
                return "Great — you're all set for your first session! I'll remind you as it approaches."
            if readiness.get("status") == "blocked":
                return "Just to confirm — do you acknowledge and accept this teaching assignment?"
            return "I wasn't able to save that just now — could you confirm again in a moment?"
        ack = collected.get("confirm_acknowledgement")
        if isinstance(ack, dict):
            if ack.get("status") == "success":
                return "Thanks for confirming!"
            return "I wasn't able to save that just now — could you confirm again in a moment?"
        notify = collected.get("notify_linked_stakeholder")
        if isinstance(notify, dict):
            # The outer status is "success" whenever the MCP call itself
            # completed — but that's just "we recorded the attempt", not "the
            # coordinator was actually reached". The real outcome is nested
            # under notification.status; check THAT before claiming anything.
            inner_status = (notify.get("notification") or {}).get("status")
            if inner_status == "sent":
                return "I've let your coordinator know. 🙏"
            if inner_status == "no_contact_on_file":
                return ("I don't have a phone number on file for your coordinator yet, so I "
                        "couldn't reach them directly — I've noted your update for our team instead.")
            return ("I wasn't able to reach your coordinator just now — I've noted your update "
                    "for our team instead.")
        sig = collected.get("signal_outcome")
        if isinstance(sig, dict) and sig.get("outcome") == "continue":
            # Last resort: even the LLM's tools-off follow-up turn (see
            # llm_adapter.run_conversation_loop) produced nothing. Nothing
            # failed technically, so don't claim trouble responding — just
            # invite them to continue rather than leaving them with nothing.
            return "I'm here — what would you like to know about your sessions?"
        return None

    @staticmethod
    def _weekday_name(date_str: str) -> Optional[str]:
        from datetime import datetime as _dt
        try:
            return _dt.strptime(date_str[:10], "%Y-%m-%d").strftime("%A").lower()
        except (ValueError, TypeError):
            return None

    def _activation_blocked_prompt(self, missing: List[str]) -> str:
        """Deterministic, honest prompt when the LLM signals activation_complete
        before the real gates (acknowledgement + first-session readiness) are
        both satisfied. Never the generic outage message — nothing failed."""
        if "volunteer_acknowledged" in missing and "first_session_ready" in missing:
            return ("Before we finish setting you up — can you confirm you're aware of "
                    "the assignment, and let me know once you're ready for your first session?")
        if "first_session_ready" in missing:
            return "Great, thanks for confirming! One more thing — are you all set and ready for your first session?"
        if "volunteer_acknowledged" in missing:
            return "Just to confirm — do you acknowledge and accept this teaching assignment?"
        return "Let's continue getting you set up for your first session."

    async def _audit_collected(self, session_id: str, collected: Dict[str, Any]) -> None:
        """Fill in the spec's telemetry catalogue for events that are side
        effects of a successful tool call, not a stage transition — those are
        already covered centrally in _transition. Best-effort: never raises,
        since a missed audit log must never break the actual turn."""
        try:
            ack = collected.get("confirm_acknowledgement")
            if isinstance(ack, dict) and ack.get("status") == "success":
                await domain_client.log_event(session_id, "acknowledgement_received",
                                              {"party": ack.get("party")})
            readiness = collected.get("confirm_readiness")
            if isinstance(readiness, dict) and readiness.get("status") == "success":
                await domain_client.log_event(session_id, "readiness_confirmed", {})
            resched = collected.get("capture_reschedule_request")
            if isinstance(resched, dict) and resched.get("status") == "success":
                await domain_client.log_event(session_id, "reschedule_requested", {})
        except Exception as e:
            logger.warning(f"[{session_id}] _audit_collected failed (non-fatal): {e}")

    def _log_turn(self, session_id, mode, stage_in, stage_out, tool_calls, signals, llm_attempts, started):
        duration_ms = int((time.time() - started) * 1000)
        logger.info(
            f"[{session_id}] turn done | mode={mode} | {stage_in}→{stage_out} | "
            f"tools={tool_calls} | results={signals} | llm_attempts={llm_attempts} | {duration_ms}ms"
        )


# Singleton
delivery_agent_service = DeliveryAgentService()
