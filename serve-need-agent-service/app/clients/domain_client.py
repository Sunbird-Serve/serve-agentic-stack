"""
SERVE Need Agent Service - MCP Tool Client
Calls serve-mcp-server tools via the MCP SSE protocol.

This replaces the former REST-based DomainClient. The public interface is
identical so need_logic.py requires no changes.

Tool name mapping (former REST endpoint → MCP tool):
  resolve-coordinator       → resolve_coordinator_identity
  map-coordinator-school    → map_coordinator_to_school
  resolve-school            → resolve_school_context
  create-school             → create_school_context
  fetch-previous-needs      → fetch_previous_need_context
  save-need-draft           → create_or_update_need_draft  (dict unpacked to kwargs)
  get-missing-fields        → get_missing_need_fields
  evaluate-readiness        → evaluate_need_submission_readiness
  submit-for-approval       → submit_need_for_approval
  update-status             → update_need_status
  start-session (need)      → start_need_session
  resume-context (need)     → resume_need_context
  advance-state (need)      → advance_need_state
  pause-session (need)      → pause_need_session
  prepare-handoff           → prepare_fulfillment_handoff
  emit-handoff              → emit_need_handoff_event
  log-event                 → log_need_event
  save-message (need)       → save_need_message
  resume-context (shared)   → resume_session
  advance-state (shared)    → advance_session_state
  save-message (shared)     → save_message
  log-event (shared)        → log_event
  pause-session (shared)    → pause_need_session
  emit-handoff-event(shared)→ emit_handoff_event
"""
import asyncio
import os
import json
import logging
from typing import Dict, Any, List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://serve-mcp-server:8004")
_MCP_RETRIES = int(os.environ.get("MCP_RETRIES", "3"))


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict:
    """
    Call an MCP server tool via the SSE transport with exponential-backoff retry.

    Retries up to _MCP_RETRIES times on transient connection failures (0.5s, 1s, 2s).
    Returns {"status": "error", ...} on permanent failure so callers can inspect
    without catching exceptions.

    MCP tools that accept a Pydantic model expect arguments wrapped under the
    "params" key.  Tools with no parameters receive an empty dict as-is.
    """
    last_error: Exception | None = None
    wire_args = {"params": arguments} if arguments else {}

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
                                return {"result": item.text}
            return {}

        except Exception as e:
            last_error = e
            if attempt < _MCP_RETRIES - 1:
                wait = 0.5 * (2 ** attempt)  # 0.5s → 1s → 2s
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
        "message": "Serve system temporarily unavailable. Cannot verify this information.",
    }


