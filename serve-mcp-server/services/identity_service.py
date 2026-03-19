"""
SERVE MCP Server - Identity Resolution Service
Resolves "who is this actor?" before any workflow starts.

User type classification (S1-S5):
  S1 — new_user          : not in Serve Registry, no prior AI sessions
  S2 — registry_known    : in Serve Registry, first time with AI
  S3 — returning_ai_user : in Serve Registry, has prior AI sessions
  S4 — coordinator       : need coordinator (in Serve Registry as NEED_COORDINATOR)
  S5 — anonymous         : no identity provided (web visitor, no email/phone)

Resolution order:
  1. Check actor_registry_cache (no network call if hit + not expired)
  2. Call Serve Registry (volunteering service) if cache miss/expired
  3. Check MCP sessions history for prior AI interaction
  4. Classify S1-S5
  5. Write to identity_resolution_log
  6. Update actor_registry_cache
"""
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update

from config import (
    ACTOR_CACHE_TTL_HOURS,
    IDENTITY_EMAIL, IDENTITY_PHONE, IDENTITY_SESSION, IDENTITY_SYSTEM,
    USER_TYPE_NEW, USER_TYPE_REGISTRY_KNOWN, USER_TYPE_RETURNING,
    USER_TYPE_COORDINATOR, USER_TYPE_ANONYMOUS,
    VOLUNTEER_ROLE, COORDINATOR_ROLE,
)
from services.database import (
    ActorRegistryCache, IdentityResolutionLog, Session as DBSession,
    get_db, is_db_healthy,
)
from services.serve_registry_client import volunteering_client

logger = logging.getLogger(__name__)


class IdentityResolution:
    """Result of a full identity resolution."""
    def __init__(
        self,
        actor_id: str,
        identity_type: str,
        channel: str,
        user_type: str,
        actor_type: str,
        serve_entity_id: Optional[str],
        has_prior_session: bool,
        last_session_id: Optional[str],
        profile_available: bool,
        suggested_workflow: str,
        resolution_status: str,
        resolution_ms: int = 0,
    ):
        self.actor_id          = actor_id
        self.identity_type     = identity_type
        self.channel           = channel
        self.user_type         = user_type
        self.actor_type        = actor_type
        self.serve_entity_id   = serve_entity_id
        self.has_prior_session = has_prior_session
        self.last_session_id   = last_session_id
        self.profile_available = profile_available
        self.suggested_workflow = suggested_workflow
        self.resolution_status = resolution_status
        self.resolution_ms     = resolution_ms

    def to_dict(self) -> dict:
        return {
            "actor_id":           self.actor_id,
            "identity_type":      self.identity_type,
            "channel":            self.channel,
            "user_type":          self.user_type,
            "actor_type":         self.actor_type,
            "serve_entity_id":    self.serve_entity_id,
            "has_prior_session":  self.has_prior_session,
            "last_session_id":    self.last_session_id,
            "profile_available":  self.profile_available,
            "suggested_workflow": self.suggested_workflow,
            "resolution_status":  self.resolution_status,
            "resolution_ms":      self.resolution_ms,
        }


