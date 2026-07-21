"""
SERVE MCP Server - Volunteer Service
CRUD operations for the persistent volunteer fact-store.

The `volunteers` table holds one row per volunteer with:
- Denormalized identity (name, phone, email) for dashboard display
- serve_registry_id for linking to external Serve Registry
- facts JSONB for all accumulated AI platform knowledge

Facts JSONB structure:
{
    "identity_verified": bool,
    "adult_eligibility": bool,
    "internet_device": bool,
    "unpaid_consent": bool,
    "registered": bool,
    "platform_status": "active" | "dormant" | "withdrawn",
    "credentials": {
        "english_teaching": {
            "status": "recommended" | "engagement_later" | "not_matched" | ...,
            "confidence": float,
            "assessed_at": "ISO datetime",
            "signals": {...},
            "notes": {...}
        }
    },
    "preferences": {
        "intent": "teach",
        "subjects": [...],
        "days": [...],
        "time": "10:00-12:00",
        "commitment_weeks": int,
        "willing_to_act": "ready_now" | "deferred" | "declined",
        "captured_at": "ISO datetime"
    },
    "commitments": [
        {"need_id": "...", "school": "...", "status": "nominated", ...}
    ]
}
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from services.database import get_db, is_db_healthy, Volunteer

logger = logging.getLogger(__name__)


class VolunteerService:
    """Service for managing the persistent volunteer fact-store."""

    async def get_by_id(self, volunteer_id: str) -> Optional[Dict[str, Any]]:
        """Get a volunteer by their platform ID."""
        if not is_db_healthy():
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Volunteer).where(Volunteer.id == UUID(volunteer_id))
                )
                row = result.scalars().first()
                return self._to_dict(row) if row else None
        except Exception as e:
            logger.error(f"get_by_id failed: {e}")
            return None

    async def get_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find a volunteer by email."""
        if not is_db_healthy() or not email:
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Volunteer).where(Volunteer.email == email.lower().strip())
                )
                row = result.scalars().first()
                return self._to_dict(row) if row else None
        except Exception as e:
            logger.error(f"get_by_email failed: {e}")
            return None

    async def get_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """Find a volunteer by phone number."""
        if not is_db_healthy() or not phone:
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Volunteer).where(Volunteer.phone == phone.strip())
                )
                row = result.scalars().first()
                return self._to_dict(row) if row else None
        except Exception as e:
            logger.error(f"get_by_phone failed: {e}")
            return None

    async def get_by_serve_registry_id(self, serve_id: str) -> Optional[Dict[str, Any]]:
        """Find a volunteer by their Serve Registry osid."""
        if not is_db_healthy() or not serve_id:
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Volunteer).where(Volunteer.serve_registry_id == serve_id)
                )
                row = result.scalars().first()
                return self._to_dict(row) if row else None
        except Exception as e:
            logger.error(f"get_by_serve_registry_id failed: {e}")
            return None

    async def find_volunteer(self, email: str = None, phone: str = None, serve_registry_id: str = None) -> Optional[Dict[str, Any]]:
        """Find a volunteer by any identifier (tries in order: serve_id, email, phone)."""
        if serve_registry_id:
            result = await self.get_by_serve_registry_id(serve_registry_id)
            if result:
                return result
        if email:
            result = await self.get_by_email(email)
            if result:
                return result
        if phone:
            result = await self.get_by_phone(phone)
            if result:
                return result
        return None

    async def create_volunteer(
        self,
        full_name: str = None,
        phone: str = None,
        email: str = None,
        serve_registry_id: str = None,
        facts: Dict[str, Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a new volunteer record. Returns the created row."""
        if not is_db_healthy():
            return None
        try:
            async with get_db() as db:
                vol = Volunteer(
                    full_name=full_name,
                    phone=phone.strip() if phone else None,
                    email=email.lower().strip() if email else None,
                    serve_registry_id=serve_registry_id,
                    facts=facts or {},
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(vol)
                await db.flush()
                logger.info(f"Created volunteer: id={vol.id}, name={full_name}, email={email}")
                return self._to_dict(vol)
        except Exception as e:
            logger.error(f"create_volunteer failed: {e}")
            return None

    async def update_volunteer(
        self,
        volunteer_id: str,
        full_name: str = None,
        phone: str = None,
        email: str = None,
        serve_registry_id: str = None,
    ) -> bool:
        """Update denormalized identity fields on a volunteer."""
        if not is_db_healthy():
            return False
        try:
            updates: Dict[str, Any] = {"updated_at": datetime.utcnow()}
            if full_name is not None:
                updates["full_name"] = full_name
            if phone is not None:
                updates["phone"] = phone.strip()
            if email is not None:
                updates["email"] = email.lower().strip()
            if serve_registry_id is not None:
                updates["serve_registry_id"] = serve_registry_id

            async with get_db() as db:
                await db.execute(
                    sa_update(Volunteer)
                    .where(Volunteer.id == UUID(volunteer_id))
                    .values(**updates)
                )
            return True
        except Exception as e:
            logger.error(f"update_volunteer failed: {e}")
            return False

    async def merge_facts(self, volunteer_id: str, new_facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Merge new facts into the volunteer's existing facts JSONB.
        Uses shallow merge at top level, deep merge for nested dicts like 'credentials'.
        Returns the updated facts dict.
        """
        if not is_db_healthy() or not new_facts:
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Volunteer).where(Volunteer.id == UUID(volunteer_id))
                )
                vol = result.scalars().first()
                if not vol:
                    return None

                current_facts = dict(vol.facts or {})

                # Deep merge for known nested keys
                for key in ("credentials", "preferences", "commitments"):
                    if key in new_facts:
                        if key == "commitments":
                            # Commitments is a list — append new entries
                            existing = current_facts.get("commitments") or []
                            incoming = new_facts["commitments"]
                            if isinstance(incoming, list):
                                existing.extend(incoming)
                            current_facts["commitments"] = existing
                        elif key == "credentials":
                            # Credentials is a dict keyed by category — merge per-category
                            existing = current_facts.get("credentials") or {}
                            incoming = new_facts["credentials"]
                            if isinstance(incoming, dict):
                                existing.update(incoming)
                            current_facts["credentials"] = existing
                        else:
                            # Preferences — overwrite entirely (latest wins)
                            current_facts[key] = new_facts[key]

                # Shallow merge for all other top-level keys
                for key, value in new_facts.items():
                    if key not in ("credentials", "preferences", "commitments"):
                        current_facts[key] = value

                await db.execute(
                    sa_update(Volunteer)
                    .where(Volunteer.id == UUID(volunteer_id))
                    .values(facts=current_facts, updated_at=datetime.utcnow())
                )
                logger.info(f"Merged facts for volunteer {volunteer_id}: keys={list(new_facts.keys())}")
                return current_facts
        except Exception as e:
            logger.error(f"merge_facts failed: {e}")
            return None

    async def get_facts(self, volunteer_id: str) -> Optional[Dict[str, Any]]:
        """Get just the facts JSONB for a volunteer."""
        if not is_db_healthy():
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(Volunteer.facts).where(Volunteer.id == UUID(volunteer_id))
                )
                row = result.scalar()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_facts failed: {e}")
            return None

    async def get_credential(self, volunteer_id: str, category: str) -> Optional[Dict[str, Any]]:
        """Get a specific credential for a volunteer by category."""
        facts = await self.get_facts(volunteer_id)
        if not facts:
            return None
        credentials = facts.get("credentials") or {}
        return credentials.get(category)

    async def has_credential(self, volunteer_id: str, category: str, required_status: str = "recommended") -> bool:
        """Check if a volunteer has a valid credential for a category."""
        credential = await self.get_credential(volunteer_id, category)
        if not credential:
            return False
        return credential.get("status") == required_status

    def _to_dict(self, row: Volunteer) -> Dict[str, Any]:
        """Convert a Volunteer ORM object to a plain dict."""
        if not row:
            return {}
        return {
            "id": str(row.id),
            "serve_registry_id": row.serve_registry_id,
            "full_name": row.full_name,
            "phone": row.phone,
            "email": row.email,
            "facts": dict(row.facts or {}),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


# Singleton
volunteer_service = VolunteerService()
