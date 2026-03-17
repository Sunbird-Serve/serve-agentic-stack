"""
SERVE MCP Server - Services Package
Business logic services that power MCP tools

Services support both PostgreSQL (production) and in-memory (development) storage.
"""
from .session_service import SessionService
from .profile_service import ProfileService
from .memory_service import MemoryService

__all__ = ['SessionService', 'ProfileService', 'MemoryService']

# Optional database initialization
async def init_database():
    """Initialize database if available."""
    try:
        from .database import init_db, test_connection
        if await test_connection():
            await init_db()
            return True
    except Exception:
        pass
    return False

