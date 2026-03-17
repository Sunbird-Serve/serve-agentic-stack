"""
SERVE AI - Real MCP Server
Model Context Protocol compliant server using the official Python MCP SDK.

This server exposes volunteer management capabilities as MCP tools that can be
called by any MCP-compatible LLM client (Claude, Cursor, etc.).

Tools exposed:
- onboarding.start_session: Start a new volunteer onboarding session
- onboarding.get_missing_fields: Get fields still needed from volunteer
- onboarding.save_fields: Save confirmed volunteer profile fields
- onboarding.get_session: Retrieve session state
- memory.save_summary: Save conversation memory summary
- memory.get_summary: Retrieve conversation memory
"""
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID, uuid4

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import business services
from services.session_service import SessionService
from services.profile_service import ProfileService
from services.memory_service import MemoryService

# Initialize services
session_service = SessionService()
profile_service = ProfileService()
memory_service = MemoryService()

# Create FastMCP server
mcp = FastMCP(
    name="SERVE AI MCP Server",
    instructions="Model Context Protocol server for eVidyaloka volunteer management. Use these tools to manage volunteer onboarding sessions, profiles, and conversation memory."
)


# ============ Session Tools ============

@mcp.tool()
async def start_session(
    channel: str = "web_ui",
    persona: str = "new_volunteer"
) -> dict:
    """
    Start a new volunteer onboarding session.
    
    Args:
        channel: The channel through which the volunteer is interacting (web_ui, whatsapp, api)
        persona: The type of user (new_volunteer, returning_volunteer, need_coordinator)
    
    Returns:
        Dictionary containing session_id, initial stage, and status
    """
    result = await session_service.create_session(channel=channel, persona=persona)
    logger.info(f"MCP Tool: start_session created session {result.get('session_id', 'unknown')}")
    return result


@mcp.tool()
async def get_session(session_id: str) -> dict:
    """
    Retrieve the current state of a volunteer session.
    
    Args:
        session_id: The UUID of the session to retrieve
    
    Returns:
        Dictionary containing session state, stage, and volunteer profile
    """
    result = await session_service.get_session(session_id)
    return result


@mcp.tool()
async def resume_session(session_id: str) -> dict:
    """
    Resume an existing session with full context.
    
    Args:
        session_id: The UUID of the session to resume
    
    Returns:
        Dictionary containing session state, volunteer profile, conversation history, and memory summary
    """
    result = await session_service.resume_context(session_id)
    logger.info(f"MCP Tool: resume_session for {session_id[:8]}...")
    return result


@mcp.tool()
async def advance_session_state(
    session_id: str,
    new_state: str,
    sub_state: Optional[str] = None
) -> dict:
    """
    Advance a session to a new state in the onboarding workflow.
    
    Args:
        session_id: The UUID of the session
        new_state: The target state (init, intent_discovery, purpose_orientation, etc.)
        sub_state: Optional sub-state for more granular tracking
    
    Returns:
        Dictionary with previous_state, current_state, and validation result
    """
    result = await session_service.advance_state(
        session_id=session_id,
        new_state=new_state,
        sub_state=sub_state
    )
    logger.info(f"MCP Tool: advance_state {session_id[:8]}... -> {new_state}")
    return result


# ============ Profile Tools ============

@mcp.tool()
async def get_missing_fields(session_id: str) -> dict:
    """
    Get the list of fields still needed from the volunteer.
    
    Args:
        session_id: The UUID of the session
    
    Returns:
        Dictionary containing missing_fields list, confirmed_fields dict, and completion_percentage
    """
    result = await profile_service.get_missing_fields(session_id)
    return result


@mcp.tool()
async def save_volunteer_fields(
    session_id: str,
    fields: Dict[str, Any]
) -> dict:
    """
    Save confirmed volunteer profile fields.
    
    Args:
        session_id: The UUID of the session
        fields: Dictionary of field names to values (e.g., {"full_name": "Priya", "email": "priya@example.com"})
    
    Returns:
        Dictionary confirming saved fields
    """
    result = await profile_service.save_fields(session_id=session_id, fields=fields)
    logger.info(f"MCP Tool: save_fields {session_id[:8]}... fields={list(fields.keys())}")
    return result


@mcp.tool()
async def get_volunteer_profile(session_id: str) -> dict:
    """
    Get the complete volunteer profile for a session.
    
    Args:
        session_id: The UUID of the session
    
    Returns:
        Dictionary containing all confirmed volunteer information
    """
    result = await profile_service.get_profile(session_id)
    return result


# ============ Message Tools ============

@mcp.tool()
async def save_message(
    session_id: str,
    role: str,
    content: str,
    agent: Optional[str] = None
) -> dict:
    """
    Save a conversation message.
    
    Args:
        session_id: The UUID of the session
        role: The message role (user or assistant)
        content: The message content
        agent: Optional agent identifier (onboarding, selection, etc.)
    
    Returns:
        Dictionary confirming message was saved
    """
    result = await session_service.save_message(
        session_id=session_id,
        role=role,
        content=content,
        agent=agent
    )
    return result


@mcp.tool()
async def get_conversation(
    session_id: str,
    limit: int = 50
) -> dict:
    """
    Get conversation history for a session.
    
    Args:
        session_id: The UUID of the session
        limit: Maximum number of messages to return (default 50)
    
    Returns:
        Dictionary containing list of messages
    """
    result = await session_service.get_conversation(session_id=session_id, limit=limit)
    return result


# ============ Memory Tools ============

@mcp.tool()
async def save_memory_summary(
    session_id: str,
    summary_text: str,
    key_facts: Optional[List[str]] = None
) -> dict:
    """
    Save a conversation memory summary for long-term context.
    
    Args:
        session_id: The UUID of the session
        summary_text: The summarized conversation context
        key_facts: Optional list of extracted key facts about the volunteer
    
    Returns:
        Dictionary confirming summary was saved
    """
    result = await memory_service.save_summary(
        session_id=session_id,
        summary_text=summary_text,
        key_facts=key_facts or []
    )
    logger.info(f"MCP Tool: save_memory_summary {session_id[:8]}...")
    return result


@mcp.tool()
async def get_memory_summary(session_id: str) -> dict:
    """
    Retrieve memory summary for a session.
    
    Args:
        session_id: The UUID of the session
    
    Returns:
        Dictionary containing summary_text and key_facts, or null if no summary exists
    """
    result = await memory_service.get_summary(session_id)
    return result


# ============ Evaluation Tools ============

@mcp.tool()
async def evaluate_readiness(session_id: str) -> dict:
    """
    Evaluate if a volunteer is ready for the selection phase.
    
    Args:
        session_id: The UUID of the session
    
    Returns:
        Dictionary with ready_for_selection boolean, missing_fields, and recommendation
    """
    result = await profile_service.evaluate_readiness(session_id)
    return result


# ============ Telemetry Tools ============

@mcp.tool()
async def log_event(
    session_id: str,
    event_type: str,
    agent: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None
) -> dict:
    """
    Log a telemetry event for debugging and analytics.
    
    Args:
        session_id: The UUID of the session
        event_type: Type of event (state_transition, agent_response, mcp_call, etc.)
        agent: Optional agent identifier
        data: Optional event data payload
    
    Returns:
        Dictionary with event_id confirming event was logged
    """
    result = await session_service.log_event(
        session_id=session_id,
        event_type=event_type,
        agent=agent,
        data=data or {}
    )
    return result


# ============ Server Entry Point ============

if __name__ == "__main__":
    import sys
    
    # Check for transport mode
    transport = "stdio"
    if "--http" in sys.argv:
        transport = "sse"
    
    logger.info(f"Starting SERVE AI MCP Server (transport={transport})")
    mcp.run(transport=transport)
