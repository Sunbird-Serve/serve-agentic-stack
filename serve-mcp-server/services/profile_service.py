"""
SERVE MCP Server - Profile Service
Handles volunteer profile operations (get, save, evaluate)
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


class InMemoryProfileStore:
    """In-memory profile storage."""
    def __init__(self):
        self.profiles: Dict[str, Dict] = {}


# Global store instance
_store = InMemoryProfileStore()


# Required fields for complete profile
REQUIRED_FIELDS = ["full_name", "email", "skills", "availability"]
OPTIONAL_FIELDS = ["phone", "location", "interests"]


class ProfileService:
    """
    Service for managing volunteer profiles.
    """
    
    async def get_profile(self, session_id: str) -> Dict[str, Any]:
        """Get volunteer profile for a session."""
        profile = _store.profiles.get(session_id, {})
        return {
            "status": "success",
            "profile": profile
        }
    
    async def get_missing_fields(self, session_id: str) -> Dict[str, Any]:
        """Get list of missing required fields."""
        profile = _store.profiles.get(session_id, {})
        
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
        if session_id not in _store.profiles:
            _store.profiles[session_id] = {
                "id": str(uuid4()),
                "session_id": session_id,
                "created_at": datetime.utcnow().isoformat()
            }
        
        for field, value in fields.items():
            if field == "skills":
                # Merge skills
                existing = _store.profiles[session_id].get("skills", [])
                if isinstance(existing, list) and isinstance(value, list):
                    combined = list(set(existing + value))
                    _store.profiles[session_id]["skills"] = combined
                else:
                    _store.profiles[session_id]["skills"] = value
            else:
                _store.profiles[session_id][field] = value
        
        _store.profiles[session_id]["updated_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Profile updated: {session_id[:8]}... fields={list(fields.keys())}")
        
        return {
            "status": "success",
            "saved_fields": list(fields.keys()),
            "profile": _store.profiles[session_id]
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
