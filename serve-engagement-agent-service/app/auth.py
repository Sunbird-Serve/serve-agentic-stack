"""
JWT Authentication Module for SERVE Agent Services
Validates Keycloak-issued JWTs using JWKS (RS256).

Usage:
    from app.auth import get_current_user, UserClaims
    
    @app.post("/api/turn")
    async def process_turn(request: Request, user: UserClaims = Depends(get_current_user)):
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
    sub: str
    email: Optional[str] = None
    preferred_username: Optional[str] = None
    name: Optional[str] = None
    roles: List[str] = []
    agency_id: Optional[str] = None
    agency_type: Optional[str] = None
    rc_osid: Optional[str] = None


# ── JWKS Fetching ──────────────────────────────────────────────────────────────

async def _fetch_jwks() -> dict:
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
            return _jwks_cache
    except Exception as e:
        logger.error("Failed to fetch JWKS: %s", e)
        if _jwks_cache:
            return _jwks_cache
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="JWKS unavailable")


async def _get_signing_key(token: str):
    jwks_data = await _fetch_jwks()
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    kid = unverified_header.get("kid")
    if not kid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing kid")

    for key_data in jwks_data.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    # Force refresh and retry
    global _jwks_fetched_at
    _jwks_fetched_at = 0
    jwks_data = await _fetch_jwks()
    for key_data in jwks_data.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signing key not found")


# ── Dependencies ───────────────────────────────────────────────────────────────

def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth_header[7:]


async def get_current_user(request: Request) -> UserClaims:
    """FastAPI dependency: validates JWT and returns user claims."""
    token = _extract_bearer_token(request)
    public_key = await _get_signing_key(token)

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={"verify_aud": False, "verify_exp": True, "verify_iss": True},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

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


def require_role(*allowed_roles: str):
    """Dependency factory requiring specific roles."""
    async def _dependency(user: UserClaims = Depends(get_current_user)) -> UserClaims:
        if not any(role in user.roles for role in allowed_roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user
    return _dependency


async def get_optional_user(request: Request) -> Optional[UserClaims]:
    """
    FastAPI dependency: validates JWT if present, returns None if no token.
    
    Use this for endpoints that should work both with user JWT (forwarded from
    orchestrator) and without (internal service-to-service calls, WhatsApp webhook path).
    If a token IS provided but is invalid, still returns 401.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None  # No token — allow through (internal call)

    # Token present — must be valid
    token = auth_header[7:]
    public_key = await _get_signing_key(token)

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={"verify_aud": False, "verify_exp": True, "verify_iss": True},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("JWT validation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

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
