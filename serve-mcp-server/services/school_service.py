"""
SERVE MCP Server - School Service
Business logic for school context management.
"""
import logging
from typing import Dict, Any, Optional, List
from uuid import uuid4
from datetime import datetime

logger = logging.getLogger(__name__)


class SchoolService:
    """Service for school context operations."""
    
    def __init__(self):
        # In-memory store for preview environment
        self._schools: Dict[str, Dict] = {}
        self._school_by_name: Dict[str, str] = {}  # normalized_name -> school_id
    
    async def resolve_context(
        self,
        coordinator_id: Optional[str] = None,
        school_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resolve school context.
        
        Args:
            coordinator_id: ID of linked coordinator
            school_hint: Partial school name or hint
            
        Returns:
            status: existing | new | ambiguous
            school: School data if found
            previous_needs: List of previous needs for this school
        """
        # If coordinator is linked, check their schools
        if coordinator_id:
            for school_id, school in self._schools.items():
                if coordinator_id in school.get("coordinator_ids", []):
                    return {
                        "status": "existing",
                        "school": school,
                        "previous_needs": school.get("previous_needs", []),
                        "needs_creation": False
                    }
        
        # Try to match by name hint
        if school_hint:
            normalized = school_hint.lower().strip()
            
            # Exact match
            if normalized in self._school_by_name:
                school_id = self._school_by_name[normalized]
                school = self._schools[school_id]
                return {
                    "status": "existing",
                    "school": school,
                    "previous_needs": school.get("previous_needs", []),
                    "needs_creation": False
                }
            
            # Partial match
            matches = []
            for name, sid in self._school_by_name.items():
                if normalized in name or name in normalized:
                    matches.append(self._schools[sid])
            
            if len(matches) == 1:
                return {
                    "status": "existing",
                    "school": matches[0],
                    "previous_needs": matches[0].get("previous_needs", []),
                    "needs_creation": False
                }
            elif len(matches) > 1:
                return {
                    "status": "ambiguous",
                    "school": None,
                    "previous_needs": [],
                    "needs_creation": False,
                    "ambiguity_reason": f"Multiple schools match '{school_hint}'"
                }
        
        # No match found - new school needed
        return {
            "status": "new",
            "school": None,
            "previous_needs": [],
            "needs_creation": True
        }
    
    async def create_school(
        self,
        name: str,
        location: str,
        contact_number: Optional[str] = None,
        coordinator_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new school context."""
        school_id = str(uuid4())
        
        school = {
            "id": school_id,
            "name": name,
            "location": location,
            "contact_number": contact_number,
            "coordinator_ids": [coordinator_id] if coordinator_id else [],
            "previous_needs": [],
            "created_at": datetime.utcnow().isoformat()
        }
        
        self._schools[school_id] = school
        self._school_by_name[name.lower().strip()] = school_id
        
        logger.info(f"Created school: {school_id} - {name}")
        return school
    
    async def get_school(self, school_id: str) -> Optional[Dict]:
        """Get school by ID."""
        return self._schools.get(school_id)
    
    async def add_coordinator(self, school_id: str, coordinator_id: str) -> Dict[str, Any]:
        """Add a coordinator to a school."""
        if school_id not in self._schools:
            return {"success": False, "error": "School not found"}
        
        school = self._schools[school_id]
        if coordinator_id not in school["coordinator_ids"]:
            school["coordinator_ids"].append(coordinator_id)
        
        return {"success": True, "school_id": school_id}
    
    async def fetch_previous_needs(self, school_id: str) -> Dict[str, Any]:
        """Fetch previous need context for a school."""
        if school_id not in self._schools:
            return {"success": False, "needs": [], "error": "School not found"}
        
        school = self._schools[school_id]
        return {
            "success": True,
            "school": school,
            "needs": school.get("previous_needs", [])
        }
    
    async def add_need_reference(self, school_id: str, need_id: str) -> None:
        """Add a need reference to school's history."""
        if school_id in self._schools:
            if need_id not in self._schools[school_id]["previous_needs"]:
                self._schools[school_id]["previous_needs"].append(need_id)


# Singleton instance
school_service = SchoolService()
