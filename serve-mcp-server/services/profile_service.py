"""
SERVE MCP Server - Profile Service
Handles volunteer profile operations (get, save, evaluate)

Supports both PostgreSQL (production) and in-memory (development) storage.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4, UUID
import logging

logger = logging.getLogger(__name__)


# In-memory fallback storage
class InMemoryProfileStore:
    """In-memory profile storage."""
    def __init__(self):
        self.profiles: Dict[str, Dict] = {}

_memory_store = InMemoryProfileStore()


# Required fields for complete profile
REQUIRED_FIELDS = ["full_name", "email", "skills", "availability"]
OPTIONAL_FIELDS = ["phone", "location", "interests"]


class ProfileService:
    """
    Service for managing volunteer profiles.
    Automatically uses Postgres if available, falls back to in-memory.
    """
    
    async def _check_postgres(self) -> bool:
        """Check if Postgres is available."""
        try:
            from .database import test_connection
            return await test_connection()
        except ImportError:
            return False
    
    async def get_profile(self, session_id: str) -> Dict[str, Any]:
        """Get volunteer profile for a session."""
        # Try Postgres
        if await self._check_postgres():
            try:
                from .database import get_db, VolunteerProfile
                from sqlalchemy import select
                async with get_db() as db:
                    result = await db.execute(
                        select(VolunteerProfile).where(
                            VolunteerProfile.session_id == UUID(session_id)
                        )
                    )
                    profile = result.scalar_one_or_none()
                    if profile:
                        return {
                            "status": "success",
                            "profile": {
                                "id": str(profile.id),
                                "session_id": str(profile.session_id),
                                "full_name": profile.full_name,
                                "email": profile.email,
                                "phone": profile.phone,
                                "location": profile.location,
                                "skills": profile.skills or [],
                                "interests": profile.interests or [],
                                "availability": profile.availability
                            }
                        }
            except Exception as e:
                logger.warning(f"Postgres get profile failed: {e}")
        
        # Fallback to memory
        profile = _memory_store.profiles.get(session_id, {})
        return {"status": "success", "profile": profile}
    
    async def get_missing_fields(self, session_id: str) -> Dict[str, Any]:
        """Get list of missing required fields."""
        profile_result = await self.get_profile(session_id)
        profile = profile_result.get("profile", {})
        
        missing = []
        confirmed = {}
        
        for field in REQUIRED_FIELDS:
            value = profile.get(field)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
            else:
                confirmed[field] = value
        
        # Also include optional fields if present
        for field in OPTIONAL_FIELDS:
            value = profile.get(field)
            if value:
                confirmed[field] = value
        
        total_fields = len(REQUIRED_FIELDS)
        confirmed_required = total_fields - len(missing)
        completion = round((confirmed_required / total_fields) * 100) if total_fields > 0 else 0
        
        return {
            "status": "success",
            "missing_fields": missing,
            "confirmed_fields": confirmed,
            "completion_percentage": completion
        }
    
    async def save_fields(
        self,
        session_id: str,
        fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Save confirmed volunteer fields."""
        now = datetime.utcnow()
        
        # Initialize profile if not exists
        if session_id not in _memory_store.profiles:
            _memory_store.profiles[session_id] = {
                "id": str(uuid4()),
                "session_id": session_id,
                "skills": [],
                "interests": [],
                "created_at": now.isoformat()
            }
        
        profile = _memory_store.profiles[session_id]
        
        for field, value in fields.items():
            if field == "skills":
                # Merge skills
                existing = profile.get("skills", [])
                if isinstance(existing, list) and isinstance(value, list):
                    combined = list(set(existing + value))
                    profile["skills"] = combined
                else:
                    profile["skills"] = value if isinstance(value, list) else [value]
            else:
                profile[field] = value
        
        profile["updated_at"] = now.isoformat()
        
        logger.info(f"Profile updated: {session_id[:8]}... fields={list(fields.keys())}")
        
        return {
            "status": "success",
            "saved_fields": list(fields.keys()),
            "profile": profile
        }
    
    async def evaluate_readiness(self, session_id: str) -> Dict[str, Any]:
        """Evaluate if volunteer is ready for selection phase."""
        result = await self.get_missing_fields(session_id)
        missing = result.get("missing_fields", [])
        
        is_ready = len(missing) == 0
        
        if is_ready:
            recommendation = "proceed_to_selection"
            reason = "All required fields have been collected"
        elif len(missing) == 1:
            recommendation = "collect_one_more"
            reason = f"Only missing: {missing[0]}"
        else:
            recommendation = "continue_onboarding"
            reason = f"Missing {len(missing)} required fields: {', '.join(missing)}"
        
        return {
            "status": "success",
            "ready_for_selection": is_ready,
            "missing_fields": missing,
            "recommendation": recommendation,
            "reason": reason
        }
