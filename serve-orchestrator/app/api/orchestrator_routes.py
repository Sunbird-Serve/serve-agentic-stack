"""
SERVE Orchestrator Service - API Routes
HTTP endpoints for the orchestrator
"""
from fastapi import APIRouter, HTTPException
from uuid import UUID
from typing import Optional
from datetime import datetime

from app.schemas import InteractionRequest, InteractionResponse, HealthResponse
from app.service import orchestration_service

router = APIRouter(tags=["Orchestrator"])


@router.post("/interact", response_model=InteractionResponse)
async def process_interaction(request: InteractionRequest):
    """
    Process incoming user interaction.
    Main entry point from channel adapters.
    """
    try:
        return await orchestration_service.process_interaction(request)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Orchestrator /interact error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session(session_id: UUID):
    """Get session state"""
    result = await orchestration_service.get_session(session_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("error", "Session not found"))
    return result


@router.get("/sessions")
async def list_sessions(status: Optional[str] = None, limit: int = 50):
    """List all sessions"""
    return await orchestration_service.list_sessions(status, limit)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        service="serve-orchestrator",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )
