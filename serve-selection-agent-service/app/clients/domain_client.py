"""
SERVE Selection Agent Service - MCP Tool Client

Calls serve-mcp-server tools via the MCP SSE protocol.
Selection reuses the generic profile, readiness, memory, and telemetry tools.
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
    """Call an MCP server tool via SSE transport with retry."""
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
                await asyncio.sleep(0.5 * (2 ** attempt))

    logger.error("MCP tool [%s] failed after %s attempts: %s", tool_name, _MCP_RETRIES, last_error)
    return {"status": "error", "error": str(last_error)}


class DomainClient:
    async def get_volunteer_profile(self, session_id: str) -> Dict[str, Any]:
        return await _call_mcp_tool("get_volunteer_profile", {"session_id": session_id})

    async def evaluate_readiness(self, session_id: str) -> Dict[str, Any]:
        return await _call_mcp_tool("evaluate_readiness", {"session_id": session_id})

    async def save_confirmed_fields(self, session_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        return await _call_mcp_tool(
            "save_volunteer_fields",
            {
                "session_id": session_id,
                "fields": fields,
            },
        )

    async def advance_state(
        self,
        session_id: str,
        new_state: str,
        sub_state: Optional[str] = None,
    ) -> Dict[str, Any]:
        args: Dict[str, Any] = {"session_id": session_id, "new_state": new_state}
        if sub_state is not None:
            args["sub_state"] = sub_state
        return await _call_mcp_tool("advance_session_state", args)

    async def get_memory_summary(self, session_id: str) -> Dict[str, Any]:
        return await _call_mcp_tool("get_memory_summary", {"session_id": session_id})

    async def save_memory_summary(
        self,
        session_id: str,
        summary_text: str,
        key_facts: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        return await _call_mcp_tool(
            "save_memory_summary",
            {
                "session_id": session_id,
                "summary_text": summary_text,
                "key_facts": key_facts or [],
            },
        )

    async def log_event(
        self,
        session_id: str,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await _call_mcp_tool(
            "log_event",
            {
                "session_id": session_id,
                "event_type": event_type,
                "agent": "selection",
                "data": data or {},
            },
        )


domain_client = DomainClient()
