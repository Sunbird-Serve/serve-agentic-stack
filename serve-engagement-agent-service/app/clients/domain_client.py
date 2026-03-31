"""
SERVE Engagement Agent Service - MCP Tool Client

Calls serve-mcp-server tools via the MCP SSE protocol.
Same transport pattern as the need agent's domain_client.

TODO (contributor): Add methods here as new MCP tools are needed.
  e.g. get_volunteer_profile, save_volunteer_fields, log_engagement_event, etc.
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
    Returns {"status": "error", ...} on permanent failure.
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
    MCP-backed client for the engagement agent.
    Add methods here as the engagement flow requires new MCP tool calls.
    """

    # ── Session ───────────────────────────────────────────────────────────────

    async def resume_session(self, session_id: str) -> Dict:
        """Resume an existing session with full context."""
        return await _call_mcp_tool("resume_session", {"session_id": session_id})

    async def advance_state(self, session_id: str, new_state: str, sub_state: Optional[str] = None) -> Dict:
        """Advance session to a new workflow stage."""
        args: Dict[str, Any] = {"session_id": session_id, "new_state": new_state}
        if sub_state:
            args["sub_state"] = sub_state
        return await _call_mcp_tool("advance_session_state", args)

    async def save_message(self, session_id: str, role: str, content: str, agent: str = "engagement") -> Dict:
        """Persist a conversation message."""
        return await _call_mcp_tool("save_message", {
            "session_id": session_id,
            "role": role,
            "content": content,
            "agent": agent,
        })

    async def log_event(self, session_id: str, event_type: str, data: Optional[Dict] = None) -> Dict:
        """Log a telemetry event."""
        return await _call_mcp_tool("log_event", {
            "session_id": session_id,
            "event_type": event_type,
            "agent": "engagement",
            "data": data or {},
        })

    # ── Volunteer Context ─────────────────────────────────────────────────────

    async def get_engagement_context(self, volunteer_id: str) -> Dict:
        """Load fulfillment history, active nominations, and profile for engagement."""
        return await _call_mcp_tool("get_engagement_context", {"volunteer_id": volunteer_id})

    async def engagement_save_confirmed_signals(self, session_id: str, signals: Dict[str, Any]) -> Dict:
        """Persist confirmed engagement signals in MCP-managed session state."""
        return await _call_mcp_tool("engagement_save_confirmed_signals", {
            "session_id": session_id,
            "signals": signals,
        })

    async def engagement_update_volunteer_status(
        self,
        session_id: str,
        volunteer_status: str,
        reason: Optional[str] = None,
        signals: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Persist engagement status in MCP-managed session state."""
        args: Dict[str, Any] = {
            "session_id": session_id,
            "volunteer_status": volunteer_status,
        }
        if reason:
            args["reason"] = reason
        if signals:
            args["signals"] = signals
        return await _call_mcp_tool("engagement_update_volunteer_status", args)

    async def engagement_prepare_fulfillment_handoff(
        self,
        session_id: str,
        signals: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """Build the fulfillment handoff payload for the engagement session."""
        args: Dict[str, Any] = {"session_id": session_id}
        if signals:
            args["signals"] = signals
        return await _call_mcp_tool("engagement_prepare_fulfillment_handoff", args)

    async def save_memory_summary(
        self,
        session_id: str,
        summary_text: str,
        key_facts: Optional[list] = None,
        volunteer_id: Optional[str] = None,
    ) -> Dict:
        """Persist a summary using the generic MCP memory tool."""
        args: Dict[str, Any] = {
            "session_id": session_id,
            "summary_text": summary_text,
        }
        if key_facts is not None:
            args["key_facts"] = key_facts
        if volunteer_id:
            args["volunteer_id"] = volunteer_id
        return await _call_mcp_tool("save_memory_summary", args)

    # ── Volunteer Profile ─────────────────────────────────────────────────────

    async def get_volunteer_profile(self, session_id: str) -> Dict:
        """Fetch the volunteer's profile from MCP cache."""
        return await _call_mcp_tool("get_volunteer_profile", {"session_id": session_id})

    async def save_volunteer_fields(self, session_id: str, fields: Dict[str, Any]) -> Dict:
        """Save updated volunteer profile fields."""
        return await _call_mcp_tool("save_volunteer_fields", {
            "session_id": session_id,
            "fields": fields,
        })

    # TODO (contributor): add more methods as needed
    # e.g. fetch_matching_opportunities, confirm_availability, etc.


# Singleton
domain_client = DomainClient()
