"""
SERVE MCP Server - Memory Service
Handles conversation memory and summarization
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


class InMemoryMemoryStore:
    """In-memory memory storage."""
    def __init__(self):
        self.summaries: Dict[str, Dict] = {}


# Global store instance
_store = InMemoryMemoryStore()


class MemoryService:
    """
    Service for managing conversation memory summaries.
    """
    
    async def save_summary(
        self,
        session_id: str,
        summary_text: str,
        key_facts: List[str] = None
    ) -> Dict[str, Any]:
        """Save a memory summary for a session."""
        summary_id = str(uuid4())
        
        _store.summaries[session_id] = {
            "id": summary_id,
            "session_id": session_id,
            "summary_text": summary_text,
            "key_facts": key_facts or [],
            "created_at": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Memory saved: {session_id[:8]}... facts={len(key_facts or [])}")
        
        return {
            "status": "success",
            "summary_id": summary_id,
            "key_facts_count": len(key_facts or [])
        }
    
    async def get_summary(self, session_id: str) -> Dict[str, Any]:
        """Get memory summary for a session."""
        summary = _store.summaries.get(session_id)
        
        if not summary:
            return {
                "status": "success",
                "data": None
            }
        
        return {
            "status": "success",
            "data": {
                "summary_id": summary["id"],
                "summary_text": summary["summary_text"],
                "key_facts": summary["key_facts"],
                "created_at": summary["created_at"]
            }
        }
    
    async def get_memory_context(
        self,
        session_id: str,
        confirmed_fields: Dict = None
    ) -> str:
        """
        Generate a context string for use in prompts.
        Returns empty string if no memory exists.
        """
        result = await self.get_summary(session_id)
        data = result.get("data")
        
        if not data:
            return ""
        
        context_parts = []
        
        if data.get("summary_text"):
            context_parts.append(f"Previous conversation: {data['summary_text']}")
        
        if data.get("key_facts"):
            facts = "\n".join(f"  - {f}" for f in data["key_facts"][:5])
            context_parts.append(f"Key facts:\n{facts}")
        
        if confirmed_fields:
            name = confirmed_fields.get("full_name")
            if name:
                context_parts.append(f"Remember: Their name is {name}.")
        
        return "\n\n".join(context_parts)
