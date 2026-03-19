"""
SERVE AI - MCP Server
Model Context Protocol server exposing volunteer management and need coordination
tools to any MCP-compatible LLM client (Claude, Cursor, etc.).

External data sources:
  Serve Volunteering Service → user identity, volunteer profiles
  Serve Need Service         → entities (schools), needs

MCP DB (this server owns):
  sessions, volunteer_profiles (cache), conversation_messages,
  memory_summaries, telemetry_events, actor_registry_cache,
  identity_resolution_log, agent_handoff_log, need_drafts
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Import config and services ─────────────────────────────────────────────────
from config import MCP_PORT, MCP_HOST

from services.session_service     import SessionService
from services.profile_service     import ProfileService
from services.memory_service      import MemoryService
from services.coordinator_service import coordinator_service
from services.school_service      import school_service
from services.need_service        import need_service
from services.identity_service    import identity_service
from services.serve_registry_client import volunteering_client

session_service = SessionService()
profile_service = ProfileService()
memory_service  = MemoryService()


# ── Server lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(server: FastMCP):
    from services.database import init_db, check_db_health
    try:
        await init_db()
        await check_db_health()
        logger.info("MCP Server ready — DB initialised and health cached")
    except Exception as e:
        logger.warning(f"DB init failed (in-memory fallback active): {e}")
    yield


mcp = FastMCP(
    name="SERVE AI MCP Server",
    instructions=(
        "MCP server for eVidyaloka volunteer onboarding and need coordination. "
        "Use lookup_actor at the start of every session to identify the user before "
        "calling any workflow tools."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
    lifespan=_lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# IDENTITY TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def lookup_actor(
    actor_id: str,
    channel: str,
    identity_type: Optional[str] = None,
    session_id: Optional[str] = None,
) -> dict:
    """
    Resolve who this actor is across all systems (Serve Registry + MCP history).
    MUST be called at session start before any workflow tool.

    Args:
        actor_id:      Channel-native identity (email, phone number, temp session id)
        channel:       whatsapp | web_ui | api | mobile | scheduler
        identity_type: email | phone | session_id | system (inferred if omitted)
        session_id:    MCP session UUID if already created (for log linking)

    Returns:
        user_type:          S1=new_user | S2=registry_known | S3=returning_ai_user
                            | S4=coordinator | S5=anonymous
        actor_type:         volunteer | coordinator | system
        serve_entity_id:    Serve Registry osid (null if brand new)
        has_prior_session:  bool
        last_session_id:    UUID of most recent MCP session (if any)
        profile_available:  True when Serve Registry has existing profile data
        suggested_workflow: new_volunteer_onboarding | returning_volunteer
                            | need_coordination | system_triggered
    """
    result = await identity_service.resolve(
        actor_id=actor_id,
        channel=channel,
        identity_type=identity_type,
        session_id=session_id,
    )
    return result.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# SESSION TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def start_session(
    channel: str = "web_ui",
    persona: str = "new_volunteer",
    channel_metadata: Optional[Dict[str, Any]] = None,
    actor_id: Optional[str] = None,
    identity_type: Optional[str] = None,
    user_type: Optional[str] = None,
    volunteer_id: Optional[str] = None,
    coordinator_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> dict:
    """
    Start a new conversation session.

    Args:
        channel:          web_ui | whatsapp | api | scheduler | mobile
        persona:          new_volunteer | returning_volunteer | need_coordinator
        channel_metadata: Channel-specific context {actor_id, trigger_type, …}
        actor_id:         Channel-native identity (from lookup_actor result)
        identity_type:    email | phone | session_id | system
        user_type:        From lookup_actor: new_user | registry_known | returning_ai_user
                          | coordinator | anonymous
        volunteer_id:     Serve Registry osid (from lookup_actor serve_entity_id)
        coordinator_id:   Serve Registry coordinator osid (for need_coordinator persona)
        idempotency_key:  Deduplication key (WhatsApp message_id / wamid)

    Returns:
        session_id, stage, workflow
    """
    result = await session_service.create_session(
        channel=channel,
        persona=persona,
        channel_metadata=channel_metadata,
        actor_id=actor_id,
        identity_type=identity_type,
        user_type=user_type,
        volunteer_id=volunteer_id,
        coordinator_id=coordinator_id,
        idempotency_key=idempotency_key,
    )

    # For S2/S3 users with existing Serve Registry profile → pre-populate profile cache
    session_id = result.get("session_id")
    if session_id and volunteer_id and user_type in ("registry_known", "returning_ai_user"):
        await profile_service.prefetch_from_registry(
            session_id=session_id,
            volunteer_id=volunteer_id,
        )
        result["profile_prefetched"] = True

    logger.info(f"start_session: {session_id} (persona={persona}, user_type={user_type})")
    return result


@mcp.tool()
async def get_session(session_id: str) -> dict:
    """
    Retrieve current state of a session.

    Args:
        session_id: UUID of the session

    Returns:
        Full session object including user_type, volunteer_id, stage, status
    """
    return await session_service.get_session(session_id)


@mcp.tool()
async def resume_session(session_id: str) -> dict:
    """
    Resume an existing session with full context (session state + conversation history).

    Args:
        session_id: UUID of the session to resume

    Returns:
        session, conversation_history (last 10 messages), memory_summary
    """
    result = await session_service.resume_context(session_id)

    # Enrich with memory summary
    memory = await memory_service.get_summary(session_id)
    result["memory_summary"] = memory.get("data")

    logger.info(f"resume_session: {session_id[:8]}…")
    return result


@mcp.tool()
async def advance_session_state(
    session_id: str,
    new_state: str,
    sub_state: Optional[str] = None,
    active_agent: Optional[str] = None,
) -> dict:
    """
    Advance a session to a new workflow stage.

    Args:
        session_id:   UUID of the session
        new_state:    Target stage (e.g. intent_discovery, onboarding_complete)
        sub_state:    Optional finer-grained sub-state
        active_agent: Updated owning agent after a handoff

    Returns:
        previous_state, current_state, active_agent, is_valid

    Side-effect:
        When new_state = "onboarding_complete", the volunteer profile is
        automatically synced back to Serve Registry.
    """
    result = await session_service.advance_state(
        session_id=session_id,
        new_state=new_state,
        sub_state=sub_state,
        active_agent=active_agent,
    )

    # Write-back to Serve Registry on onboarding completion
    if new_state == "onboarding_complete":
        session_result = await session_service.get_session(session_id)
        volunteer_id   = session_result.get("session", {}).get("volunteer_id")

        if not volunteer_id:
            # New user — create volunteer stub in Serve Registry first
            profile_result = await profile_service.get_profile(session_id)
            profile        = profile_result.get("profile", {})
            new_vid = await volunteering_client.create_volunteer(
                full_name=profile.get("full_name", ""),
                email=profile.get("email"),
                phone=profile.get("phone"),
                city=profile.get("location"),
            )
            if new_vid:
                volunteer_id = new_vid
                # Update session with the new volunteer_id
                from services.database import get_db, Session as DBSession
                from sqlalchemy import update
                from uuid import UUID
                if __import__("services.database", fromlist=["is_db_healthy"]).is_db_healthy():
                    try:
                        async with get_db() as db:
                            await db.execute(
                                update(DBSession)
                                .where(DBSession.id == UUID(session_id))
                                .values(volunteer_id=volunteer_id)
                            )
                    except Exception as e:
                        logger.warning(f"Could not update volunteer_id on session: {e}")

        if volunteer_id:
            sync_result = await profile_service.sync_to_registry(
                session_id=session_id,
                volunteer_id=volunteer_id,
            )
            result["registry_sync"] = sync_result
            logger.info(f"Profile synced to Serve Registry: {volunteer_id}")

    return result


@mcp.tool()
async def list_sessions(
    status: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """
    List sessions, optionally filtered by status.

    Args:
        status: active | paused | completed | abandoned (omit for all)
        limit:  Max sessions to return (default 50)
    """
    return await session_service.list_sessions(status=status, limit=limit)


# ─────────────────────────────────────────────────────────────────────────────
# PROFILE TOOLS (reads/writes MCP DB working copy)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_missing_fields(session_id: str) -> dict:
    """
    Get fields still needed from the volunteer.
    Reads from MCP DB profile cache (fast, no API call).

    Returns:
        missing_fields, confirmed_fields, completion_percentage
    """
    return await profile_service.get_missing_fields(session_id)


@mcp.tool()
async def save_volunteer_fields(
    session_id: str,
    fields: Dict[str, Any],
) -> dict:
    """
    Save confirmed volunteer profile fields to MCP DB working copy.
    Does NOT call Serve Registry — that happens automatically at onboarding_complete.

    Args:
        session_id: UUID of the session
        fields:     Dict of field names → values
                    Supported: full_name, first_name, gender, dob, email, phone,
                    location, skills (list), skill_levels (dict), interests (list),
                    languages (list), availability, days_preferred (list),
                    time_preferred (list), qualification, years_of_experience,
                    employment_status, motivation, experience_level

    Returns:
        saved_fields list
    """
    return await profile_service.save_fields(session_id=session_id, fields=fields)


@mcp.tool()
async def get_volunteer_profile(session_id: str) -> dict:
    """
    Get the complete volunteer profile from MCP DB cache.

    Returns:
        Full profile dict including Serve Registry source info
    """
    return await profile_service.get_profile(session_id)


@mcp.tool()
async def evaluate_readiness(session_id: str) -> dict:
    """
    Evaluate if a volunteer is ready for the selection phase.

    Returns:
        ready_for_selection (bool), missing_fields, recommendation, reason
    """
    return await profile_service.evaluate_readiness(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def save_message(
    session_id: str,
    role: str,
    content: str,
    agent: Optional[str] = None,
    message_metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Save a conversation message to MCP DB.

    Args:
        session_id:       UUID of the session
        role:             user | assistant
        content:          Message text
        agent:            Agent identifier (onboarding, need, selection…)
        message_metadata: Optional {token_count, latency_ms, model}
    """
    return await session_service.save_message(
        session_id=session_id,
        role=role,
        content=content,
        agent=agent,
        message_metadata=message_metadata,
    )