class DomainClient:
    """
    MCP-backed replacement for the former HTTP DomainClient.
    All public methods keep the same signatures so need_logic.py is unchanged.
    """

    def __init__(self, base_url: str = None):
        pass

    # ============ Coordinator Operations ============

    async def resolve_coordinator_identity(
        self,
        whatsapp_number: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Dict:
        """Resolve coordinator identity from WhatsApp number or email."""
        args: Dict[str, Any] = {}
        if whatsapp_number:
            args["whatsapp_number"] = whatsapp_number
        if email:
            args["email"] = email
        if name:
            args["name"] = name
        result = await _call_mcp_tool("resolve_coordinator_identity", args)
        # Normalise empty / unexpected responses so Claude always sees a clear status
        if not result or result == {}:
            return {"status": "not_found", "serve_system_available": True,
                    "message": "Coordinator not found in Serve system"}
        if result.get("status") not in ("linked", "unlinked", "not_found", "error"):
            result.setdefault("status", "not_found")
        return result

    async def create_coordinator(
        self,
        name: str,
        whatsapp_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Dict:
        """Register a new coordinator in Serve Registry."""
        args: Dict[str, Any] = {"name": name}
        if whatsapp_number:
            args["whatsapp_number"] = whatsapp_number
        if email:
            args["email"] = email
        return await _call_mcp_tool("create_coordinator", args)

    async def map_coordinator_to_school(
        self,
        coordinator_id: str,
        school_id: str
    ) -> Dict:
        """Map a coordinator to an existing school."""
        return await _call_mcp_tool("map_coordinator_to_school", {
            "coordinator_id": coordinator_id,
            "school_id": school_id,
        })

    # ============ School Operations ============

    async def resolve_school_context(
        self,
        coordinator_id: Optional[str] = None,
        school_hint: Optional[str] = None
    ) -> Dict:
        """Resolve school context."""
        args: Dict[str, Any] = {}
        if coordinator_id:
            args["coordinator_id"] = coordinator_id
        if school_hint:
            args["school_hint"] = school_hint
        result = await _call_mcp_tool("resolve_school_context", args)
        # Normalise empty / unexpected responses so Claude always sees a clear status
        if not result or result == {}:
            return {"status": "not_found", "serve_system_available": True,
                    "message": "School not found in Serve system"}
        if result.get("status") not in ("existing", "new", "not_found", "error", "success", "linked"):
            # MCP may return school dict directly — wrap it
            if result.get("id") or result.get("school"):
                return result
            result.setdefault("status", "not_found")
        return result

    async def create_basic_school_context(
        self,
        name: str,
        location: str,
        contact_number: Optional[str] = None
    ) -> Dict:
        """Create a new school context."""
        args: Dict[str, Any] = {"name": name, "location": location}
        if contact_number:
            args["contact_number"] = contact_number
        return await _call_mcp_tool("create_school_context", args)

    async def fetch_previous_need_context(self, school_id: str) -> Dict:
        """Fetch previous need context for a school."""
        return await _call_mcp_tool("fetch_previous_need_context", {
            "school_id": school_id
        })

    # ============ Need Operations ============

    async def create_or_update_need_draft(
        self,
        session_id: str,
        need_data: Dict[str, Any]
    ) -> Dict:
        """Create or update a need draft.
        
        The MCP tool accepts individual fields rather than a dict,
        so we unpack need_data into keyword arguments.
        """
        args: Dict[str, Any] = {"session_id": session_id}
        # Unpack need_data fields that the MCP tool accepts
        field_map = {
            "subjects": "subjects",
            "grade_levels": "grade_levels",
            "student_count": "student_count",
            "time_slots": "time_slots",
            "start_date": "start_date",
            "duration_weeks": "duration_weeks",
            "schedule_preference": "schedule_preference",
            "grade_schedule": "grade_schedule",
            "skipped_grades": "skipped_grades",
            "special_requirements": "special_requirements",
            "coordinator_osid": "coordinator_osid",
            "entity_id": "entity_id",
        }
        for src_key, dst_key in field_map.items():
            if src_key in need_data and need_data[src_key] is not None:
                args[dst_key] = need_data[src_key]
        return await _call_mcp_tool("create_or_update_need_draft", args)

    async def get_missing_need_fields(self, session_id: str) -> Dict:
        """Get missing fields for a need draft."""
        return await _call_mcp_tool("get_missing_need_fields", {
            "session_id": session_id
        })

    async def evaluate_need_readiness(self, session_id: str) -> Dict:
        """Evaluate if need is ready for submission."""
        return await _call_mcp_tool("evaluate_need_submission_readiness", {
            "session_id": session_id
        })

    async def submit_need_for_approval(self, need_id: str) -> Dict:
        """Submit need for approval."""
        return await _call_mcp_tool("submit_need_for_approval", {
            "need_id": need_id
        })

    async def update_need_status(
        self,
        need_id: str,
        status: str,
        comments: Optional[str] = None
    ) -> Dict:
        """Update need status."""
        args: Dict[str, Any] = {"need_id": need_id, "status": status}
        if comments:
            args["comments"] = comments
        return await _call_mcp_tool("update_need_status", args)

    # ============ Session Operations ============

    async def start_need_session(
        self,
        channel: str,
        whatsapp_number: Optional[str] = None,
        channel_metadata: Optional[Dict] = None
    ) -> Dict:
        """Start a new need session."""
        args: Dict[str, Any] = {"channel": channel}
        if whatsapp_number:
            args["whatsapp_number"] = whatsapp_number
        if channel_metadata:
            args["channel_metadata"] = channel_metadata
        return await _call_mcp_tool("start_need_session", args)

    async def resume_need_context(self, session_id: str) -> Dict:
        """Resume an existing need session."""
        return await _call_mcp_tool("resume_need_context", {
            "session_id": session_id
        })

    async def advance_need_state(
        self,
        session_id: str,
        new_state: str,
        sub_state: Optional[str] = None
    ) -> Dict:
        """Advance need session state."""
        args: Dict[str, Any] = {
            "session_id": session_id,
            "new_state": new_state,
        }
        if sub_state:
            args["sub_state"] = sub_state
        return await _call_mcp_tool("advance_need_state", args)

    async def pause_need_session(
        self,
        session_id: str,
        reason: Optional[str] = None
    ) -> Dict:
        """Pause a need session."""
        args: Dict[str, Any] = {"session_id": session_id}
        if reason:
            args["reason"] = reason
        return await _call_mcp_tool("pause_need_session", args)

    # ============ Handoff Operations ============

    async def prepare_fulfillment_handoff(self, need_id: str) -> Dict:
        """Prepare handoff payload for fulfillment."""
        return await _call_mcp_tool("prepare_fulfillment_handoff", {
            "need_id": need_id
        })

    async def emit_handoff_event(
        self,
        session_id: str,
        from_agent: str,
        to_agent: str,
        payload: Dict[str, Any]
    ) -> Dict:
        """Emit handoff event for need workflow."""
        return await _call_mcp_tool("emit_need_handoff_event", {
            "session_id": session_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "payload": payload,
        })

    # ============ Telemetry ============

    async def log_need_event(
        self,
        session_id: str,
        event_type: str,
        data: Optional[Dict] = None
    ) -> Dict:
        """Log a need lifecycle event."""
        args: Dict[str, Any] = {
            "session_id": session_id,
            "event_type": event_type,
        }
        if data:
            args["data"] = data
        return await _call_mcp_tool("log_need_event", args)

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        agent: Optional[str] = None
    ) -> Dict:
        """Save a conversation message for a need session."""
        args: Dict[str, Any] = {
            "session_id": session_id,
            "role": role,
            "content": content,
        }
        if agent:
            args["agent"] = agent
        return await _call_mcp_tool("save_need_message", args)

    # ============ Shared Session Operations (used by need_logic via domain_client) ============

    async def call_capability(self, endpoint: str, payload: Dict[str, Any]) -> Dict:
        """
        Generic fallback for any endpoint not yet mapped to a dedicated method.
        Routes shared session endpoints to the general MCP session tools.
        """
        shared_endpoint_map = {
            "resume-context": "resume_session",
            "advance-state": "advance_session_state",
            "save-message": "save_message",
            "log-event": "log_event",
            "pause-session": "pause_need_session",
            "emit-handoff-event": "emit_handoff_event",
        }
        tool_name = shared_endpoint_map.get(endpoint)
        if tool_name:
            return await _call_mcp_tool(tool_name, payload)
        logger.warning(f"Unmapped endpoint: {endpoint}; returning graceful error")
        return {"status": "error", "error": f"Endpoint '{endpoint}' not implemented in MCP client"}


# Singleton instance
domain_client = DomainClient()
