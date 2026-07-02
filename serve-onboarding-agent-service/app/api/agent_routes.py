"""
SERVE Onboarding Agent Service - API Routes
HTTP endpoints for the onboarding agent
"""
from fastapi import APIRouter, Depends
from typing import Optional
from datetime import datetime

from app.schemas import AgentTurnRequest, AgentTurnResponse, HealthResponse
from app.service import onboarding_agent_service
from app.auth import get_optional_user, UserClaims

router = APIRouter(tags=["Onboarding Agent"])


@router.post("/turn", response_model=AgentTurnResponse)
async def process_turn(request: AgentTurnRequest, user: Optional[UserClaims] = Depends(get_optional_user)):
    """
    Process a single conversation turn for onboarding.
    Core agent logic for the onboarding workflow. Requires JWT.
    """
    return await onboarding_agent_service.process_turn(request)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        service="serve-onboarding-agent-service",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )
