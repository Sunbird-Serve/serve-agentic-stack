"""
SERVE MCP Server - School Service
All school (entity) operations delegate to the Serve Need Service
via NeedServiceClient. Schools are entities owned by the Serve DB.
"""
import logging
from typing import Any, Dict, List, Optional

from services.serve_registry_client import need_service_client

logger = logging.getLogger(__name__)


class SchoolService:

    async def resolve_context(
        self,
        coordinator_id: Optional[str] = None,
        school_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Resolve school context for a coordinator.
        1. If coordinator_id → fetch their linked entities from Serve Need Service
        2. If school_hint → search all entities and filter by name
        """
        # Try coordinator's linked entities first
        if coordinator_id:
            entities = await need_service_client.get_entities_for_user(coordinator_id)
            if entities:
                if len(entities) == 1:
                    return {
                        "status":         "existing",
                        "school":         entities[0],
                        "previous_needs": [],
                        "needs_creation": False,
                        "source":         "serve_need_service",
                    }
                # Multiple schools — return list for disambiguation
                return {
                    "status":         "multiple",
                    "schools":        entities,
                    "school":         None,
                    "previous_needs": [],
                    "needs_creation": False,
                    "source":         "serve_need_service",
                }

        # Try name-based search
        if school_hint:
            all_entities = await need_service_client.search_entities()
            hint_lower   = school_hint.lower().strip()
            matches = [
                e for e in all_entities
                if hint_lower in e.get("name", "").lower()
            ]
            if len(matches) == 1:
                return {
                    "status":         "existing",
                    "school":         matches[0],
                    "previous_needs": [],
                    "needs_creation": False,
                    "source":         "serve_need_service",
                }
            if len(matches) > 1:
                return {
                    "status":         "ambiguous",
                    "schools":        matches,
                    "school":         None,
                    "previous_needs": [],
                    "needs_creation": True,
                    "source":         "serve_need_service",
                }

        # Nothing found — needs to be created
        return {
            "status":         "new",
            "school":         None,
            "previous_needs": [],
            "needs_creation": True,
            "source":         "serve_need_service",
        }

    async def create_school(
        self,
        name: str,
        location: str,
        contact_number: Optional[str] = None,
        coordinator_id: Optional[str] = None,
        district: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new entity (school) in Serve Need Service.
        Optionally links the coordinator to the new entity.
        """
        entity = await need_service_client.create_entity(
            name=name,
            location=location,
            contact_number=contact_number,
            district=district,
            state=state,
        )
        if not entity:
            return {"error": "Failed to create school in Serve Need Service"}

        # Auto-link coordinator if provided
        if coordinator_id and entity.get("id"):
            linked = await need_service_client.assign_user_to_entity(
                entity_id=entity["id"],
                user_id=coordinator_id,
            )
            entity["coordinator_linked"] = linked

        logger.info(f"School created in Serve Need Service: {entity.get('id')} — {name}")
        return entity

    async def fetch_previous_needs(self, school_id: str) -> Dict[str, Any]:
        """Fetch entity details + previous needs from Serve Need Service."""
        entity = await need_service_client.get_entity(school_id)
        needs  = await need_service_client.get_needs_for_entity(school_id)
        return {
            "status":         "success",
            "school":         entity or {"id": school_id},
            "previous_needs": needs,
            "needs_count":    len(needs),
        }

    async def link_coordinator(
        self,
        school_id: str,
        coordinator_id: str,
    ) -> Dict[str, Any]:
        """Link an existing coordinator to an existing school."""
        ok = await need_service_client.assign_user_to_entity(
            entity_id=school_id,
            user_id=coordinator_id,
        )
        return {
            "success":        ok,
            "school_id":      school_id,
            "coordinator_id": coordinator_id,
        }


school_service = SchoolService()
