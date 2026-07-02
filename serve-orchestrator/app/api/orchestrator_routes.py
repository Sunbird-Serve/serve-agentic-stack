"""
SERVE Orchestrator Service - API Routes
HTTP endpoints for the orchestrator
"""
from fastapi import APIRouter, HTTPException, Depends, Request as FastAPIRequest
from uuid import UUID
from typing import Optional
from datetime import datetime

from app.schemas import InteractionRequest, InteractionResponse, HealthResponse
from app.service import orchestration_service
from app.core.auth import get_current_user, require_role, UserClaims
from app.core.request_context import auth_token_var

router = APIRouter(tags=["Orchestrator"])


@router.post("/interact", response_model=InteractionResponse)
async def process_interaction(
    request: InteractionRequest,
    raw_request: FastAPIRequest,
    user: UserClaims = Depends(get_current_user),
):
    """
    Process incoming user interaction.
    Main entry point from channel adapters.
    Requires authenticated user (any role).
    """
    # Set auth token in context so downstream agent calls can forward it
    auth_token_var.set(raw_request.headers.get("Authorization", ""))

    # Inject authenticated user identity into channel_metadata so the
    # channel adapter uses the Keycloak sub as the stable actor_id.
    meta = request.channel_metadata or {}
    meta["keycloak_sub"] = user.sub
    meta["email"] = meta.get("email") or user.email or ""
    meta["preferred_username"] = user.preferred_username or ""
    request = request.model_copy(update={"channel_metadata": meta})

    try:
        return await orchestration_service.process_interaction(request)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Orchestrator /interact error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session(
    session_id: UUID,
    user: UserClaims = Depends(get_current_user),
):
    """Get session state. Authenticated user required."""
    result = await orchestration_service.get_session(session_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("error", "Session not found"))
    return result


@router.get("/my-session")
async def get_my_active_session(
    user: UserClaims = Depends(get_current_user),
):
    """
    Get the current user's most recent active/paused session.
    Used by the frontend to resume a session after page refresh.
    Returns the session or 404 if none found.
    """
    result = await orchestration_service.find_active_session_by_actor(user.sub)
    if not result:
        raise HTTPException(status_code=404, detail="No active session found")
    return result


@router.get("/sessions")
async def list_sessions(
    status: Optional[str] = None,
    limit: int = 50,
    user: UserClaims = Depends(require_role("vCoordinator", "nCoordinator", "sAdmin", "nAdmin", "vAdmin")),
):
    """List all sessions. Requires coordinator or admin role."""
    return await orchestration_service.list_sessions(status, limit)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint — no auth required."""
    return HealthResponse(
        service="serve-orchestrator",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )
