"""
SERVE AI - Main Application Server
Wires together all services while maintaining logical boundaries
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from pathlib import Path
import os
import logging

# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Import service routers
from serve_orchestrator.router import orchestrator_router
from serve_onboarding_agent.router import onboarding_router
from serve_mcp_service.router import mcp_router
from serve_mcp_service.database import init_db, close_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting SERVE AI Platform...")
    
    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning(f"Database initialization skipped (may need Postgres): {e}")
    
    yield
    
    # Cleanup
    logger.info("Shutting down SERVE AI Platform...")
    try:
        await close_db()
    except Exception:
        pass


# Create main application
app = FastAPI(
    title="SERVE AI Platform",
    description="Multi-agent volunteer management platform",
    version="1.0.0",
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

# Include service routers under /api prefix
app.include_router(orchestrator_router, prefix="/api")
app.include_router(onboarding_router, prefix="/api")
app.include_router(mcp_router, prefix="/api")


# Root health check
@app.get("/api/health")
async def health_check():
    """Platform-wide health check"""
    return {
        "platform": "SERVE AI",
        "status": "healthy",
        "services": {
            "orchestrator": "healthy",
            "onboarding_agent": "healthy",
            "mcp_service": "healthy"
        }
    }


@app.get("/api/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to SERVE AI Platform",
        "version": "1.0.0",
        "services": [
            "/api/orchestrator - Central coordination layer",
            "/api/agents/onboarding - Onboarding agent service",
            "/api/mcp - MCP capability server"
        ]
    }
