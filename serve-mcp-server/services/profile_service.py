"""
SERVE MCP Server - Profile Service
Manages the session-scoped volunteer profile (working copy / Serve Registry cache).

Read strategy:
  1. Read from MCP DB volunteer_profiles (fast, no API call)
  2. If not in MCP DB and a volunteer_id is known → fetch from Serve Registry

Write strategy (mid-conversation):
  - All writes go to MCP DB only (no Serve Registry call)

Write-back (at onboarding completion):
  - Called by main.py when stage = "onboarding_complete"
  - Pushes full profile to Serve Registry via VolunteeringClient
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select, update

from services.database import VolunteerProfile, get_db, is_db_healthy
from services.serve_registry_client import volunteering_client

logger = logging.getLogger(__name__)

# Required fields for readiness check
REQUIRED_FIELDS  = ["full_name", "email", "skills", "availability"]
OPTIONAL_FIELDS  = ["phone", "location", "interests"]

# In-memory fallback
_mem_profiles: Dict[str, Dict] = {}


class ProfileService:

    # ── Get / Pre-populate ────────────────────────────────────────────────────

    async def get_profile(self, session_id: str) -> Dict[str, Any]:
        """Return the MCP DB profile for a session."""
        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(VolunteerProfile).where(
                            VolunteerProfile.session_id == UUID(session_id)
                        )
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        return {"status": "success", "profile": self._row_to_dict(row)}
            except Exception as e:
                logger.warning(f"DB get_profile failed: {e}")

        profile = _mem_profiles.get(session_id, {})
        return {"status": "success", "profile": profile}

    async def prefetch_from_registry(
        self,
        session_id: str,
        volunteer_id: str,
    ) -> Dict[str, Any]:
        """
        Called at session start for S2/S3 users.
        Fetches profile from Serve Registry and stores in MCP DB.
        This pre-populates data so the AI doesn't re-ask for known info.
        """
        # 1. Fetch user record (identity fields)
        user_data = None
        # We need to look up the user by their osid — but the volunteering service
        # only exposes GET by email. We'll get what we have from the session context.
        # For now we rely on the volunteering_client that already parsed the user object.

        # 2. Fetch user-profile (skills, preferences)
        profile_data = await volunteering_client.get_user_profile(volunteer_id)

        now = datetime.utcnow()

        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(VolunteerProfile).where(
                            VolunteerProfile.session_id == UUID(session_id)
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if profile_data:
                        fields = {
                            "serve_volunteer_id":    volunteer_id,
                            "source":                "registry",
                            "registry_fetched_at":   now,
                            "skills":                profile_data.get("skills") or [],
                            "skill_levels":          profile_data.get("skill_levels"),
                            "interests":             profile_data.get("interests") or [],
                            "languages":             profile_data.get("languages") or [],
                            "days_preferred":        profile_data.get("days_preferred") or [],
                            "time_preferred":        profile_data.get("time_preferred") or [],
                            "qualification":         profile_data.get("qualification"),
                            "years_of_experience":   profile_data.get("years_of_experience"),
                            "employment_status":     profile_data.get("employment_status"),
                            "profile_completion_pct": profile_data.get("profile_completion_pct", 0),
                            "onboarding_completed":  profile_data.get("onboarding_completed", False),
                            "updated_at":            now,
                        }
                        if existing:
                            await db.execute(
                                update(VolunteerProfile)
                                .where(VolunteerProfile.session_id == UUID(session_id))
                                .values(**fields)
                            )
                        else:
                            db.add(VolunteerProfile(
                                session_id=UUID(session_id),
                                **fields,
                                created_at=now,
                            ))
                    elif not existing:
                        # No profile data yet — create empty row with registry marker
                        db.add(VolunteerProfile(
                            session_id=UUID(session_id),
                            serve_volunteer_id=volunteer_id,
                            source="registry",
                            registry_fetched_at=now,
                            created_at=now,
                            updated_at=now,
                        ))

                logger.info(f"Profile prefetched from registry for session {session_id[:8]}…")
                return {"status": "success", "prefetched": profile_data is not None}
            except Exception as e:
                logger.warning(f"DB prefetch_from_registry failed: {e}")

        return {"status": "success", "prefetched": False}

    # ── Missing fields ────────────────────────────────────────────────────────

    async def get_missing_fields(self, session_id: str) -> Dict[str, Any]:
        profile_result = await self.get_profile(session_id)
        profile = profile_result.get("profile", {})

        missing   = []
        confirmed = {}

        for field in REQUIRED_FIELDS:
            value = profile.get(field)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
            else:
                confirmed[field] = value

        for field in OPTIONAL_FIELDS:
            value = profile.get(field)
            if value:
                confirmed[field] = value

        completion = round(
            ((len(REQUIRED_FIELDS) - len(missing)) / len(REQUIRED_FIELDS)) * 100
        ) if REQUIRED_FIELDS else 0

        return {
            "status": "success",
            "missing_fields":       missing,
            "confirmed_fields":     confirmed,
            "completion_percentage": completion,
        }

    # ── Save fields (mid-conversation → MCP DB only) ──────────────────────────

    async def save_fields(
        self,
        session_id: str,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Save collected volunteer fields to MCP DB working copy."""
        now = datetime.utcnow()

        if is_db_healthy():
            try:
                async with get_db() as db:
                    result = await db.execute(
                        select(VolunteerProfile).where(
                            VolunteerProfile.session_id == UUID(session_id)
                        )
                    )
                    existing = result.scalar_one_or_none()

                    update_values: Dict[str, Any] = {"updated_at": now}

                    for field, value in fields.items():
                        if field == "skills":
                            existing_skills = (existing.skills or []) if existing else []
                            if isinstance(value, list):
                                update_values["skills"] = list(set(existing_skills + value))
                            else:
                                update_values["skills"] = existing_skills + [value]
                        elif field == "skill_levels":
                            existing_levels = (existing.skill_levels or {}) if existing else {}
                            if isinstance(value, dict):
                                existing_levels.update(value)
                            update_values["skill_levels"] = existing_levels
                        elif field in (
                            "full_name", "first_name", "gender", "dob",
                            "email", "phone", "location",
                            "interests", "languages", "availability",
                            "days_preferred", "time_preferred",
                            "qualification", "years_of_experience",
                            "employment_status", "motivation",
                            "experience_level", "eligibility_status",
                        ):
                            update_values[field] = value

                    if existing:
                        await db.execute(
                            update(VolunteerProfile)
                            .where(VolunteerProfile.session_id == UUID(session_id))
                            .values(**update_values)
                        )
                    else:
                        update_values["session_id"] = UUID(session_id)
                        update_values["source"]     = "new"
                        update_values["created_at"] = now
                        db.add(VolunteerProfile(**update_values))

                logger.info(f"Profile fields saved to MCP DB: {list(fields.keys())}")
                return {"status": "success", "saved_fields": list(fields.keys())}
            except Exception as e:
                logger.warning(f"DB save_fields failed: {e}")

        # In-memory fallback
        if session_id not in _mem_profiles:
            _mem_profiles[session_id] = {"session_id": session_id, "skills": [],
                                          "source": "new", "created_at": now.isoformat()}
        profile = _mem_profiles[session_id]
        for field, value in fields.items():
            if field == "skills":
                existing = profile.get("skills", [])
                profile["skills"] = list(set(existing + (value if isinstance(value, list) else [value])))
            else:
                profile[field] = value
        profile["updated_at"] = now.isoformat()
        return {"status": "success", "saved_fields": list(fields.keys())}

    # ── Evaluate readiness ────────────────────────────────────────────────────

    async def evaluate_readiness(self, session_id: str) -> Dict[str, Any]:
        result  = await self.get_missing_fields(session_id)
        missing = result.get("missing_fields", [])
        is_ready = len(missing) == 0

        if is_ready:
            recommendation = "proceed_to_selection"
            reason = "All required fields collected"
        elif len(missing) == 1:
            recommendation = "collect_one_more"
            reason = f"Only missing: {missing[0]}"
        else:
            recommendation = "continue_onboarding"
            reason = f"Missing {len(missing)} fields: {', '.join(missing)}"

        return {
            "status": "success",
            "ready_for_selection": is_ready,
            "missing_fields":      missing,
            "recommendation":      recommendation,
            "reason":              reason,
        }

    # ── Write-back to Serve Registry (called at onboarding completion) ─────────

    async def sync_to_registry(
        self,
        session_id: str,
        volunteer_id: str,
    ) -> Dict[str, Any]:
        """
        Push the MCP DB profile to Serve Registry.
        Called once when the onboarding workflow completes.
        """
        profile_result = await self.get_profile(session_id)
        profile = profile_result.get("profile", {})

        if not profile:
            return {"status": "error", "error_message": "No profile data to sync"}

        # Update user record (contactDetails + identityDetails)
        user_ok = await volunteering_client.update_user(volunteer_id, profile)

        # Save / update user-profile (skills, preferences)
        existing_profile_id = profile.get("serve_volunteer_id")
        profile_ok = await volunteering_client.save_volunteer_profile(
            volunteer_id=volunteer_id,
            profile_data=profile,
            existing_profile_id=existing_profile_id,
        )

        now = datetime.utcnow()
        if is_db_healthy() and (user_ok or profile_ok):
            try:
                async with get_db() as db:
                    await db.execute(
                        update(VolunteerProfile)
                        .where(VolunteerProfile.session_id == UUID(session_id))
                        .values(
                            registry_synced_at=now,
                            onboarding_completed=True,
                            source="merged",
                            updated_at=now,
                        )
                    )
            except Exception as e:
                logger.warning(f"DB sync_to_registry update failed: {e}")

        logger.info(f"Profile synced to Serve Registry for {volunteer_id}: user={user_ok} profile={profile_ok}")
        return {
            "status": "success" if (user_ok or profile_ok) else "partial",
            "user_updated":    user_ok,
            "profile_updated": profile_ok,
            "synced_at":       now.isoformat(),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _row_to_dict(self, row: VolunteerProfile) -> Dict:
        return {
            "id":                    str(row.id),
            "session_id":            str(row.session_id) if row.session_id else None,
            "serve_volunteer_id":    row.serve_volunteer_id,
            "source":                row.source,
            "registry_fetched_at":   row.registry_fetched_at.isoformat() if row.registry_fetched_at else None,
            "registry_synced_at":    row.registry_synced_at.isoformat() if row.registry_synced_at else None,
            "is_complete":           row.is_complete,
            "full_name":             row.full_name,
            "first_name":            row.first_name,
            "gender":                row.gender,
            "dob":                   row.dob,
            "email":                 row.email,
            "phone":                 row.phone,
            "location":              row.location,
            "skills":                row.skills or [],
            "skill_levels":          row.skill_levels or {},
            "interests":             row.interests or [],
            "languages":             row.languages or [],
            "availability":          row.availability,
            "days_preferred":        row.days_preferred or [],
            "time_preferred":        row.time_preferred or [],
            "qualification":         row.qualification,
            "years_of_experience":   row.years_of_experience,
            "employment_status":     row.employment_status,
            "profile_completion_pct": row.profile_completion_pct,
            "onboarding_completed":  row.onboarding_completed,
            "eligibility_status":    row.eligibility_status,
            "motivation":            row.motivation,
        }
