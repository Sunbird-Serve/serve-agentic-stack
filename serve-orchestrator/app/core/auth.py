"""
JWT Authentication Module for SERVE Agentic Services
Validates Keycloak-issued JWTs using JWKS (RS256).

Usage in FastAPI endpoints:
    from app.core.auth import get_current_user, require_role

    @router.get("/protected")
    async def protected_endpoint(user: UserClaims = Depends(get_current_user)):
        ...

    @router.get("/admin-only")
    async def admin_endpoint(user: UserClaims = Depends(require_role("sAdmin"))):
        ...
"""
import os
import time
import logging
from typing import List, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "sunbird-serve")

JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
ISSUER = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"

# JWKS cache
_jwks_cache: dict = {}
_jwks_fetched_at: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour


# ── Models ─────────────────────────────────────────────────────────────────────

class UserClaims(BaseModel):
    """Decoded JWT claims relevant to the application."""
    sub: str  # Keycloak user ID
    email: Optional[str] = None
    preferred_username: Optional[str] = None
    name: Optional[str] = None
    roles: List[str] = []
    agency_id: Optional[str] = None
    agency_type: Optional[str] = None
    rc_osid: Optional[str] = None


# ── JWKS Fetching ──────────────────────────────────────────────────────────────

async def _fetch_jwks() -> dict:
    """Fetch JWKS from Keycloak and cache it."""
    global _jwks_cache, _jwks_fetched_at

    now = time.time()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_CACHE_TTL:
        return _jwks_cache

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_fetched_at = now
            logger.info("JWKS fetched and cached from %s", JWKS_URL)
            return _jwks_cache
    except Exception as e:
        logger.error("Failed to fetch JWKS from %s: %s", JWKS_URL, e)
        # Return stale cache if available
        if _jwks_cache:
            logger.warning("Using stale JWKS cache")
            return _jwks_cache
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to validate authentication (JWKS unavailable)",
        )


async def _get_signing_key(token: str) -> jwt.algorithms.RSAAlgorithm:
    """Get the RSA public key that matches the token's kid."""
    jwks_data = await _fetch_jwks()

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        )

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing key ID (kid)",
        )

    # Find matching key
    for key_data in jwks_data.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    # Key not found — maybe keys rotated. Force refresh cache and retry once.
    global _jwks_fetched_at
    _jwks_fetched_at = 0  # Invalidate cache
    jwks_data = await _fetch_jwks()

    for key_data in jwks_data.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token signing key not found in JWKS",
    )


# ── Token Extraction ───────────────────────────────────────────────────────────

def _extract_bearer_token(request: Request) -> str:
    """Extract Bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_header[7:]  # Strip "Bearer "


# ── Token Validation ───────────────────────────────────────────────────────────

async def _decode_token(token: str) -> dict:
    """Validate and decode a JWT token."""
    public_key = await _get_signing_key(token)

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={
                "verify_aud": False,  # Keycloak public client — audience varies
                "verify_exp": True,
                "verify_iss": True,
            },
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
        )
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def _extract_claims(payload: dict) -> UserClaims:
    """Extract application-relevant claims from decoded JWT payload."""
    # Roles from realm_access
    realm_roles = payload.get("realm_access", {}).get("roles", [])

    return UserClaims(
        sub=payload.get("sub", ""),
        email=payload.get("email"),
        preferred_username=payload.get("preferred_username"),
        name=payload.get("name"),
        roles=realm_roles,
        agency_id=payload.get("agencyId"),
        agency_type=payload.get("agencyType"),
        rc_osid=payload.get("rcOsid"),
    )


# ── FastAPI Dependencies ───────────────────────────────────────────────────────

async def get_current_user(request: Request) -> UserClaims:
    """
    FastAPI dependency that extracts and validates the JWT from the request.
    Returns UserClaims on success, raises 401 on failure.
    """
    token = _extract_bearer_token(request)
    payload = await _decode_token(token)
    return _extract_claims(payload)


def require_role(*allowed_roles: str):
    """
    Factory for a FastAPI dependency that requires the user to have
    at least one of the specified roles.

    Usage:
        @router.get("/ops")
        async def ops_endpoint(user: UserClaims = Depends(require_role("vCoordinator", "sAdmin"))):
            ...
    """
    async def _dependency(user: UserClaims = Depends(get_current_user)) -> UserClaims:
        if not any(role in user.roles for role in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return user

    return _dependency


def require_any_role(allowed_roles: List[str]):
    """Alias for require_role accepting a list."""
    return require_role(*allowed_roles)
