"""
SERVE Onboarding Agent Service - MCP Tool Client
Calls serve-mcp-server tools via the MCP SSE protocol.

This replaces the former REST-based DomainClient. The public interface is
identical so onboarding_logic.py and memory_service.py require no changes.

Tool name mapping (former REST endpoint → MCP tool):
  get-missing-fields        → get_missing_fields
  save-confirmed-fields     → save_volunteer_fields
  advance-state             → advance_session_state
  save-message              → save_message
  log-event                 → log_event
  emit-handoff-event        → emit_handoff_event
  save-memory-summary       → save_memory_summary
  get-memory-summary        → get_memory_summary
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
    return {"status": "error", "error": str(last_error)}


class DomainClient:
    """
    MCP-backed replacement for the former HTTP DomainClient.
    All public methods keep the same signatures.
    """

    def __init__(self, base_url: str = None):
        pass

    async def get_missing_fields(self, session_id: UUID) -> Dict:
        """Get missing profile fields."""
        return await _call_mcp_tool("get_missing_fields", {
            "session_id": str(session_id)
        })

    async def save_confirmed_fields(self, session_id: UUID, fields: Dict[str, Any]) -> Dict:
        """Save confirmed profile fields (maps to save_volunteer_fields MCP tool)."""
        return await _call_mcp_tool("save_volunteer_fields", {
            "session_id": str(session_id),
            "fields": fields,
        })

    async def advance_state(
        self,
        session_id: UUID,
        new_state: str,
        sub_state: str = None
    ) -> Dict:
        """Advance session state."""
        args: Dict[str, Any] = {
            "session_id": str(session_id),
            "new_state": new_state,
        }
        if sub_state:
            args["sub_state"] = sub_state
        return await _call_mcp_tool("advance_session_state", args)

    async def save_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        agent: str = None
    ) -> Dict:
        """Save conversation message."""
        args: Dict[str, Any] = {
            "session_id": str(session_id),
            "role": role,
            "content": content,
        }
        if agent:
            args["agent"] = agent
        return await _call_mcp_tool("save_message", args)

    async def log_event(
        self,
        session_id: UUID,
        event_type: str,
        agent: str = None,
        data: Dict = None
    ) -> Dict:
        """Log telemetry event."""
        args: Dict[str, Any] = {
            "session_id": str(session_id),
            "event_type": event_type,
        }
        if agent:
            args["agent"] = agent
        if data:
            args["data"] = data
        return await _call_mcp_tool("log_event", args)

    async def emit_handoff_event(
        self,
        session_id: UUID,
        from_agent: str,
        to_agent: str,
        handoff_type: str,
        payload: Dict = None,
        reason: str = None
    ) -> Dict:
        """Emit handoff event."""
        args: Dict[str, Any] = {
            "session_id": str(session_id),
            "from_agent": from_agent,
            "to_agent": to_agent,
            "handoff_type": handoff_type,
            "payload": payload or {},
        }
        if reason:
            args["reason"] = reason
        return await _call_mcp_tool("emit_handoff_event", args)

    async def save_memory_summary(
        self,
        session_id: UUID,
        summary_text: str,
        key_facts: List[str] = None
    ) -> Dict[str, Any]:
        """Save a memory summary for the session."""
        return await _call_mcp_tool("save_memory_summary", {
            "session_id": str(session_id),
            "summary_text": summary_text,
            "key_facts": key_facts or [],
        })

    async def get_memory_summary(self, session_id: UUID) -> Dict[str, Any]:
        """Get memory summary for a session."""
        return await _call_mcp_tool("get_memory_summary", {
            "session_id": str(session_id)
        })


# Singleton instance
domain_client = DomainClient()
