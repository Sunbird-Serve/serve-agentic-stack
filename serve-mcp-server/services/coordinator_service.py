"""
SERVE MCP Server - Coordinator Service
All coordinator identity operations now delegate to the Serve Registry
(via VolunteeringClient). In-memory fallback retained for dev/offline use.
"""
import logging
from typing import Any, Dict, List, Optional

from services.serve_registry_client import volunteering_client

logger = logging.getLogger(__name__)


class CoordinatorService:

    async def resolve_identity(
        self,
        whatsapp_number: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Resolve coordinator identity from WhatsApp number or email.
        Tries phone lookup first, then email. Any registered user is treated
        as a valid coordinator (Option A) — role check is advisory only.
        """
        serve_user = None

        # Phone lookup (primary path for WhatsApp channel)
        if whatsapp_number and not serve_user:
            serve_user = await volunteering_client.lookup_by_mobile(whatsapp_number)

        # Email lookup (fallback / web UI path)
        if email and not serve_user:
            serve_user = await volunteering_client.lookup_by_email(email)

        if serve_user:
            roles = serve_user.get("role", [])
            # Role in Serve Registry is "nCoordinator" for coordinators.
            # Option A: treat any registered user as a valid coordinator —
            # entity mapping in the next stage will confirm the school link.
            is_coordinator = "nCoordinator" in roles or bool(roles)

            return {
                "status":               "linked",
                "coordinator": {
                    "id":               serve_user.get("osid"),
                    "name":             serve_user.get("full_name"),
                    "whatsapp_number":  whatsapp_number,
                    "email":            serve_user.get("email"),
                    "is_verified":      serve_user.get("status") == "Active",
                    "school_ids":       [],
                },
                "linked_schools":       [],
                "resolution_confidence": 1.0,
                "needs_verification":   not is_coordinator,
                "source":               "serve_registry",
            }

        # Not found in registry
        if name:
            return {
                "status":               "unlinked",
                "coordinator":          None,
                "linked_schools":       [],
                "resolution_confidence": 0.0,
                "needs_verification":   True,
                "hint":                 f"No coordinator found for name '{name}'",
            }

        return {
            "status":               "unlinked",
            "coordinator":          None,
            "linked_schools":       [],
            "resolution_confidence": 0.0,
            "needs_verification":   True,
        }

    async def create_coordinator(
        self,
        name: str,
        whatsapp_number: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new coordinator in Serve Registry."""
        new_id = await volunteering_client.create_coordinator(
            name=name, phone=whatsapp_number, email=email
        )
        if new_id:
            logger.info(f"Coordinator created in Serve Registry: {new_id}")
            return {
                "id":               new_id,
                "name":             name,
                "whatsapp_number":  whatsapp_number,
                "email":            email,
                "school_ids":       [],
                "is_verified":      False,
                "source":           "serve_registry",
            }
        logger.error("Failed to create coordinator in Serve Registry")
        return {"error": "Failed to create coordinator in Serve Registry"}

    async def get_coordinator(
        self, coordinator_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch coordinator by their Serve Registry osid (lookup by email)."""
        # The volunteering service doesn't have a GET-by-id endpoint;
        # coordinator data comes from the session context or identity resolution.
        logger.warning(f"get_coordinator({coordinator_id}): no direct ID lookup endpoint available")
        return None


coordinator_service = CoordinatorService()