class IdentityService:
    """
    Resolves actor identity through the cache → Serve Registry → session history chain.
    """

    async def resolve(
        self,
        actor_id: str,
        channel: str,
        identity_type: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> IdentityResolution:
        """
        Main entry point. Returns a fully populated IdentityResolution.

        actor_id      : the channel-native identity (email, phone, temp-session-id)
        channel       : whatsapp | web_ui | api | mobile | scheduler
        identity_type : email | phone | session_id | system  (inferred if not given)
        session_id    : if a session was already created, link the log to it
        """
        start_ms = int(time.monotonic() * 1000)

        # Infer identity_type from channel if not provided
        if not identity_type:
            identity_type = self._infer_identity_type(actor_id, channel)

        # S5: truly anonymous (no identity at all)
        if identity_type == IDENTITY_SESSION or not actor_id:
            resolution = IdentityResolution(
                actor_id=actor_id or "anonymous",
                identity_type=identity_type or IDENTITY_SESSION,
                channel=channel,
                user_type=USER_TYPE_ANONYMOUS,
                actor_type="volunteer",
                serve_entity_id=None,
                has_prior_session=False,
                last_session_id=None,
                profile_available=False,
                suggested_workflow="new_volunteer_onboarding",
                resolution_status="unresolved_anonymous",
                resolution_ms=0,
            )
            await self._log_resolution(resolution, session_id)
            return resolution

        # System actor — skip lookup
        if identity_type == IDENTITY_SYSTEM or channel == "scheduler":
            resolution = IdentityResolution(
                actor_id=actor_id,
                identity_type=IDENTITY_SYSTEM,
                channel=channel,
                user_type="system",
                actor_type="system",
                serve_entity_id=None,
                has_prior_session=False,
                last_session_id=None,
                profile_available=False,
                suggested_workflow="system_triggered",
                resolution_status="resolved_system",
            )
            return resolution

        # Step 1: Check cache
        cached = await self._check_cache(actor_id, channel)
        if cached:
            resolution = await self._build_from_cache(
                cached, actor_id, identity_type, channel
            )
            resolution.resolution_ms = int(time.monotonic() * 1000) - start_ms
            resolution.resolution_status = f"{resolution.resolution_status}_cache_hit"
            await self._log_resolution(resolution, session_id)
            return resolution

        # Step 2: Call Serve Registry
        serve_user = None
        actor_type = "volunteer"

        if identity_type == IDENTITY_EMAIL:
            serve_user = await volunteering_client.lookup_by_email(actor_id)
        elif identity_type == IDENTITY_PHONE:
            # Phone lookup: try email field won't work; currently no phone endpoint.
            # Phone-based channels (WhatsApp) will start as anonymous and collect email.
            serve_user = None

        # Step 3: Check for prior MCP sessions with this actor_id
        prior_session = await self._find_prior_session(actor_id, channel)

        # Step 4: Classify
        user_type, resolution_status, suggested_workflow = self._classify(
            serve_user=serve_user,
            prior_session=prior_session,
            actor_type=actor_type,
        )

        # Determine actor_type from role if found
        if serve_user and serve_user.get("role"):
            roles = serve_user.get("role", [])
            if "NEED_COORDINATOR" in roles:
                actor_type = "coordinator"
                user_type = USER_TYPE_COORDINATOR
                suggested_workflow = "need_coordination"
                resolution_status = "resolved_coordinator"

        serve_entity_id = serve_user.get("osid") if serve_user else None
        profile_available = serve_user is not None

        resolution = IdentityResolution(
            actor_id=actor_id,
            identity_type=identity_type,
            channel=channel,
            user_type=user_type,
            actor_type=actor_type,
            serve_entity_id=serve_entity_id,
            has_prior_session=prior_session is not None,
            last_session_id=str(prior_session["id"]) if prior_session else None,
            profile_available=profile_available,
            suggested_workflow=suggested_workflow,
            resolution_status=resolution_status,
            resolution_ms=int(time.monotonic() * 1000) - start_ms,
        )

        # Step 5: Update cache and log
        if serve_entity_id:
            await self._update_cache(resolution)
        await self._log_resolution(resolution, session_id)

        return resolution

    # ── Private helpers ───────────────────────────────────────────────────────

    def _infer_identity_type(self, actor_id: str, channel: str) -> str:
        if channel == "scheduler":
            return IDENTITY_SYSTEM
        if channel == "whatsapp":
            return IDENTITY_PHONE
        if actor_id and "@" in actor_id:
            return IDENTITY_EMAIL
        if actor_id and actor_id.startswith("+"):
            return IDENTITY_PHONE
        return IDENTITY_SESSION  # anonymous / temp session

    def _classify(
        self,
        serve_user: Optional[dict],
        prior_session: Optional[dict],
        actor_type: str,
    ):
        if serve_user is None:
            # Not in Serve Registry
            if prior_session:
                # Had AI sessions before — perhaps registered afterwards
                return (
                    USER_TYPE_RETURNING,
                    "resolved_returning_no_registry",
                    "new_volunteer_onboarding",
                )
            return (
                USER_TYPE_NEW,
                "resolved_new",
                "new_volunteer_onboarding",
            )
        else:
            # Found in Serve Registry
            if prior_session:
                return (
                    USER_TYPE_RETURNING,
                    "resolved_returning",
                    "returning_volunteer",
                )
            return (
                USER_TYPE_REGISTRY_KNOWN,
                "resolved_registry_known",
                "new_volunteer_onboarding",
            )

    async def _check_cache(
        self, actor_id: str, channel: str
    ) -> Optional[ActorRegistryCache]:
        if not is_db_healthy():
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(ActorRegistryCache).where(
                        ActorRegistryCache.actor_id == actor_id,
                        ActorRegistryCache.channel  == channel,
                        ActorRegistryCache.expires_at > datetime.utcnow(),
                    )
                )
                return result.scalar_one_or_none()
        except Exception as e:
            logger.warning(f"Cache lookup failed: {e}")
            return None

    async def _build_from_cache(
        self,
        cached: ActorRegistryCache,
        actor_id: str,
        identity_type: str,
        channel: str,
    ) -> IdentityResolution:
        prior_session = await self._find_prior_session(actor_id, channel)
        actor_type = cached.actor_type

        if actor_type == "coordinator":
            user_type = USER_TYPE_COORDINATOR
            suggested_workflow = "need_coordination"
            status = "resolved_coordinator"
        elif prior_session:
            user_type = USER_TYPE_RETURNING
            suggested_workflow = "returning_volunteer"
            status = "resolved_returning"
        elif cached.serve_entity_id:
            user_type = USER_TYPE_REGISTRY_KNOWN
            suggested_workflow = "new_volunteer_onboarding"
            status = "resolved_registry_known"
        else:
            user_type = USER_TYPE_NEW
            suggested_workflow = "new_volunteer_onboarding"
            status = "resolved_new"

        return IdentityResolution(
            actor_id=actor_id,
            identity_type=identity_type,
            channel=channel,
            user_type=user_type,
            actor_type=actor_type,
            serve_entity_id=cached.serve_entity_id,
            has_prior_session=prior_session is not None,
            last_session_id=str(prior_session["id"]) if prior_session else None,
            profile_available=cached.serve_entity_id is not None,
            suggested_workflow=suggested_workflow,
            resolution_status=status,
        )

    async def _find_prior_session(
        self, actor_id: str, channel: str
    ) -> Optional[dict]:
        """Return the most recent completed or active session for this actor."""
        if not is_db_healthy():
            return None
        try:
            async with get_db() as db:
                result = await db.execute(
                    select(DBSession)
                    .where(
                        DBSession.actor_id == actor_id,
                        DBSession.channel  == channel,
                        DBSession.status.in_(["active", "completed", "paused"]),
                    )
                    .order_by(DBSession.updated_at.desc())
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                if row:
                    return {
                        "id":           str(row.id),
                        "status":       row.status,
                        "stage":        row.stage,
                        "volunteer_id": row.volunteer_id,
                        "updated_at":   row.updated_at.isoformat() if row.updated_at else None,
                    }
        except Exception as e:
            logger.warning(f"Prior session lookup failed: {e}")
        return None

    async def _update_cache(self, resolution: IdentityResolution) -> None:
        if not is_db_healthy():
            return
        try:
            expires = datetime.utcnow() + timedelta(hours=ACTOR_CACHE_TTL_HOURS)
            async with get_db() as db:
                existing = await db.execute(
                    select(ActorRegistryCache).where(
                        ActorRegistryCache.actor_id == resolution.actor_id,
                        ActorRegistryCache.channel  == resolution.channel,
                    )
                )
                row = existing.scalar_one_or_none()
                if row:
                    await db.execute(
                        update(ActorRegistryCache)
                        .where(ActorRegistryCache.id == row.id)
                        .values(
                            serve_entity_id=resolution.serve_entity_id,
                            actor_type=resolution.actor_type,
                            is_onboarding_complete=(
                                resolution.user_type in (USER_TYPE_RETURNING,)
                            ),
                            last_active_at=datetime.utcnow(),
                            cached_at=datetime.utcnow(),
                            expires_at=expires,
                        )
                    )
                else:
                    db.add(ActorRegistryCache(
                        actor_id=resolution.actor_id,
                        identity_type=resolution.identity_type,
                        channel=resolution.channel,
                        actor_type=resolution.actor_type,
                        serve_entity_id=resolution.serve_entity_id,
                        is_onboarding_complete=(
                            resolution.user_type == USER_TYPE_RETURNING
                        ),
                        last_active_at=datetime.utcnow(),
                        cached_at=datetime.utcnow(),
                        expires_at=expires,
                    ))
        except Exception as e:
            logger.warning(f"Cache update failed: {e}")

    async def _log_resolution(
        self,
        resolution: IdentityResolution,
        session_id: Optional[str],
    ) -> None:
        if not is_db_healthy():
            return
        try:
            async with get_db() as db:
                db.add(IdentityResolutionLog(
                    session_id=UUID(session_id) if session_id else None,
                    actor_id=resolution.actor_id,
                    identity_type=resolution.identity_type,
                    channel=resolution.channel,
                    resolution_status=resolution.resolution_status,
                    user_type=resolution.user_type,
                    serve_entity_id=resolution.serve_entity_id,
                    resolution_ms=resolution.resolution_ms,
                ))
        except Exception as e:
            logger.warning(f"Resolution log write failed: {e}")


# Singleton
identity_service = IdentityService()
