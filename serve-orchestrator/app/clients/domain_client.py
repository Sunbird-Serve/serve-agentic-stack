"""
SERVE Orchestrator Service - MCP Tool Client
Calls serve-mcp-server tools via the MCP SSE protocol.

This replaces the former REST-based DomainClient. The public interface is
identical so orchestration.py requires no changes.

Response adaptation: MCP tools return flat dicts; the orchestrator expects
{"status": "success", "data": {...}}, so we wrap results here.
"""
import asyncio
import os
import json
import logging
from typing import Dict, Any, Optional
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
    """
    last_error: Exception | None = None

    for attempt in range(_MCP_RETRIES):
        try:
            from mcp.client.session import ClientSession
            from mcp.client.sse import sse_client

            sse_url = f"{MCP_SERVER_URL}/sse"
            async with sse_client(url=sse_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments)
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

    All public methods keep the same signatures so orchestration.py is
    unchanged. Responses are wrapped in {"status": "success", "data": {...}}
    to match the format the orchestrator expects.
    """

    def __init__(self, base_url: str = None):
        pass

    # ---------- Session lifecycle ----------

    async def start_session(
        self,
        channel: str,
        persona: str,
        channel_metadata: Optional[Dict] = None
    ) -> Dict:
        """Start a new session via MCP, persisting channel_metadata (actor_id, trigger_type, …)."""
        args: Dict[str, Any] = {"channel": channel, "persona": persona}
        if channel_metadata:
            args["channel_metadata"] = channel_metadata
        result = await _call_mcp_tool("start_session", args)
        if result.get("status") != "success":
            return result
        # Wrap in the "data" envelope the orchestrator expects
        return {
            "status": "success",
            "data": {
                "session_id": result.get("session_id"),
                "stage": result.get("stage", "init"),
                "workflow": result.get("workflow"),
            }
        }

    async def resume_context(self, session_id: UUID) -> Dict:
        """Resume an existing session with full context via MCP."""
        result = await _call_mcp_tool("resume_session", {
            "session_id": str(session_id)
        })
        if result.get("status") != "success":
            return result
        return {
            "status": "success",
            "data": {
                "session": result.get("session"),
                "volunteer_profile": result.get("volunteer_profile"),
                "conversation_history": result.get("conversation_history", []),
                "memory_summary": result.get("memory_summary"),
            }
        }

    async def advance_state(
        self,
        session_id: UUID,
        new_state: str,
        sub_state: str = None,
        active_agent: Optional[str] = None,
    ) -> Dict:
        """
        Advance session state via MCP.

        active_agent — when provided, also updates the session's active_agent so the
        next turn is routed to the correct agent after a handoff.
        """
        args: Dict[str, Any] = {
            "session_id": str(session_id),
            "new_state": new_state,
        }
        if sub_state:
            args["sub_state"] = sub_state
        if active_agent:
            args["active_agent"] = active_agent
        return await _call_mcp_tool("advance_session_state", args)

    async def save_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        agent: str = None
    ) -> Dict:
        """Save a conversation message via MCP."""
        args: Dict[str, Any] = {
            "session_id": str(session_id),
            "role": role,
            "content": content,
        }
        if agent:
            args["agent"] = agent
        return await _call_mcp_tool("save_message", args)

    async def emit_handoff_event(
        self,
        session_id: UUID,
        from_agent: str,
        to_agent: str,
        handoff_type: str,
        payload: Dict = None,
        reason: str = None
    ) -> Dict:
        """Emit a handoff event via MCP."""
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

    async def get_session(self, session_id: UUID) -> Dict:
        """Get session details via MCP."""
        return await _call_mcp_tool("get_session", {
            "session_id": str(session_id)
        })

    async def list_sessions(self, status: str = None, limit: int = 50) -> Dict:
        """List all sessions via MCP."""
        args: Dict[str, Any] = {"limit": limit}
        if status:
            args["status"] = status
        return await _call_mcp_tool("list_sessions", args)


# Singleton instance
domain_client = DomainClient()
