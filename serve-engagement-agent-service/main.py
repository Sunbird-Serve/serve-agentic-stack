"""
SERVE Engagement Agent Service
FastAPI service for re-engaging returning volunteers.

Port: 8006
Workflow: returning_volunteer, volunteer_engagement
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import logging

from app.schemas.engagement_schemas import EngagementAgentTurnRequest, EngagementAgentTurnResponse
from app.service.engagement_logic import engagement_agent_service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SERVE Engagement Agent Service...")
    yield
    logger.info("Shutting down SERVE Engagement Agent Service...")


app = FastAPI(
    title="SERVE Engagement Agent Service",
    description="Re-engagement agent for returning volunteers",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/turn", response_model=EngagementAgentTurnResponse)
async def process_turn(request: EngagementAgentTurnRequest):
    """Process a conversation turn for volunteer re-engagement."""
    try:
        return await engagement_agent_service.process_turn(request)
    except Exception as e:
        logger.error(f"Error processing engagement turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    return {
        "service": "serve-engagement-agent-service",
        "status": "healthy",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8006))
    uvicorn.run(app, host="0.0.0.0", port=port)
