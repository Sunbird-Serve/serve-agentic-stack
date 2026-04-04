"""
SERVE Selection Agent Service - MCP Tool Client

Calls serve-mcp-server tools via the MCP SSE protocol.
Same transport pattern as the other agent services.

TODO (contributor): Add methods as evaluation logic requires.
  e.g. get_volunteer_profile, get_onboarding_summary, log_evaluation_result, etc.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://serve-mcp-server:8004")
_MCP_RETRIES = int(os.environ.get("MCP_RETRIES", "3"))


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict:
    """Call an MCP server tool via SSE transport with retry."""
    last_error = None
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

    logger.error(f"MCP tool [{tool_name}] failed after {_MCP_RETRIES} attempts: {last_error}")
    return {"status": "error", "error": str(last_error)}
