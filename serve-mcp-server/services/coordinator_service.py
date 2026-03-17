"""
SERVE MCP Server - Coordinator Service
Business logic for coordinator identity management.
"""
import logging
from typing import Dict, Any, Optional, List
from uuid import uuid4
from datetime import datetime

logger = logging.getLogger(__name__)


class CoordinatorService:
    """Service for coordinator identity operations."""
    
    def __init__(self):
        # In-memory store for preview environment
        self._coordinators: Dict[str, Dict] = {}
        self._coordinator_by_phone: Dict[str, str] = {}  # phone -> coordinator_id
    
    async def resolve_identity(
        self,
        whatsapp_number: str,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Resolve coordinator identity from WhatsApp number.
        
        Returns:
            status: linked | unlinked | ambiguous
            coordinator: Coordinator data if found
            linked_schools: Schools linked to coordinator
        """
        # Check if phone is already linked
        coord_id = self._coordinator_by_phone.get(whatsapp_number)
        
        if coord_id and coord_id in self._coordinators:
            coordinator = self._coordinators[coord_id]
            return {
                "status": "linked",
                "coordinator": coordinator,
                "linked_schools": coordinator.get("school_ids", []),
                "resolution_confidence": 1.0,
                "needs_verification": False
            }
        
        # Check if name matches any known coordinator
        if name:
            name_lower = name.lower()
            matches = []
            for cid, coord in self._coordinators.items():
                if coord.get("name", "").lower() == name_lower:
                    matches.append(coord)
            
            if len(matches) == 1:
                return {
                    "status": "linked",
                    "coordinator": matches[0],
                    "linked_schools": matches[0].get("school_ids", []),
                    "resolution_confidence": 0.8,
                    "needs_verification": True
                }
            elif len(matches) > 1:
                return {
                    "status": "ambiguous",
                    "coordinator": None,
                    "linked_schools": [],
                    "resolution_confidence": 0.0,
                    "needs_verification": True,
                    "ambiguity_reason": f"Multiple coordinators found with name {name}"
                }
        
        # New coordinator - unlinked
        return {
            "status": "unlinked",
            "coordinator": None,
            "linked_schools": [],
            "resolution_confidence": 0.0,
            "needs_verification": True
        }
    
    async def create_coordinator(
        self,
        name: str,
        whatsapp_number: str,
        email: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new coordinator."""
        coord_id = str(uuid4())
        
        coordinator = {
            "id": coord_id,
            "name": name,
            "whatsapp_number": whatsapp_number,
            "email": email,
            "school_ids": [],
            "is_verified": False,
            "created_at": datetime.utcnow().isoformat()
        }
        
        self._coordinators[coord_id] = coordinator
        self._coordinator_by_phone[whatsapp_number] = coord_id
        
        logger.info(f"Created coordinator: {coord_id} - {name}")
        return coordinator
    
    async def map_to_school(
        self,
        coordinator_id: str,
        school_id: str
    ) -> Dict[str, Any]:
        """Map a coordinator to a school."""
        if coordinator_id not in self._coordinators:
            return {"success": False, "error": "Coordinator not found"}
        
        coordinator = self._coordinators[coordinator_id]
        if school_id not in coordinator["school_ids"]:
            coordinator["school_ids"].append(school_id)
        
        logger.info(f"Mapped coordinator {coordinator_id} to school {school_id}")
        return {
            "success": True,
            "coordinator_id": coordinator_id,
            "school_id": school_id
        }
    
    async def get_coordinator(self, coordinator_id: str) -> Optional[Dict]:
        """Get coordinator by ID."""
        return self._coordinators.get(coordinator_id)
    
    async def verify_coordinator(self, coordinator_id: str) -> Dict[str, Any]:
        """Mark coordinator as verified."""
        if coordinator_id not in self._coordinators:
            return {"success": False, "error": "Coordinator not found"}
        
        self._coordinators[coordinator_id]["is_verified"] = True
        return {"success": True, "coordinator_id": coordinator_id}


# Singleton instance
coordinator_service = CoordinatorService()
