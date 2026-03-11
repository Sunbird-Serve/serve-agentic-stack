"""
SERVE Orchestrator Service - Main Entry Point
Central coordination layer for SERVE AI
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from datetime import datetime

from app.api import orchestrator_router
from app.schemas import HealthResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Create FastAPI application
app = FastAPI(
    title="SERVE Orchestrator Service",
    description="Central coordination layer for SERVE AI",
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
app.include_router(orchestrator_router, prefix="/api")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        service="serve-orchestrator",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )


@app.get("/api/")
async def root():
    """Root endpoint"""
    return {
        "service": "SERVE Orchestrator Service",
        "version": "1.0.0",
        "description": "Central coordination layer for SERVE AI",
        "endpoints": [
            "/api/interact - Process user interaction",
            "/api/session/{id} - Get session state",
            "/api/sessions - List all sessions",
            "/api/health - Health check"
        ]
    }


@app.on_event("startup")
async def startup_event():
    logger.info("Starting SERVE Orchestrator Service...")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down SERVE Orchestrator Service...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8001)),
        reload=True
    )
