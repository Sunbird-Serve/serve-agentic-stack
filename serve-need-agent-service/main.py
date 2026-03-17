"""
SERVE Need Agent Service
FastAPI service for need coordination with eVidyaloka schools.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import logging

from app.schemas.need_schemas import NeedAgentTurnRequest, NeedAgentTurnResponse
from app.service.need_logic import need_agent_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SERVE Need Agent Service...")
    yield
    logger.info("Shutting down SERVE Need Agent Service...")


app = FastAPI(
    title="SERVE Need Agent Service",
    description="Need coordination agent for eVidyaloka schools",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/turn", response_model=NeedAgentTurnResponse)
async def process_turn(request: NeedAgentTurnRequest):
    """Process a conversation turn for need coordination."""
    try:
        return await need_agent_service.process_turn(request)
    except Exception as e:
        logger.error(f"Error processing need turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "service": "serve-need-agent-service",
        "status": "healthy",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8005))
    uvicorn.run(app, host="0.0.0.0", port=port)
