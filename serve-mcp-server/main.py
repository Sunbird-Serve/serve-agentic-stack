"""
SERVE AI - Real MCP Server
Model Context Protocol compliant server using the official Python MCP SDK.

This server exposes volunteer management capabilities as MCP tools that can be
called by any MCP-compatible LLM client (Claude, Cursor, etc.).

Tools exposed:
- Onboarding: start_session, get_session, resume_session, advance_session_state, etc.
- Profile: get_missing_fields, save_volunteer_fields, get_volunteer_profile, evaluate_readiness
- Memory: save_memory_summary, get_memory_summary
- Need Coordination: resolve_coordinator_identity, resolve_school_context, create_need_draft, etc.
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

# Import business services - Onboarding
from services.session_service import SessionService
from services.profile_service import ProfileService
from services.memory_service import MemoryService

# Import business services - Need Coordination
from services.coordinator_service import coordinator_service
from services.school_service import school_service
from services.need_service import need_service

# Initialize onboarding services
session_service = SessionService()
profile_service = ProfileService()
memory_service = MemoryService()

# Create FastMCP server
mcp = FastMCP(
    name="SERVE AI MCP Server",
    instructions="Model Context Protocol server for eVidyaloka volunteer and need management. Use these tools to manage volunteer onboarding, need coordination, school contexts, and conversation memory."
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


# ============ Need Coordination Tools ============

@mcp.tool()
async def resolve_coordinator_identity(
    whatsapp_number: str,
    name: Optional[str] = None
) -> dict:
    """
    Resolve coordinator identity from WhatsApp number or name.
    
    Args:
        whatsapp_number: The WhatsApp number of the coordinator
        name: Optional name hint for resolution
    
    Returns:
        Dictionary with status (linked/unlinked/ambiguous), coordinator data if found, linked schools
    """
    result = await coordinator_service.resolve_identity(
        whatsapp_number=whatsapp_number,
        name=name
    )
    logger.info(f"MCP Tool: resolve_coordinator_identity -> {result.get('status')}")
    return result


@mcp.tool()
async def create_coordinator(
    name: str,
    whatsapp_number: str,
    email: Optional[str] = None
) -> dict:
    """
    Create a new coordinator profile.
    
    Args:
        name: Full name of the coordinator
        whatsapp_number: WhatsApp contact number
        email: Optional email address
    
    Returns:
        Created coordinator profile
    """
    result = await coordinator_service.create_coordinator(
        name=name,
        whatsapp_number=whatsapp_number,
        email=email
    )
    logger.info(f"MCP Tool: create_coordinator -> {result.get('id')}")
    return result


@mcp.tool()
async def map_coordinator_to_school(
    coordinator_id: str,
    school_id: str
) -> dict:
    """
    Map a coordinator to an existing school.
    
    Args:
        coordinator_id: ID of the coordinator
        school_id: ID of the school to link
    
    Returns:
        Mapping confirmation
    """
    result = await coordinator_service.map_to_school(
        coordinator_id=coordinator_id,
        school_id=school_id
    )
    logger.info(f"MCP Tool: map_coordinator_to_school")
    return result


@mcp.tool()
async def resolve_school_context(
    coordinator_id: Optional[str] = None,
    school_hint: Optional[str] = None
) -> dict:
    """
    Resolve school context for need coordination.
    
    Args:
        coordinator_id: ID of linked coordinator (if known)
        school_hint: School name or hint for matching
    
    Returns:
        Dictionary with status (existing/new/ambiguous), school data if found, previous needs
    """
    result = await school_service.resolve_context(
        coordinator_id=coordinator_id,
        school_hint=school_hint
    )
    logger.info(f"MCP Tool: resolve_school_context -> {result.get('status')}")
    return result


@mcp.tool()
async def create_school_context(
    name: str,
    location: str,
    contact_number: Optional[str] = None,
    coordinator_id: Optional[str] = None
) -> dict:
    """
    Create a new school context.
    
    Args:
        name: School name
        location: School location (village/town/district)
        contact_number: Optional contact phone
        coordinator_id: Optional coordinator to link
    
    Returns:
        Created school context
    """
    result = await school_service.create_school(
        name=name,
        location=location,
        contact_number=contact_number,
        coordinator_id=coordinator_id
    )
    logger.info(f"MCP Tool: create_school_context -> {result.get('id')}")
    return result


@mcp.tool()
async def fetch_previous_need_context(
    school_id: str
) -> dict:
    """
    Fetch previous need context for an existing school.
    
    Args:
        school_id: ID of the school
    
    Returns:
        School context and list of previous needs
    """
    result = await school_service.fetch_previous_needs(school_id)
    logger.info(f"MCP Tool: fetch_previous_need_context for school {school_id[:8]}...")
    return result


@mcp.tool()
async def start_need_session(
    channel: str = "web_ui",
    whatsapp_number: Optional[str] = None,
    channel_metadata: Optional[Dict[str, Any]] = None
) -> dict:
    """
    Start a new need coordination session.
    
    Args:
        channel: Channel type (web_ui, whatsapp)
        whatsapp_number: WhatsApp number if applicable
        channel_metadata: Additional channel context
    
    Returns:
        New session details
    """
    result = await need_service.start_session(
        channel=channel,
        whatsapp_number=whatsapp_number,
        channel_metadata=channel_metadata
    )
    logger.info(f"MCP Tool: start_need_session -> {result.get('session_id')}")
    return result


@mcp.tool()
async def resume_need_context(
    session_id: str
) -> dict:
    """
    Resume an existing need session with full context.
    
    Args:
        session_id: ID of the session to resume
    
    Returns:
        Full session context including coordinator, school, and draft
    """
    result = await need_service.resume_context(session_id)
    logger.info(f"MCP Tool: resume_need_context for {session_id[:8]}...")
    return result


@mcp.tool()
async def advance_need_state(
    session_id: str,
    new_state: str,
    sub_state: Optional[str] = None
) -> dict:
    """
    Advance a need session to a new state.
    
    Args:
        session_id: The session ID
        new_state: Target state (initiated, resolving_coordinator, drafting_need, etc.)
        sub_state: Optional sub-state
    
    Returns:
        State transition confirmation
    """
    result = await need_service.advance_state(
        session_id=session_id,
        new_state=new_state,
        sub_state=sub_state
    )
    logger.info(f"MCP Tool: advance_need_state -> {new_state}")
    return result


@mcp.tool()
async def create_or_update_need_draft(
    session_id: str,
    subjects: Optional[List[str]] = None,
    grade_levels: Optional[List[str]] = None,
    student_count: Optional[int] = None,
    time_slots: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    duration_weeks: Optional[int] = None,
    schedule_preference: Optional[str] = None,
    special_requirements: Optional[str] = None
) -> dict:
    """
    Create or update a need draft with captured details.
    
    Args:
        session_id: The session ID
        subjects: List of subjects needed (mathematics, science, english, etc.)
        grade_levels: List of grade levels (1-12)
        student_count: Number of students
        time_slots: Preferred time slots
        start_date: When to start (ISO format)
        duration_weeks: How many weeks of support needed
        schedule_preference: Schedule preference description
        special_requirements: Any special requirements
    
    Returns:
        Updated draft with need_id
    """
    need_data = {}
    if subjects is not None:
        need_data["subjects"] = subjects
    if grade_levels is not None:
        need_data["grade_levels"] = grade_levels
    if student_count is not None:
        need_data["student_count"] = student_count
    if time_slots is not None:
        need_data["time_slots"] = time_slots
    if start_date is not None:
        need_data["start_date"] = start_date
    if duration_weeks is not None:
        need_data["duration_weeks"] = duration_weeks
    if schedule_preference is not None:
        need_data["schedule_preference"] = schedule_preference
    if special_requirements is not None:
        need_data["special_requirements"] = special_requirements
    
    result = await need_service.save_need_draft(
        session_id=session_id,
        need_data=need_data
    )
    logger.info(f"MCP Tool: create_or_update_need_draft for {session_id[:8]}...")
    return result


@mcp.tool()
async def get_missing_need_fields(
    session_id: str
) -> dict:
    """
    Get the list of mandatory fields still missing from a need draft.
    
    Args:
        session_id: The session ID
    
    Returns:
        Dictionary with missing_fields list, confirmed_fields, and completion_percentage
    """
    result = await need_service.get_missing_fields(session_id)
    return result


@mcp.tool()
async def evaluate_need_submission_readiness(
    session_id: str
) -> dict:
    """
    Evaluate whether a need is ready for submission/approval.
    
    Args:
        session_id: The session ID
    
    Returns:
        Dictionary with is_ready boolean, missing fields, warnings, and recommendation
    """
    result = await need_service.evaluate_readiness(session_id)
    logger.info(f"MCP Tool: evaluate_need_readiness -> ready={result.get('is_ready')}")
    return result


@mcp.tool()
async def submit_need_for_approval(
    need_id: str
) -> dict:
    """
    Submit a completed need for approval (future: routes to Need Admin).
    
    Args:
        need_id: The need ID to submit
    
    Returns:
        Submission confirmation with status
    """
    result = await need_service.submit_for_approval(need_id)
    logger.info(f"MCP Tool: submit_need_for_approval -> {result.get('status')}")
    return result


@mcp.tool()
async def update_need_status(
    need_id: str,
    status: str,
    comments: Optional[str] = None
) -> dict:
    """
    Update the status of a need.
    
    Args:
        need_id: The need ID
        status: New status (draft, pending_approval, approved, refinement_required, paused, rejected)
        comments: Optional admin comments
    
    Returns:
        Update confirmation
    """
    result = await need_service.update_status(
        need_id=need_id,
        status=status,
        comments=comments
    )
    logger.info(f"MCP Tool: update_need_status -> {status}")
    return result


@mcp.tool()
async def prepare_fulfillment_handoff(
    need_id: str
) -> dict:
    """
    Prepare a handoff payload for the fulfillment agent after need approval.
    
    Args:
        need_id: The approved need ID
    
    Returns:
        Complete handoff payload with need details, school, and coordinator
    """
    result = await need_service.prepare_fulfillment_handoff(need_id)
    logger.info(f"MCP Tool: prepare_fulfillment_handoff for need {need_id[:8]}...")
    return result


@mcp.tool()
async def pause_need_session(
    session_id: str,
    reason: Optional[str] = None
) -> dict:
    """
    Pause a need session for later resumption.
    
    Args:
        session_id: The session ID
        reason: Optional reason for pausing
    
    Returns:
        Pause confirmation
    """
    result = await need_service.pause_session(
        session_id=session_id,
        reason=reason
    )
    logger.info(f"MCP Tool: pause_need_session")
    return result


@mcp.tool()
async def save_need_message(
    session_id: str,
    role: str,
    content: str,
    agent: Optional[str] = None
) -> dict:
    """
    Save a conversation message in a need session.
    
    Args:
        session_id: The session ID
        role: Message role (user or assistant)
        content: Message content
        agent: Optional agent identifier
    
    Returns:
        Message save confirmation
    """
    result = await need_service.save_message(
        session_id=session_id,
        role=role,
        content=content,
        agent=agent
    )
    return result


@mcp.tool()
async def log_need_event(
    session_id: str,
    event_type: str,
    data: Optional[Dict[str, Any]] = None
) -> dict:
    """
    Log a telemetry/audit event for a need session.
    
    Args:
        session_id: The session ID
        event_type: Type of event (coordinator_resolved, school_resolved, need_draft_updated, etc.)
        data: Optional event data
    
    Returns:
        Event logging confirmation
    """
    result = await need_service.log_event(
        session_id=session_id,
        event_type=event_type,
        data=data
    )
    return result


@mcp.tool()
async def emit_need_handoff_event(
    session_id: str,
    from_agent: str,
    to_agent: str,
    payload: Dict[str, Any]
) -> dict:
    """
    Emit a handoff event for workflow transition.
    
    Args:
        session_id: The session ID
        from_agent: Source agent (need)
        to_agent: Target agent (fulfillment)
        payload: Handoff payload data
    
    Returns:
        Handoff event confirmation
    """
    result = await need_service.emit_handoff_event(
        session_id=session_id,
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload
    )
    logger.info(f"MCP Tool: emit_need_handoff_event {from_agent} -> {to_agent}")
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
