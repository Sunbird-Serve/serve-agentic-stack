"""
SERVE Orchestrator Service - MCP Tool Client
Calls serve-mcp-server tools via the MCP SSE protocol.

This replaces the former REST-based DomainClient. The public interface is
identical so orchestration.py requires no changes.

Response adaptation: MCP tools return flat dicts; the orchestrator expects
{"status": "success", "data": {...}}, so we wrap results here.
"""
import os
import json
import logging
from typing import Dict, Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://serve-mcp-server:8004")


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict:
    """Call an MCP server tool via the SSE transport and return its parsed result."""
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
        logger.error(f"MCP tool call failed [{tool_name}]: {e}")
        return {"status": "error", "error": str(e)}


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
        """Start a new session via MCP."""
        result = await _call_mcp_tool("start_session", {
            "channel": channel,
            "persona": persona,
        })
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
        sub_state: str = None
    ) -> Dict:
        """Advance session state via MCP."""
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
