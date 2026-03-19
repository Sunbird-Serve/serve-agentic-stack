"""
SERVE MCP Server - Memory Service
Stores and retrieves AI-compressed conversation summaries.
Now correctly writes to the memory_summaries PostgreSQL table
(previously only used an in-memory dict — data was lost on restart).
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, update

from services.database import MemorySummary, get_db, is_db_healthy

logger = logging.getLogger(__name__)

# In-memory fallback
_mem_summaries: Dict[str, Dict] = {}


class MemoryService:

    async def save_summary(
        self,
        session_id: str,
        summary_text: str,
        key_facts: Optional[List[str]] = None,
        volunteer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save or update a memory summary for a session.
        Each call increments the version counter (history is NOT overwritten —
        the latest record per session_id is used on read).
        """
        now   = datetime.utcnow()
        facts = key_facts or []

        if is_db_healthy():
            try:
                async with get_db() as db:
                    # Check for existing summary to increment version
                    result = await db.execute(
                        select(MemorySummary)
                        .where(MemorySummary.session_id == UUID(session_id))
                        .order_by(MemorySummary.version.desc())
                        .limit(1)
                    )
                    existing = result.scalar_one_or_none()
                    version = (existing.version + 1) if existing else 1

                    summary_id = str(uuid4())
                    db.add(MemorySummary(
                        id=UUID(summary_id),
                        session_id=UUID(session_id),
                        volunteer_id=volunteer_id,
                        summary_text=summary_text,
                        key_facts=facts,
                        version=version,
                        created_at=now,
                        updated_at=now,
                    ))
                logger.info(f"Memory summary v{version} saved for session {session_id[:8]}…")
                return {
                    "status":          "success",
                    "summary_id":      summary_id,
                    "version":         version,
                    "key_facts_count": len(facts),
                }
            except Exception as e:
                logger.warning(f"DB save_summary failed, using memory fallback: {e}")

        # In-memory fallback
        summary_id = str(uuid4())
        version    = (_mem_summaries.get(session_id, {}).get("version", 0) + 1)
        _mem_summaries[session_id] = {
            "id":           summary_id,
            "session_id":   session_id,
            "summary_text": summary_text,
            "key_facts":    facts,
            "version":      version,
            "created_at":   now.isoformat(),
        }
        return {"status": "success", "summary_id": summary_id, "version": version,
                "key_facts_count": len(facts)}

    async def get_summary(self, session_id: str) -> Dict[str, Any]:
        """Retrieve the latest memory summary for a session."""
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(MemorySummary)
                        .where(MemorySummary.session_id == UUID(session_id))
                        .order_by(MemorySummary.version.desc())
                        .limit(1)
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        return {
                            "status": "success",
                            "data": {
                                "summary_id":   str(row.id),
                                "summary_text": row.summary_text,
                                "key_facts":    row.key_facts or [],
                                "version":      row.version,
                                "created_at":   row.created_at.isoformat() if row.created_at else None,
                            },
                        }
                    return {"status": "success", "data": None}
            except Exception as e:
                logger.warning(f"DB get_summary failed: {e}")

        summary = _mem_summaries.get(session_id)
        if not summary:
            return {"status": "success", "data": None}
        return {
            "status": "success",
            "data": {
                "summary_id":   summary["id"],
                "summary_text": summary["summary_text"],
                "key_facts":    summary["key_facts"],
                "version":      summary.get("version", 1),
                "created_at":   summary["created_at"],
            },
        }

    async def get_memory_context(
        self,
        session_id: str,
        confirmed_fields: Optional[Dict] = None,
    ) -> str:
        """Build a context string for inclusion in agent prompts."""
        result = await self.get_summary(session_id)
        data   = result.get("data")
        if not data:
            return ""

        parts = []
        if data.get("summary_text"):
            parts.append(f"Previous conversation: {data['summary_text']}")
        if data.get("key_facts"):
            facts = "\n".join(f"  - {f}" for f in data["key_facts"][:5])
            parts.append(f"Key facts:\n{facts}")
        if confirmed_fields:
            name = confirmed_fields.get("full_name")
            if name:
                parts.append(f"Remember: Their name is {name}.")

        return "\n\n".join(parts)
