"""
SERVE Fulfillment Agent Service
FastAPI service for volunteer-to-need matching (L4 autonomy).

Port: 8007
Workflow: returning_volunteer
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import logging

from app.schemas.fulfillment_schemas import FulfillmentAgentTurnRequest, FulfillmentAgentTurnResponse
from app.service.fulfillment_logic import fulfillment_agent_service

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SERVE Fulfillment Agent Service...")
    yield
    logger.info("Shutting down SERVE Fulfillment Agent Service...")


app = FastAPI(
    title="SERVE Fulfillment Agent Service",
    description="L4 volunteer-to-need matching agent",
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


@app.post("/api/turn", response_model=FulfillmentAgentTurnResponse)
async def process_turn(request: FulfillmentAgentTurnRequest):
    """Process a conversation turn for volunteer fulfillment matching."""
    try:
        return await fulfillment_agent_service.process_turn(request)
    except Exception as e:
        logger.error(f"Error processing fulfillment turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    return {
        "service": "serve-fulfillment-agent-service",
        "status": "healthy",
        "version": "1.0.0",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8007))
    uvicorn.run(app, host="0.0.0.0", port=port)