@mcp.tool()
async def get_conversation(
    session_id: str,
    limit: int = 50,
) -> dict:
    """
    Get conversation history for a session.

    Args:
        session_id: UUID of the session
        limit:      Max messages to return (default 50)
    """
    return await session_service.get_conversation(session_id=session_id, limit=limit)


# ─────────────────────────────────────────────────────────────────────────────
# MEMORY TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def save_memory_summary(
    session_id: str,
    summary_text: str,
    key_facts: Optional[List[str]] = None,
    volunteer_id: Optional[str] = None,
) -> dict:
    """
    Save a compressed conversation memory summary (persisted to DB).

    Args:
        session_id:   UUID of the session
        summary_text: Summarised conversation context
        key_facts:    List of extracted key facts about the volunteer
        volunteer_id: Serve Registry osid (if known)

    Returns:
        summary_id, version, key_facts_count
    """
    return await memory_service.save_summary(
        session_id=session_id,
        summary_text=summary_text,
        key_facts=key_facts or [],
        volunteer_id=volunteer_id,
    )


@mcp.tool()
async def get_memory_summary(session_id: str) -> dict:
    """
    Retrieve the latest memory summary for a session (from DB).

    Returns:
        data: {summary_id, summary_text, key_facts, version, created_at}
              or null if no summary exists
    """
    return await memory_service.get_summary(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# TELEMETRY TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def log_event(
    session_id: str,
    event_type: str,
    agent: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    domain: Optional[str] = None,
    source_service: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> dict:
    """
    Log a telemetry/audit event (persisted to DB).

    Args:
        session_id:     UUID of the session
        event_type:     state_transition | agent_response | mcp_call | error | …
        agent:          Agent identifier
        data:           Event payload
        domain:         volunteer | need | system
        source_service: orchestrator | onboarding_agent | need_agent
        duration_ms:    Operation duration for performance tracking
    """
    return await session_service.log_event(
        session_id=session_id,
        event_type=event_type,
        agent=agent,
        data=data or {},
        domain=domain,
        source_service=source_service,
        duration_ms=duration_ms,
    )


@mcp.tool()
async def emit_handoff_event(
    session_id: str,
    from_agent: str,
    to_agent: str,
    handoff_type: str,
    payload: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Record an agent handoff in the dedicated agent_handoff_log table.

    Args:
        session_id:   UUID of the session
        from_agent:   Source agent (onboarding, need, …)
        to_agent:     Target agent
        handoff_type: agent_transition | resume | escalation | pause
        payload:      Handoff context data
        reason:       Human-readable reason
    """
    return await session_service.emit_handoff_event(
        session_id=session_id,
        from_agent=from_agent,
        to_agent=to_agent,
        handoff_type=handoff_type,
        payload=payload,
        reason=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# NEED COORDINATION TOOLS — Coordinator (delegates to Serve Registry)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def resolve_coordinator_identity(
    whatsapp_number: Optional[str] = None,
    email: Optional[str] = None,
    name: Optional[str] = None,
) -> dict:
    """
    Resolve coordinator identity from Serve Registry.
    Provide email for reliable lookup. WhatsApp-only resolution requires email
    to be collected first.

    Args:
        whatsapp_number: WhatsApp contact number
        email:           Email address (preferred for lookup)
        name:            Name hint for disambiguation

    Returns:
        status: linked | unlinked | ambiguous
        coordinator: Serve Registry coordinator data if found
        linked_schools: List of linked entity IDs
    """
    return await coordinator_service.resolve_identity(
        whatsapp_number=whatsapp_number,
        email=email,
        name=name,
    )


@mcp.tool()
async def create_coordinator(
    name: str,
    whatsapp_number: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """
    Register a new coordinator in Serve Registry.

    Args:
        name:            Full name of the coordinator
        whatsapp_number: WhatsApp contact number
        email:           Email address

    Returns:
        Created coordinator profile with Serve Registry ID
    """
    return await coordinator_service.create_coordinator(
        name=name,
        whatsapp_number=whatsapp_number,
        email=email,
    )


@mcp.tool()
async def map_coordinator_to_school(
    coordinator_id: str,
    school_id: str,
) -> dict:
    """
    Link a coordinator to a school (entity) in Serve Need Service.

    Args:
        coordinator_id: Serve Registry coordinator osid
        school_id:      Serve Need Service entity UUID
    """
    return await school_service.link_coordinator(
        school_id=school_id,
        coordinator_id=coordinator_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# NEED COORDINATION TOOLS — School / Entity (delegates to Serve Need Service)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def resolve_school_context(
    coordinator_id: Optional[str] = None,
    school_hint: Optional[str] = None,
) -> dict:
    """
    Resolve school context from Serve Need Service.

    Args:
        coordinator_id: Serve Registry coordinator osid (fetches linked entities)
        school_hint:    School name / partial name for search

    Returns:
        status: existing | new | ambiguous | multiple
        school: Entity data if found
        previous_needs: List of past needs for this school
    """
    return await school_service.resolve_context(
        coordinator_id=coordinator_id,
        school_hint=school_hint,
    )


@mcp.tool()
async def create_school_context(
    name: str,
    location: str,
    contact_number: Optional[str] = None,
    coordinator_id: Optional[str] = None,
    district: Optional[str] = None,
    state: Optional[str] = None,
) -> dict:
    """
    Create a new school (entity) in Serve Need Service.

    Args:
        name:            School name
        location:        Location description (village/town/district)
        contact_number:  Contact phone
        coordinator_id:  Coordinator to auto-link (optional)
        district:        District name
        state:           State name

    Returns:
        Created entity with Serve Need Service ID
    """
    return await school_service.create_school(
        name=name,
        location=location,
        contact_number=contact_number,
        coordinator_id=coordinator_id,
        district=district,
        state=state,
    )


@mcp.tool()
async def fetch_previous_need_context(school_id: str) -> dict:
    """
    Fetch school details and previous needs from Serve Need Service.

    Args:
        school_id: Serve Need Service entity UUID

    Returns:
        school, previous_needs (list), needs_count
    """
    return await school_service.fetch_previous_needs(school_id)


# ─────────────────────────────────────────────────────────────────────────────
# NEED COORDINATION TOOLS — Need Lifecycle (MCP DB draft → Serve Need Service)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def start_need_session(
    channel: str = "web_ui",
    whatsapp_number: Optional[str] = None,
    channel_metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Start a new need coordination session (wrapper — prefer start_session directly).
    """
    return await need_service.start_session(
        channel=channel,
        whatsapp_number=whatsapp_number,
        channel_metadata=channel_metadata,
    )


@mcp.tool()
async def resume_need_context(session_id: str) -> dict:
    """Resume a need session with its current draft."""
    return await need_service.resume_context(session_id)


@mcp.tool()
async def advance_need_state(
    session_id: str,
    new_state: str,
    sub_state: Optional[str] = None,
) -> dict:
    """Advance a need session to a new workflow state."""
    return await need_service.advance_state(
        session_id=session_id,
        new_state=new_state,
        sub_state=sub_state,
    )


@mcp.tool()
async def create_or_update_need_draft(
    session_id: str,
    subjects: Optional[List[str]] = None,
    grade_levels: Optional[List[str]] = None,
    student_count: Optional[int] = None,
    time_slots: Optional[List[Any]] = None,
    start_date: Optional[str] = None,
    duration_weeks: Optional[int] = None,
    schedule_preference: Optional[str] = None,
    special_requirements: Optional[str] = None,
    coordinator_osid: Optional[str] = None,
    entity_id: Optional[str] = None,
) -> dict:
    """
    Create or update the working need draft (stored in MCP DB).
    The draft is only pushed to Serve Need Service when submit_need_for_approval is called.

    Args:
        session_id:           UUID of the need session
        subjects:             List of subject names (mathematics, science, english…)
        grade_levels:         List of grades ("1"-"12")
        student_count:        Number of students
        time_slots:           [{day, startTime, endTime}] or simple string list
        start_date:           ISO date string
        duration_weeks:       Number of weeks
        schedule_preference:  Schedule description / frequency
        special_requirements: Any special notes
        coordinator_osid:     Serve Registry coordinator osid (set when resolved)
        entity_id:            Serve Need Service entity UUID (set when school resolved)
    """
    need_data: Dict[str, Any] = {}
    if subjects           is not None: need_data["subjects"]             = subjects
    if grade_levels       is not None: need_data["grade_levels"]         = grade_levels
    if student_count      is not None: need_data["student_count"]        = student_count
    if time_slots         is not None: need_data["time_slots"]           = time_slots
    if start_date         is not None: need_data["start_date"]           = start_date
    if duration_weeks     is not None: need_data["duration_weeks"]       = duration_weeks
    if schedule_preference is not None: need_data["schedule_preference"] = schedule_preference
    if special_requirements is not None: need_data["special_requirements"] = special_requirements
    if coordinator_osid   is not None: need_data["coordinator_osid"]     = coordinator_osid
    if entity_id          is not None: need_data["entity_id"]            = entity_id

    return await need_service.save_need_draft(
        session_id=session_id,
        need_data=need_data,
    )


@mcp.tool()
async def get_missing_need_fields(session_id: str) -> dict:
    """
    Get mandatory need fields still missing from the draft.

    Returns:
        missing_fields, confirmed_fields, completion_percentage
    """
    return await need_service.get_missing_fields(session_id)


@mcp.tool()
async def evaluate_need_submission_readiness(session_id: str) -> dict:
    """
    Evaluate whether the need draft is ready for submission.

    Returns:
        is_ready (bool), missing_fields, warnings, completion_percentage, recommendation
    """
    return await need_service.evaluate_readiness(session_id)


@mcp.tool()
async def submit_need_for_approval(need_id: str) -> dict:
    """
    Submit the completed need draft to Serve Need Service (POST /need/raise).
    The draft must have coordinator_osid and entity_id set.

    Args:
        need_id: MCP DB draft UUID (from create_or_update_need_draft response)

    Returns:
        serve_need_id (Serve Need Service UUID), status, need details
    """
    return await need_service.submit_for_approval(need_id)


@mcp.tool()
async def update_need_status(
    need_id: str,
    status: str,
    comments: Optional[str] = None,
) -> dict:
    """
    Update the status of a need in both MCP DB and Serve Need Service.

    Args:
        need_id:  MCP DB draft UUID
        status:   draft | pending_approval | approved | refinement_required
                  | paused | rejected | submitted
        comments: Admin/reviewer comments
    """
    return await need_service.update_status(
        need_id=need_id,
        status=status,
        comments=comments,
    )


@mcp.tool()
async def prepare_fulfillment_handoff(need_id: str) -> dict:
    """
    Prepare a handoff payload for the fulfillment agent.
    Assembles need details + school + coordinator from Serve Need Service.

    Args:
        need_id: MCP DB draft UUID

    Returns:
        Complete handoff payload: need_details, school, coordinator_osid, approval_status
    """
    return await need_service.prepare_fulfillment_handoff(need_id)


@mcp.tool()
async def pause_need_session(
    session_id: str,
    reason: Optional[str] = None,
) -> dict:
    """Pause a need session for later resumption."""
    return await need_service.pause_session(session_id=session_id, reason=reason)


@mcp.tool()
async def save_need_message(
    session_id: str,
    role: str,
    content: str,
    agent: Optional[str] = None,
) -> dict:
    """Save a conversation message in a need session."""
    return await need_service.save_message(
        session_id=session_id, role=role, content=content, agent=agent
    )


@mcp.tool()
async def log_need_event(
    session_id: str,
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
) -> dict:
    """Log a need lifecycle audit event."""
    return await need_service.log_event(
        session_id=session_id, event_type=event_type, data=data
    )


@mcp.tool()
async def emit_need_handoff_event(
    session_id: str,
    from_agent: str,
    to_agent: str,
    payload: Dict[str, Any],
) -> dict:
    """Emit a handoff event in the need workflow."""
    return await need_service.emit_handoff_event(
        session_id=session_id,
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload,
    )


# ─────────────────────────────────────────────────────────────────────────────
# OBSERVABILITY TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_server_health() -> dict:
    """
    Get MCP server health status including DB and Serve Registry connectivity.
    """
    from services.database import is_db_healthy, check_db_health
    import httpx
    from config import VOLUNTEERING_SERVICE_URL

    db_ok = await check_db_health()

    # Quick check on Serve Registry
    registry_ok = False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{VOLUNTEERING_SERVICE_URL}/user/status",
                                  params={"status": "ACTIVE"})
            registry_ok = r.status_code < 500
    except Exception:
        registry_ok = False

    return {
        "status":           "healthy" if db_ok else "degraded",
        "db_healthy":       db_ok,
        "registry_reachable": registry_ok,
        "mcp_port":         MCP_PORT,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    transport = "sse" if "--http" in sys.argv else "stdio"
    logger.info(f"Starting SERVE AI MCP Server (transport={transport}, port={MCP_PORT})")
    mcp.run(transport=transport)
