"""
SERVE Delivery Agent Service - MCP Tool Client

Calls serve-mcp-server delivery_* tools via the MCP SSE protocol.
Same transport/retry pattern as the engagement agent's domain_client.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("delivery.mcp")

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://serve-mcp-server:8004")
_MCP_RETRIES = int(os.environ.get("MCP_RETRIES", "3"))


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict:
    """Call an MCP tool via SSE transport with exponential-backoff retry.
    Returns {"status": "error", ...} on permanent failure."""
    last_error: Optional[Exception] = None
    # Every delivery_* tool signature is `async def tool(params: SomeInput)`, so
    # the wire call MUST always include the "params" key — even when empty —
    # or FastMCP's Pydantic validation rejects it with "Field required". An
    # empty `arguments` dict is a legitimate call (e.g. "check all active
    # deliveries", no filters), so it must not be treated as "no args at all".
    wire_args = {"params": arguments}

    for attempt in range(_MCP_RETRIES):
        try:
            from mcp.client.session import ClientSession
            from mcp.client.sse import sse_client

            sse_url = f"{MCP_SERVER_URL}/sse"
            async with sse_client(url=sse_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=wire_args)
                    for item in result.content:
                        if hasattr(item, "text"):
                            try:
                                return json.loads(item.text)
                            except (json.JSONDecodeError, ValueError):
                                # A non-JSON payload from FastMCP is a tool-execution
                                # error (e.g. Pydantic validation failure), not a
                                # legitimate result. Surface it as status=error instead
                                # of silently returning it as if it were valid data —
                                # callers checking result.get("status") must be able to
                                # catch this.
                                logger.error(f"MCP tool [{tool_name}] returned non-JSON payload: {item.text}")
                                return {"status": "error", "error": item.text}
            return {}
        except Exception as e:
            last_error = e
            if attempt < _MCP_RETRIES - 1:
                wait = 0.5 * (2 ** attempt)
                logger.warning(
                    f"MCP tool [{tool_name}] attempt {attempt + 1}/{_MCP_RETRIES} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)

    logger.error(f"MCP tool [{tool_name}] failed after {_MCP_RETRIES} attempts: {last_error}")
    return {
        "status": "error",
        "serve_system_available": False,
        "error": str(last_error),
        "message": "Serve system temporarily unavailable.",
    }


class DomainClient:
    """MCP-backed client for the delivery agent."""

    # ── Generic session tools (shared MCP) ────────────────────────────────────

    async def save_message(self, session_id: str, role: str, content: str) -> Dict:
        return await _call_mcp_tool("save_message", {
            "session_id": session_id, "role": role, "content": content, "agent": "delivery_assistant",
        })

    async def advance_state(self, session_id: str, new_state: str,
                            sub_state: Optional[str] = None, active_agent: Optional[str] = None,
                            workflow: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {"session_id": session_id, "new_state": new_state}
        if sub_state:
            args["sub_state"] = sub_state
        if active_agent:
            args["active_agent"] = active_agent
        if workflow:
            args["workflow"] = workflow
        return await _call_mcp_tool("advance_session_state", args)

    async def log_event(self, session_id: str, event_type: str, data: Optional[Dict] = None) -> Dict:
        return await _call_mcp_tool("log_event", {
            "session_id": session_id, "event_type": event_type,
            "agent": "delivery_assistant", "data": data or {},
        })

    async def emit_handoff_event(self, session_id: str, from_agent: str, to_agent: str,
                                 handoff_type: str, payload: Optional[Dict] = None,
                                 reason: Optional[str] = None) -> Dict:
        return await _call_mcp_tool("emit_handoff_event", {
            "session_id": session_id, "from_agent": from_agent, "to_agent": to_agent,
            "handoff_type": handoff_type, "payload": payload or {}, "reason": reason,
        })

    # ── Delivery tools ─────────────────────────────────────────────────────────

    async def start_activation(self, **kw) -> Dict:
        return await _call_mcp_tool("delivery_start_activation", {k: v for k, v in kw.items() if v is not None})

    async def get_context(self, delivery_id: Optional[str] = None, session_id: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {}
        if delivery_id:
            args["delivery_id"] = delivery_id
        if session_id:
            args["session_id"] = session_id
        return await _call_mcp_tool("delivery_get_context", args)

    async def confirm_acknowledgement(self, delivery_id: str, party: str) -> Dict:
        return await _call_mcp_tool("delivery_confirm_acknowledgement",
                                    {"delivery_id": delivery_id, "party": party})

    async def confirm_first_session_readiness(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_confirm_first_session_readiness",
                                    {"delivery_id": delivery_id})

    async def complete_activation(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_complete_activation", {"delivery_id": delivery_id})

    async def create_scheduled_session(self, **kw) -> Dict:
        return await _call_mcp_tool("delivery_create_scheduled_session",
                                    {k: v for k, v in kw.items() if v is not None})

    async def get_scheduled_sessions(self, delivery_id: str, today_only: bool = False) -> Dict:
        return await _call_mcp_tool("delivery_get_scheduled_sessions",
                                    {"delivery_id": delivery_id, "today_only": today_only})

    async def get_due_reminders(self, delivery_id: Optional[str] = None, now: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {}
        if delivery_id:
            args["delivery_id"] = delivery_id
        if now:
            args["now"] = now
        return await _call_mcp_tool("delivery_get_due_reminders", args)

    async def mark_reminder(self, scheduled_session_id: str, reminder_type: str,
                            status: str = "sent", suppressed_reason: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {"scheduled_session_id": scheduled_session_id,
                                "reminder_type": reminder_type, "status": status}
        if suppressed_reason:
            args["suppressed_reason"] = suppressed_reason
        return await _call_mcp_tool("delivery_mark_reminder", args)

    async def record_session_outcome(self, scheduled_session_id: str, outcome: str,
                                     reason: Optional[str] = None, reported_by: str = "volunteer",
                                     attendance_count: Optional[int] = None,
                                     duration_minutes: Optional[int] = None,
                                     disruption_type: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {"scheduled_session_id": scheduled_session_id,
                                "outcome": outcome, "reported_by": reported_by}
        if reason:
            args["reason"] = reason
        if attendance_count is not None:
            args["attendance_count"] = attendance_count
        if duration_minutes is not None:
            args["duration_minutes"] = duration_minutes
        if disruption_type:
            args["disruption_type"] = disruption_type
        return await _call_mcp_tool("delivery_record_session_outcome", args)

    async def log_blocker(self, **kw) -> Dict:
        return await _call_mcp_tool("delivery_log_blocker", {k: v for k, v in kw.items() if v is not None})

    async def capture_reschedule(self, **kw) -> Dict:
        return await _call_mcp_tool("delivery_capture_reschedule", {k: v for k, v in kw.items() if v is not None})

    async def update_status(self, delivery_id: str, delivery_status: str,
                            status_reason: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {"delivery_id": delivery_id, "delivery_status": delivery_status}
        if status_reason:
            args["status_reason"] = status_reason
        return await _call_mcp_tool("delivery_update_status", args)

    async def evaluate_escalation(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_evaluate_escalation", {"delivery_id": delivery_id})

    # ── Full-spec expansion: granular reads ─────────────────────────────────────

    async def read_assignment_context(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_read_assignment_context", {"delivery_id": delivery_id})

    async def read_activation_context(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_read_activation_context", {"delivery_id": delivery_id})

    async def read_schedule_context(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_read_schedule_context", {"delivery_id": delivery_id})

    async def read_session_context(self, scheduled_session_id: str) -> Dict:
        return await _call_mcp_tool("delivery_read_session_context", {"scheduled_session_id": scheduled_session_id})

    async def read_delivery_history(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_read_delivery_history", {"delivery_id": delivery_id})

    # ── Full-spec expansion: signal processing & evaluation ─────────────────────

    async def extract_signals(self, text: str) -> Dict:
        return await _call_mcp_tool("delivery_extract_signals", {"text": text})

    async def detect_blockers(self, text: str) -> Dict:
        return await _call_mcp_tool("delivery_detect_blockers", {"text": text})

    async def get_missing_signals(self, delivery_id: str, target: str) -> Dict:
        return await _call_mcp_tool("delivery_get_missing_signals", {"delivery_id": delivery_id, "target": target})

    async def evaluate_activation(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_evaluate_activation", {"delivery_id": delivery_id})

    async def evaluate_readiness(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_evaluate_readiness", {"delivery_id": delivery_id})

    async def set_readiness_dimension(self, delivery_id: str, dimension: str, value: bool) -> Dict:
        return await _call_mcp_tool("delivery_set_readiness_dimension",
                                    {"delivery_id": delivery_id, "dimension": dimension, "value": value})

    async def evaluate_delivery_health(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_evaluate_delivery_health", {"delivery_id": delivery_id})

    async def evaluate_next_action(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_evaluate_next_action", {"delivery_id": delivery_id})

    # ── Full-spec expansion: activation content & coordinator notification ─────

    async def get_activation_content(self, delivery_id: str, content_type: str) -> Dict:
        return await _call_mcp_tool("delivery_get_activation_content",
                                    {"delivery_id": delivery_id, "content_type": content_type})

    async def notify_linked_stakeholder(self, delivery_id: str, reason: str, stakeholder: str = "coordinator") -> Dict:
        return await _call_mcp_tool("delivery_notify_linked_stakeholder",
                                    {"delivery_id": delivery_id, "stakeholder": stakeholder, "reason": reason})

    async def set_coordinator_phone(self, delivery_id: str, phone: str) -> Dict:
        return await _call_mcp_tool("delivery_set_coordinator_phone", {"delivery_id": delivery_id, "phone": phone})

    # ── Full-spec expansion: reminder wrappers, history, suppression ───────────

    async def read_reminder_history(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_read_reminder_history", {"delivery_id": delivery_id})

    async def suppress_reminder(self, scheduled_session_id: str, reminder_type: str, reason: str) -> Dict:
        return await _call_mcp_tool("delivery_suppress_reminder", {
            "scheduled_session_id": scheduled_session_id, "reminder_type": reminder_type, "reason": reason,
        })

    # ── Full-spec expansion: session check-in ───────────────────────────────────

    async def start_session_checkin(self, scheduled_session_id: str) -> Dict:
        return await _call_mcp_tool("delivery_start_session_checkin", {"scheduled_session_id": scheduled_session_id})

    async def close_checkin(self, scheduled_session_id: str) -> Dict:
        return await _call_mcp_tool("delivery_close_checkin", {"scheduled_session_id": scheduled_session_id})

    # ── Full-spec expansion: blocker resolution & support ───────────────────────

    async def update_blocker(self, blocker_id: str, status: str,
                             owner: Optional[str] = None, resolution_notes: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {"blocker_id": blocker_id, "status": status}
        if owner:
            args["owner"] = owner
        if resolution_notes:
            args["resolution_notes"] = resolution_notes
        return await _call_mcp_tool("delivery_update_blocker", args)

    async def get_support_guidance(self, blocker_type: str) -> Dict:
        return await _call_mcp_tool("delivery_get_support_guidance", {"blocker_type": blocker_type})

    async def create_ops_support_request(self, delivery_id: str, reason: str, urgency: str = "medium") -> Dict:
        return await _call_mcp_tool("delivery_create_ops_support_request",
                                    {"delivery_id": delivery_id, "reason": reason, "urgency": urgency})

    # ── Full-spec expansion: reschedule resolution ──────────────────────────────

    async def submit_reschedule_request(self, reschedule_request_id: str) -> Dict:
        return await _call_mcp_tool("delivery_submit_reschedule", {"reschedule_request_id": reschedule_request_id})

    async def read_reschedule_status(self, delivery_id: Optional[str] = None,
                                     reschedule_request_id: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {}
        if delivery_id:
            args["delivery_id"] = delivery_id
        if reschedule_request_id:
            args["reschedule_request_id"] = reschedule_request_id
        return await _call_mcp_tool("delivery_read_reschedule_status", args)

    async def resolve_reschedule_request(self, reschedule_request_id: str, status: str,
                                         resolution_notes: Optional[str] = None) -> Dict:
        args: Dict[str, Any] = {"reschedule_request_id": reschedule_request_id, "status": status}
        if resolution_notes:
            args["resolution_notes"] = resolution_notes
        return await _call_mcp_tool("delivery_resolve_reschedule", args)

    # ── Full-spec expansion: risk, handoff enrichment, summaries ───────────────

    async def raise_delivery_risk(self, delivery_id: str, risk_level: str, reason: str) -> Dict:
        return await _call_mcp_tool("delivery_raise_risk",
                                    {"delivery_id": delivery_id, "risk_level": risk_level, "reason": reason})

    async def prepare_ops_handoff(self, delivery_id: str, reason: str) -> Dict:
        return await _call_mcp_tool("delivery_prepare_ops_handoff", {"delivery_id": delivery_id, "reason": reason})

    async def write_session_summary(self, scheduled_session_id: str) -> Dict:
        return await _call_mcp_tool("delivery_write_session_summary", {"scheduled_session_id": scheduled_session_id})

    async def write_delivery_summary(self, delivery_id: str) -> Dict:
        return await _call_mcp_tool("delivery_write_delivery_summary", {"delivery_id": delivery_id})


# Singleton
domain_client = DomainClient()
