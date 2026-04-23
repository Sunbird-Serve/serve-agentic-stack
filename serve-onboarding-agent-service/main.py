"""
SERVE Onboarding Agent Service - Main Entry Point
Autonomous agent for volunteer onboarding
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
import logging
from datetime import datetime
from pathlib import Path

from app.api import agent_router
from app.schemas import HealthResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Create FastAPI application
app = FastAPI(
    title="SERVE Onboarding Agent Service",
    description="Autonomous agent for volunteer onboarding",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(agent_router, prefix="/api")

# Serve media files (orientation videos)
_media_dir = Path(__file__).parent / "media"
if _media_dir.is_dir():
    app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")
    logger.info(f"Serving media files from {_media_dir}")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        service="serve-onboarding-agent-service",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )


@app.get("/api/")
async def root():
    """Root endpoint"""
    return {
        "service": "SERVE Onboarding Agent Service",
        "version": "1.0.0",
        "description": "Autonomous agent for volunteer onboarding",
        "endpoints": [
            "/api/turn - Process agent turn",
            "/api/health - Health check"
        ]
    }


@app.on_event("startup")
async def startup_event():
    logger.info("Starting SERVE Onboarding Agent Service...")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down SERVE Onboarding Agent Service...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8002)),
        reload=True
    )
