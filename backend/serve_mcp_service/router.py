"""
SERVE AI - MCP Service Router
Main router for MCP service endpoints
"""
from fastapi import APIRouter
from datetime import datetime

from shared.contracts import HealthResponse
from .capabilities import router as onboarding_capabilities_router

# Main MCP router
mcp_router = APIRouter(prefix="/mcp", tags=["MCP Service"])

# Include capability routers
mcp_router.include_router(onboarding_capabilities_router)


@mcp_router.get("/health", response_model=HealthResponse)
async def mcp_health():
    """Health check for MCP service"""
    return HealthResponse(
        service="serve-agentic-mcp-service",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )
