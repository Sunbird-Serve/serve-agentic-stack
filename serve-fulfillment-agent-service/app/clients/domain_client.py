"""
SERVE Fulfillment Agent Service - MCP Tool Client

Calls serve-mcp-server tools via the MCP SSE protocol.
Same transport pattern as the engagement agent's domain_client.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://serve-mcp-server:8004")
_MCP_RETRIES = int(os.environ.get("MCP_RETRIES", "3"))


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict:
    """
    Call an MCP server tool via SSE transport with exponential-backoff retry.
    Returns {"status": "error", "serve_system_available": False} on permanent failure.
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
    """
    MCP-backed client for the fulfillment agent.
    Provides data and session methods for volunteer-to-need matching.

    NOTE: create_fulfillment and confirm_nomination are intentionally NOT implemented.
    """

    # ── Data methods ──────────────────────────────────────────────────────────

    async def get_engagement_context(self, volunteer_id: str) -> Dict:
        """Load volunteer's fulfillment history, profile, and active nominations."""
        return await _call_mcp_tool("get_engagement_context", {"volunteer_id": volunteer_id})

    async def get_needs_for_entity(self, entity_id: str) -> Dict:
        """Get all open needs for a school/entity."""
        return await _call_mcp_tool("get_needs_for_entity", {"entity_id": entity_id})

    async def get_need_details(self, need_id: str) -> Dict:
        """Enrich a need with subject, grade, schedule, and time slots."""
        return await _call_mcp_tool("get_need_details", {"need_id": need_id})

    async def resolve_school_context(
        self,
        coordinator_id: Optional[str] = None,
        school_hint: Optional[str] = None,
    ) -> Dict:
        """Find schools/needs by hint (name, location, preference notes)."""
        args: Dict[str, Any] = {}
        if coordinator_id:
            args["coordinator_id"] = coordinator_id
        if school_hint:
            args["school_hint"] = school_hint
        return await _call_mcp_tool("resolve_school_context", args)

    async def nominate_volunteer_for_need(self, need_id: str, volunteer_id: str) -> Dict:
        """Nominate the volunteer for a need."""
        return await _call_mcp_tool("nominate_volunteer_for_need", {
            "need_id": need_id,
            "volunteer_id": volunteer_id,
        })

    async def get_nominations_for_need(self, need_id: str, status: Optional[str] = None) -> Dict:
        """Check existing nominations for a need."""
        args: Dict[str, Any] = {"need_id": need_id}
        if status:
            args["status"] = status
        return await _call_mcp_tool("get_nominations_for_need", args)

    # ── Session methods ───────────────────────────────────────────────────────

    async def save_message(self, session_id: str, role: str, content: str) -> Dict:
        """Persist a conversation message."""
        return await _call_mcp_tool("save_message", {
            "session_id": session_id,
            "role": role,
            "content": content,
            "agent": "fulfillment",
        })

    async def advance_state(self, session_id: str, new_state: str, sub_state: Optional[str] = None) -> Dict:
        """Advance session to a new workflow stage."""
        args: Dict[str, Any] = {"session_id": session_id, "new_state": new_state}
        if sub_state:
            args["sub_state"] = sub_state
        return await _call_mcp_tool("advance_session_state", args)

    async def log_event(self, session_id: str, event_type: str, data: Optional[Dict] = None) -> Dict:
        """Log a telemetry event."""
        return await _call_mcp_tool("log_event", {
            "session_id": session_id,
            "event_type": event_type,
            "agent": "fulfillment",
            "data": data or {},
        })

    async def emit_handoff_event(
        self, session_id: str, from_agent: str, to_agent: str, payload: Dict
    ) -> Dict:
        """Emit a handoff event between agents."""
        return await _call_mcp_tool("emit_handoff_event", {
            "session_id": session_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "payload": payload,
        })


# Singleton
domain_client = DomainClient()
