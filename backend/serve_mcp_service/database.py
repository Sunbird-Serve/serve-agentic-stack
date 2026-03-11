"""
SERVE AI - Database Configuration
PostgreSQL with SQLAlchemy async (with in-memory fallback for demo)
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
import logging

logger = logging.getLogger(__name__)

# Get database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://serve:serve@localhost:5432/serve_db")

# Flag to track database availability
DB_AVAILABLE = False
engine = None
async_session_factory = None

# Base class for models
Base = declarative_base()

# In-memory store for demo mode
class InMemoryStore:
    """Simple in-memory store for demo when Postgres is unavailable"""
    def __init__(self):
        self.sessions = {}
        self.volunteer_profiles = {}
        self.messages = {}
        self.telemetry = {}
        
    def clear(self):
        self.sessions.clear()
        self.volunteer_profiles.clear()
        self.messages.clear()
        self.telemetry.clear()

in_memory_store = InMemoryStore()


def is_db_available():
    """Check if database is available"""
    return DB_AVAILABLE


async def get_db():
    """Dependency to get database session (or None for demo mode)"""
    if not DB_AVAILABLE or async_session_factory is None:
        yield None
        return
    
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database tables"""
    global engine, async_session_factory, DB_AVAILABLE
    
    try:
        engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_size=5,
            max_overflow=10
        )
        
        async_session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        DB_AVAILABLE = True
        logger.info("PostgreSQL database initialized successfully")
    except Exception as e:
        DB_AVAILABLE = False
        logger.warning(f"PostgreSQL unavailable, using in-memory store for demo: {e}")


async def close_db():
    """Close database connections"""
    global engine
    if engine:
        await engine.dispose()
