"""
SERVE Selection Agent Service

Silent evaluation agent — no volunteer-facing conversation.
Receives volunteer profile after onboarding, evaluates, returns recommendation.

Endpoints:
  POST /api/evaluate  — run evaluation
  GET  /api/health    — health check
"""
import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from app.schemas.selection_schemas import (
    SelectionEvaluateRequest,
    SelectionEvaluateResponse,
)
from app.service.selection_logic import selection_agent_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SERVE Selection Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/evaluate", response_model=SelectionEvaluateResponse)
async def evaluate(request: SelectionEvaluateRequest):
    """Evaluate a volunteer profile and return recommendation."""
    logger.info(f"Evaluation request for session {request.session_id}")
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
