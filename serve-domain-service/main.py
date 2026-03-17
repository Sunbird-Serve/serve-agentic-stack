"""
SERVE Domain Service - Main Entry Point
Domain capability and persistence layer for SERVE AI

This service provides HTTP API access to domain capabilities.
For MCP (Model Context Protocol) access, use serve-mcp-server.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import logging
from datetime import datetime

from app.db import init_db, close_db
from app.api import onboarding_router
from app.schemas import HealthResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting SERVE Domain Service...")
    
    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    
    yield
    
    # Cleanup
    logger.info("Shutting down SERVE Domain Service...")
    await close_db()


# Create FastAPI application
app = FastAPI(
    title="SERVE Domain Service",
    description="Domain capability and persistence layer for SERVE AI",
    version="1.1.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers - keep /api/capabilities path for backward compatibility
app.include_router(onboarding_router, prefix="/api")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        service="serve-domain-service",
        status="healthy",
        version="1.1.0",
        timestamp=datetime.utcnow()
    )


@app.get("/api/")
async def root():
    """Root endpoint"""
    return {
        "service": "SERVE Domain Service",
        "version": "1.1.0",
        "description": "Domain capability and persistence layer (HTTP API)",
        "note": "For MCP protocol access, use serve-mcp-server",
        "endpoints": [
            "/api/capabilities/onboarding/* - Onboarding domain capabilities",
            "/api/health - Health check"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8003)),
        reload=True
    )
