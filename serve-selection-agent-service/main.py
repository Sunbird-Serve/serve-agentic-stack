"""
SERVE Selection Agent Service

Post-onboarding evaluation agent.
Supports the standard orchestrator turn contract and keeps `/api/evaluate`
for direct internal evaluation/debugging.
"""
import logging
import os
from datetime import datetime

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from app.schemas.selection_schemas import (
    AgentTurnRequest,
    AgentTurnResponse,
    SelectionEvaluateRequest,
    SelectionEvaluateResponse,
)
from app.service.selection_logic import selection_agent_service
from app.auth import get_optional_user, UserClaims

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SERVE Selection Agent", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/turn", response_model=AgentTurnResponse)
async def process_turn(request: AgentTurnRequest, user: UserClaims = Depends(get_optional_user)):
    """Process the orchestrator handoff / follow-up turn for selection. Requires JWT."""
    logger.info("Selection turn request for session %s (user: %s)", request.session_id, user.sub if user else "internal")
    return await selection_agent_service.process_turn(request)


@app.post("/api/evaluate", response_model=SelectionEvaluateResponse)
async def evaluate(request: SelectionEvaluateRequest, user: UserClaims = Depends(get_optional_user)):
    """Run the underlying profile evaluation directly. Requires JWT."""
    logger.info("Direct selection evaluation request for session %s", request.session_id)
    return await selection_agent_service.evaluate(request)


@app.get("/api/health")
async def health():
    return {
        "service": "serve-selection-agent-service",
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8009")),
        reload=True,
    )
