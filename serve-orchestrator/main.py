"""
SERVE Orchestrator Service - Main Entry Point
Central coordination layer for SERVE AI
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
import os
import logging
import httpx
from datetime import datetime

from app.api import orchestrator_router
from app.schemas import HealthResponse

MCP_SERVICE_URL = os.environ.get("MCP_SERVICE_URL", "http://serve-agentic-mcp-service:8003")

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
app.include_router(orchestrator_router, prefix="/api/orchestrator")


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        service="serve-orchestrator",
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow()
    )


@app.api_route("/api/mcp/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def mcp_proxy(path: str, request: Request):
    """Proxy all /api/mcp/* requests to the MCP service"""
    target_url = f"{MCP_SERVICE_URL}/api/{path}"
    params = dict(request.query_params)
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length")
    }
    async with httpx.AsyncClient() as client:
        proxy_response = await client.request(
            method=request.method,
            url=target_url,
            params=params,
            content=body,
            headers=headers,
            timeout=30.0
        )
    return Response(
        content=proxy_response.content,
        status_code=proxy_response.status_code,
        headers=dict(proxy_response.headers),
        media_type=proxy_response.headers.get("content-type")
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
